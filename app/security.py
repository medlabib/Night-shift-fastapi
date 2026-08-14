"""Password hashing, session cookies and single-use tokens."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings

_hasher = PasswordHasher()

# A real Argon2 hash to verify against when the account does not exist, so
# login timing does not reveal which emails are registered.
_DUMMY_HASH = _hasher.hash("timing-equalisation-placeholder")

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password)
    except (VerifyMismatchError, InvalidHashError, TypeError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def _appears_as_word(needle: str, haystack: str) -> bool:
    """Match on word boundaries so "Other" does not flag "another-good-password"."""
    if len(needle) < 4:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", haystack) is not None


def password_problem(password: str, *, email: str = "", name: str = "") -> str | None:
    """Return why a password is unacceptable, or None if it is fine."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Use at least {MIN_PASSWORD_LENGTH} characters."

    lowered = password.lower()
    if lowered in {"password", "12345678910", "nightshift", "passwordpassword"}:
        return "That password is too common."

    local = email.split("@")[0].lower()
    if local and _appears_as_word(local, lowered):
        return "Do not use your email address in your password."

    # Check each part of the name separately: "Dr Lead" should catch "lead".
    for part in re.split(r"[^a-z0-9]+", name.lower()):
        if _appears_as_word(part, lowered):
            return "Do not use your name in your password."
    return None


# ───────────────────────────── sessions ─────────────────────────────

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="nightshift-session")


def issue_session(user_id: str, epoch: int) -> str:
    """Sign a session cookie. `epoch` lets us invalidate every existing one."""
    return _serializer.dumps({"uid": str(user_id), "epoch": int(epoch)})


def read_session(token: str) -> dict | None:
    try:
        return _serializer.loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None


# ─────────────────────────── opaque tokens ───────────────────────────
# Reset, verification, invite and share tokens are random strings; only
# their hash is stored, so a database leak cannot be replayed.


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def token_hash(token: str) -> str:
    return hashlib.sha256(f"{settings.secret_key}{token}".encode()).hexdigest()


def tokens_match(token: str, stored_hash: str) -> bool:
    return hmac.compare_digest(token_hash(token), stored_hash)


def expires_in(seconds: int) -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)
