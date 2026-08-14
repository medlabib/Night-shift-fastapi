"""Departments, members, invitations and the doctor roster."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import RequireRole, current_user
from app.models import (
    Department,
    Doctor,
    Invitation,
    Leave,
    Membership,
    PreferenceWeight,
    Role,
    User,
)
from app.schemas import (
    DepartmentIn,
    DepartmentOut,
    DoctorIn,
    DoctorOut,
    InviteIn,
    InviteOut,
    LeaveIn,
)
from app.scheduling import preferences
from app.security import expires_in, new_token, token_hash, tokens_match, utcnow

router = APIRouter(prefix="/api/departments", tags=["departments"])

INVITE_TTL = 60 * 60 * 24 * 14  # two weeks


def _doctor_out(doctor: Doctor) -> DoctorOut:
    return DoctorOut(
        id=doctor.id, name=doctor.name, grade=doctor.grade, is_active=doctor.is_active,
        leave=sorted(l.date for l in doctor.leave),
    )


@router.get("", response_model=list[DepartmentOut])
def list_departments(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Department, Membership.role)
        .join(Membership, Membership.department_id == Department.id)
        .where(Membership.user_id == user.id)
        .order_by(Department.name)
    ).all()
    return [
        DepartmentOut(id=d.id, name=d.name, hospital=d.hospital, timezone=d.timezone,
                      settings=d.settings or {}, role=role)
        for d, role in rows
    ]


@router.post("", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
def create_department(
    body: DepartmentIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    department = Department(
        name=body.name.strip(), hospital=body.hospital, timezone=body.timezone,
        settings=body.settings or {},
    )
    db.add(department)
    db.flush()
    db.add(Membership(user_id=user.id, department_id=department.id, role=Role.owner))
    db.commit()
    db.refresh(department)
    return DepartmentOut(
        id=department.id, name=department.name, hospital=department.hospital,
        timezone=department.timezone, settings=department.settings or {}, role=Role.owner,
    )


@router.patch("/{department_id}", response_model=DepartmentOut)
def update_department(
    department_id: uuid.UUID,
    body: DepartmentIn,
    membership: Membership = Depends(RequireRole(Role.owner)),
    db: Session = Depends(get_db),
):
    department = db.get(Department, department_id)
    department.name = body.name.strip()
    department.hospital = body.hospital
    department.timezone = body.timezone
    if body.settings:
        department.settings = body.settings
    db.commit()
    db.refresh(department)
    return DepartmentOut(
        id=department.id, name=department.name, hospital=department.hospital,
        timezone=department.timezone, settings=department.settings or {}, role=membership.role,
    )


# ───────────────────────────── members ─────────────────────────────


@router.get("/{department_id}/members")
def list_members(
    department_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.member)),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(User, Membership.role)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.department_id == department_id)
        .order_by(User.name)
    ).all()
    return [
        {"id": str(u.id), "name": u.name, "email": u.email, "role": role.value}
        for u, role in rows
    ]


@router.post("/{department_id}/invites", response_model=InviteOut, status_code=201)
def invite_member(
    department_id: uuid.UUID,
    body: InviteIn,
    request: Request,
    membership: Membership = Depends(RequireRole(Role.owner)),
    db: Session = Depends(get_db),
):
    email = body.email.strip().lower()
    already = db.scalar(
        select(Membership)
        .join(User, User.id == Membership.user_id)
        .where(Membership.department_id == department_id, User.email == email)
    )
    if already:
        raise HTTPException(status.HTTP_409_CONFLICT, "They are already in this department.")

    token = new_token()
    invite = Invitation(
        department_id=department_id, email=email, role=body.role,
        token_hash=token_hash(token), invited_by=membership.user_id,
        expires_at=expires_in(INVITE_TTL),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    base = str(request.base_url).rstrip("/")
    return InviteOut(
        id=invite.id, email=invite.email, role=invite.role, expires_at=invite.expires_at,
        invite_url=f"{base}/join/{token}",
    )


@router.get("/{department_id}/invites", response_model=list[InviteOut])
def list_invites(
    department_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.owner)),
    db: Session = Depends(get_db),
):
    invites = db.scalars(
        select(Invitation)
        .where(Invitation.department_id == department_id, Invitation.accepted_at.is_(None))
        .order_by(Invitation.created_at.desc())
    ).all()
    # The token itself is unrecoverable, by design: re-invite to get a new link.
    return [
        InviteOut(id=i.id, email=i.email, role=i.role, expires_at=i.expires_at) for i in invites
    ]


@router.delete("/{department_id}/members/{user_id}", status_code=204)
def remove_member(
    department_id: uuid.UUID,
    user_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.owner)),
    db: Session = Depends(get_db),
):
    owners = db.scalars(
        select(Membership).where(
            Membership.department_id == department_id, Membership.role == Role.owner
        )
    ).all()
    target = db.scalar(
        select(Membership).where(
            Membership.department_id == department_id, Membership.user_id == user_id
        )
    )
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "They are not in this department.")
    if target.role == Role.owner and len(owners) == 1:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This is the last owner. Promote someone else first.",
        )
    db.delete(target)
    db.commit()


# Accepting an invite only needs a signed-in user, not existing membership.
join_router = APIRouter(prefix="/api/invites", tags=["departments"])


@join_router.post("/{token}/accept", response_model=DepartmentOut)
def accept_invite(
    token: str, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    invite = db.scalar(select(Invitation).where(Invitation.token_hash == token_hash(token)))
    if (
        invite is None
        or not tokens_match(token, invite.token_hash)
        or invite.accepted_at is not None
        or invite.expires_at <= utcnow()
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This invitation is invalid or expired.")
    if invite.email != user.email.lower():
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This invitation was sent to a different email address."
        )

    existing = db.scalar(
        select(Membership).where(
            Membership.department_id == invite.department_id, Membership.user_id == user.id
        )
    )
    if existing is None:
        db.add(Membership(user_id=user.id, department_id=invite.department_id, role=invite.role))
    invite.accepted_at = utcnow()
    db.commit()

    department = db.get(Department, invite.department_id)
    return DepartmentOut(
        id=department.id, name=department.name, hospital=department.hospital,
        timezone=department.timezone, settings=department.settings or {}, role=invite.role,
    )


# ───────────────────────────── roster ─────────────────────────────


@router.get("/{department_id}/doctors", response_model=list[DoctorOut])
def list_doctors(
    department_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.member)),
    db: Session = Depends(get_db),
):
    doctors = db.scalars(
        select(Doctor).where(Doctor.department_id == department_id).order_by(Doctor.name)
    ).all()
    return [_doctor_out(d) for d in doctors]


@router.post("/{department_id}/doctors", response_model=DoctorOut, status_code=201)
def add_doctor(
    department_id: uuid.UUID,
    body: DoctorIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    doctor = Doctor(
        department_id=department_id, name=body.name.strip(),
        grade=body.grade, is_active=body.is_active,
    )
    db.add(doctor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That doctor is already on the roster.")
    db.refresh(doctor)
    return _doctor_out(doctor)


@router.patch("/{department_id}/doctors/{doctor_id}", response_model=DoctorOut)
def update_doctor(
    department_id: uuid.UUID,
    doctor_id: uuid.UUID,
    body: DoctorIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    doctor = db.get(Doctor, doctor_id)
    if doctor is None or doctor.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")
    doctor.name = body.name.strip()
    doctor.grade = body.grade
    doctor.is_active = body.is_active
    db.commit()
    db.refresh(doctor)
    return _doctor_out(doctor)


@router.delete("/{department_id}/doctors/{doctor_id}", status_code=204)
def remove_doctor(
    department_id: uuid.UUID,
    doctor_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    doctor = db.get(Doctor, doctor_id)
    if doctor is None or doctor.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")
    db.delete(doctor)
    db.commit()


@router.put("/{department_id}/doctors/{doctor_id}/leave", response_model=DoctorOut)
def set_leave(
    department_id: uuid.UUID,
    doctor_id: uuid.UUID,
    body: LeaveIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Replace this doctor's booked leave with the dates supplied."""
    doctor = db.get(Doctor, doctor_id)
    if doctor is None or doctor.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")

    db.execute(delete(Leave).where(Leave.doctor_id == doctor_id))
    for day in sorted(set(body.dates)):
        db.add(Leave(doctor_id=doctor_id, date=day, reason=body.reason))
    db.commit()
    db.refresh(doctor)
    return _doctor_out(doctor)


# ───────────────────────── learned preferences ─────────────────────────
# Mounted on the department, not on a schedule: what a department prefers
# outlives any one rota.


@router.post("/{department_id}/preferences/train")
def train_preferences(
    department_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Refit the preference model from this department's edit history."""
    preferences.train(db, department_id)
    return preferences.describe(db, department_id)


@router.get("/{department_id}/preferences")
def get_preferences(
    department_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.member)),
    db: Session = Depends(get_db),
) -> list[dict]:
    """What the model has learned, in plain words, so it can be audited."""
    return preferences.describe(db, department_id)


@router.delete("/{department_id}/preferences", status_code=204)
def clear_preferences(
    department_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Forget everything learned so far."""
    db.execute(
        delete(PreferenceWeight).where(PreferenceWeight.department_id == department_id)
    )
    db.commit()
