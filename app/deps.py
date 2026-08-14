"""Request dependencies: the current user, and department authorisation."""

from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import ROLE_RANK, Department, Membership, Role, User
from app.security import read_session


def current_user_optional(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(settings.session_cookie)
    if not token:
        return None
    data = read_session(token)
    if not data:
        return None
    try:
        user_id = uuid.UUID(data.get("uid", ""))
    except (ValueError, TypeError):
        return None

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    # A password change or "sign out everywhere" bumps the epoch, retiring
    # every cookie issued before it.
    if int(data.get("epoch", -1)) != user.session_epoch:
        return None
    return user


def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    return user


class RequireRole:
    """Authorise the caller against a department, at or above `minimum`.

    Usage: `membership = Depends(RequireRole(Role.coordinator))` on a route
    that takes a `department_id` path parameter.
    """

    def __init__(self, minimum: Role = Role.member):
        self.minimum = minimum

    def __call__(
        self,
        department_id: uuid.UUID,
        user: User = Depends(current_user),
        db: Session = Depends(get_db),
    ) -> Membership:
        membership = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id, Membership.department_id == department_id
            )
        )
        # Same response whether the department is missing or simply not theirs,
        # so the API does not confirm which departments exist.
        if membership is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found.")
        if ROLE_RANK[membership.role] < ROLE_RANK[self.minimum]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"This action needs the {self.minimum.value} role.",
            )
        return membership


def get_department(
    department_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.member)),
    db: Session = Depends(get_db),
) -> Department:
    department = db.get(Department, department_id)
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found.")
    return department
