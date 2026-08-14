"""Signup, login, sessions, password reset and email verification."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import current_user
from app.models import (
    Department,
    LoginAttempt,
    Membership,
    PasswordResetToken,
    Role,
    User,
)
from app.schemas import (
    DepartmentOut,
    LoginIn,
    PasswordChangeIn,
    PasswordResetIn,
    PasswordResetRequestIn,
    SessionOut,
    SignupIn,
    UserOut,
)
from app.security import (
    expires_in,
    hash_password,
    issue_session,
    needs_rehash,
    new_token,
    password_problem,
    token_hash,
    utcnow,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _normalise(email: str) -> str:
    return email.strip().lower()


def _set_session(response: Response, user: User) -> None:
    response.set_cookie(
        settings.session_cookie,
        issue_session(str(user.id), user.session_epoch),
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        path="/",
    )


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _throttled(db: Session, email: str, ip: str) -> bool:
    since = utcnow() - dt.timedelta(seconds=settings.login_window)
    recent = db.scalar(
        select(func.count(LoginAttempt.id)).where(
            LoginAttempt.created_at >= since,
            (LoginAttempt.email == email) | (LoginAttempt.ip == ip),
        )
    )
    return (recent or 0) >= settings.login_max_attempts


def _session_payload(db: Session, user: User) -> SessionOut:
    rows = db.execute(
        select(Department, Membership.role)
        .join(Membership, Membership.department_id == Department.id)
        .where(Membership.user_id == user.id)
        .order_by(Department.name)
    ).all()
    departments = [
        DepartmentOut(
            id=d.id, name=d.name, hospital=d.hospital,
            timezone=d.timezone, settings=d.settings or {}, role=role,
        )
        for d, role in rows
    ]
    return SessionOut(user=UserOut.model_validate(user), departments=departments)


@router.post("/signup", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, response: Response, db: Session = Depends(get_db)) -> SessionOut:
    email = _normalise(body.email)

    problem = password_problem(body.password, email=email, name=body.name)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)

    user = User(
        email=email,
        password_hash=hash_password(body.password),
        name=body.name.strip(),
        last_login_at=utcnow(),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        # Do not confirm which addresses are registered.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "That email cannot be used to sign up. Try signing in or resetting your password.",
        )

    # A coordinator signing up alone still needs somewhere to put a rota.
    department = Department(name=(body.department_name or f"{user.name}'s department").strip())
    db.add(department)
    db.flush()
    db.add(Membership(user_id=user.id, department_id=department.id, role=Role.owner))
    db.commit()
    db.refresh(user)

    _set_session(response, user)
    return _session_payload(db, user)


@router.post("/login", response_model=SessionOut)
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = _normalise(body.email)
    ip = _client_ip(request)

    if _throttled(db, email, ip):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many sign-in attempts. Wait a few minutes and try again.",
        )

    user = db.scalar(select(User).where(User.email == email))
    # verify_password runs against a dummy hash when the user is missing, so
    # the response takes the same time either way.
    if not verify_password(body.password, user.password_hash if user else None) or not user:
        db.add(LoginAttempt(email=email, ip=ip))
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect.")

    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This account has been disabled.")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    user.last_login_at = utcnow()
    db.execute(delete(LoginAttempt).where(LoginAttempt.email == email))
    db.commit()
    db.refresh(user)

    _set_session(response, user)
    return _session_payload(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> Response:
    response.delete_cookie(settings.session_cookie, path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-everywhere", status_code=status.HTTP_204_NO_CONTENT)
def logout_everywhere(
    response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)
) -> Response:
    user.session_epoch += 1
    db.commit()
    response.delete_cookie(settings.session_cookie, path="/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/session", response_model=SessionOut)
def whoami(user: User = Depends(current_user), db: Session = Depends(get_db)) -> SessionOut:
    return _session_payload(db, user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChangeIn,
    response: Response,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> Response:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Current password is incorrect.")

    problem = password_problem(body.new_password, email=user.email, name=user.name)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)

    user.password_hash = hash_password(body.new_password)
    user.session_epoch += 1   # retire sessions elsewhere
    db.commit()
    db.refresh(user)

    _set_session(response, user)  # keep this one signed in
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/reset-request")
def request_password_reset(body: PasswordResetRequestIn, db: Session = Depends(get_db)) -> dict:
    email = _normalise(body.email)
    user = db.scalar(select(User).where(User.email == email))

    payload = {"sent": True}
    if user is None:
        # Same answer either way: this endpoint is unauthenticated.
        return payload

    token = new_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash(token),
            expires_at=expires_in(settings.password_reset_ttl),
        )
    )
    db.commit()

    # No mail transport is configured yet; outside production the token is
    # returned so the flow is usable and testable end to end.
    if not settings.is_production:
        payload["token"] = token
    return payload


@router.post("/password/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(body: PasswordResetIn, db: Session = Depends(get_db)) -> Response:
    record = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash(body.token))
    )
    if record is None or record.used_at is not None or record.expires_at <= utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or expired.")

    user = db.get(User, record.user_id)
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This reset link is invalid or expired.")

    problem = password_problem(body.new_password, email=user.email, name=user.name)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)

    user.password_hash = hash_password(body.new_password)
    user.session_epoch += 1      # a reset signs out every existing session
    record.used_at = utcnow()
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
