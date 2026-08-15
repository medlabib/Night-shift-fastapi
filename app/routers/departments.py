"""Departments, members, invitations and the doctor roster."""

from __future__ import annotations

import csv
import io
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import audit, mail
from app.db import get_db
from app.deps import RequireRole, current_user
from app.models import (
    CalendarFeed,
    Department,
    Doctor,
    Invitation,
    Leave,
    Membership,
    PreferenceWeight,
    RequestStatus,
    Role,
    Schedule,
    SwapRequest,
    TimeOffRequest,
    User,
)
from app.schemas import (
    DecisionIn,
    DepartmentIn,
    DepartmentOut,
    DoctorIn,
    DoctorOut,
    FeedOut,
    HistoryOut,
    ImportOut,
    ImportRow,
    InboxOut,
    InviteIn,
    InviteOut,
    LeaveIn,
    LinkDoctorIn,
    SwapOut,
    TimeOffOut,
)
from app.scheduling import preferences, service
from app.security import expires_in, new_token, token_hash, tokens_match, utcnow

router = APIRouter(prefix="/api/departments", tags=["departments"])

INVITE_TTL = 60 * 60 * 24 * 14  # two weeks


def _doctor_out(
    doctor: Doctor, *, user_name: str | None = None, has_feed: bool = False
) -> DoctorOut:
    return DoctorOut(
        id=doctor.id, name=doctor.name, grade=doctor.grade, is_active=doctor.is_active,
        leave=sorted(l.date for l in doctor.leave),
        user_id=doctor.user_id, user_name=user_name, has_feed=has_feed,
    )


def _decorate(db: Session, doctors: list[Doctor]) -> list[DoctorOut]:
    """Attach the linked account and feed state in two queries, not 2N."""
    if not doctors:
        return []
    linked = {d.user_id for d in doctors if d.user_id}
    names = (
        {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(linked))).all()}
        if linked
        else {}
    )
    feeds = set(
        db.scalars(
            select(CalendarFeed.doctor_id).where(
                CalendarFeed.doctor_id.in_([d.id for d in doctors]),
                CalendarFeed.revoked_at.is_(None),
            )
        ).all()
    )
    return [
        _doctor_out(d, user_name=names.get(d.user_id), has_feed=d.id in feeds) for d in doctors
    ]


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
    background: BackgroundTasks,
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

    if body.doctor_id is not None:
        doctor = db.get(Doctor, body.doctor_id)
        if doctor is None or doctor.department_id != department_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")
        if doctor.user_id is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "That roster entry already belongs to an account."
            )

    token = new_token()
    invite = Invitation(
        department_id=department_id, email=email, role=body.role,
        token_hash=token_hash(token), invited_by=membership.user_id,
        expires_at=expires_in(INVITE_TTL), doctor_id=body.doctor_id,
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)

    url = f"{mail.base_url(request)}/join/{token}"
    inviter = db.get(User, membership.user_id)
    department = db.get(Department, department_id)
    background.add_task(
        mail.send_invitation,
        to=invite.email,
        department=department.name if department else "a department",
        inviter=inviter.name if inviter else "A colleague",
        role=invite.role,
        url=url,
        expires_at=invite.expires_at,
        # The recipient has no account yet, so there is no preference to read:
        # write in the language of whoever is doing the inviting.
        lang=inviter.locale if inviter else "en",
    )

    return InviteOut(
        id=invite.id, email=invite.email, role=invite.role, expires_at=invite.expires_at,
        invite_url=url,
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

    # An invite issued against a roster entry claims it, so they arrive at
    # their own shifts rather than an empty department.
    if invite.doctor_id is not None:
        doctor = db.get(Doctor, invite.doctor_id)
        if doctor is not None and doctor.user_id is None:
            doctor.user_id = user.id

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
    return _decorate(db, list(doctors))


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
    return _decorate(db, [doctor])[0]


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
    return _decorate(db, [doctor])[0]


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
    return _decorate(db, [doctor])[0]


@router.post("/{department_id}/doctors/{doctor_id}/link", response_model=DoctorOut)
def link_doctor(
    department_id: uuid.UUID,
    doctor_id: uuid.UUID,
    body: LinkDoctorIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Attach a roster entry to an account, so that person can sign in as them.

    The account has to already be a member of the department: linking is not a
    way to grant access, only to say which member is which name on the rota.
    """
    doctor = db.get(Doctor, doctor_id)
    if doctor is None or doctor.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")

    target = db.scalar(
        select(Membership).where(
            Membership.department_id == department_id, Membership.user_id == body.user_id
        )
    )
    if target is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "That account is not a member of this department."
        )

    taken = db.scalar(
        select(Doctor).where(
            Doctor.department_id == department_id,
            Doctor.user_id == body.user_id,
            Doctor.id != doctor_id,
        )
    )
    if taken is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"That account is already linked to {taken.name}."
        )

    doctor.user_id = body.user_id
    db.commit()
    db.refresh(doctor)
    return _decorate(db, [doctor])[0]


@router.delete("/{department_id}/doctors/{doctor_id}/link", response_model=DoctorOut)
def unlink_doctor(
    department_id: uuid.UUID,
    doctor_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    doctor = db.get(Doctor, doctor_id)
    if doctor is None or doctor.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")
    doctor.user_id = None
    db.commit()
    db.refresh(doctor)
    return _decorate(db, [doctor])[0]


# ───────────────────────── importing a roster ─────────────────────────

# Header spellings people actually have in their spreadsheets.
COLUMNS = {
    "name": {"name", "doctor", "full name", "fullname", "nom", "médecin", "medecin", "الاسم"},
    "grade": {"grade", "level", "seniority", "niveau", "الدرجة"},
    "email": {"email", "e-mail", "mail", "adresse", "البريد"},
    "active": {"active", "is_active", "status", "actif", "نشط"},
}
FALSEY = {"0", "no", "false", "n", "inactive", "non", "لا"}


def _column_map(header: list[str]) -> dict[str, int]:
    found: dict[str, int] = {}
    for index, cell in enumerate(header):
        key = (cell or "").strip().lower().lstrip("﻿")
        for field, spellings in COLUMNS.items():
            if key in spellings and field not in found:
                found[field] = index
    return found


@router.post("/{department_id}/doctors/import", response_model=ImportOut)
async def import_roster(
    department_id: uuid.UUID,
    file: UploadFile = File(...),
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Load a roster from a CSV of names, grades and email addresses.

    A bad row is reported and skipped rather than failing the upload: a
    department of forty with one typo should get thirty-nine doctors and one
    line to fix, not an error page.
    """
    raw = await file.read()
    if len(raw) > 1_000_000:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Keep the file under 1 MB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Spreadsheets exported on Windows are often still in Latin-1.
        text = raw.decode("latin-1", errors="replace")

    rows = list(csv.reader(io.StringIO(text)))
    rows = [r for r in rows if any((cell or "").strip() for cell in r)]
    if not rows:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That file has no rows.")

    columns = _column_map(rows[0])
    if "name" in columns:
        body, first_line = rows[1:], 2
    else:
        # No recognisable header: treat the first column as names throughout.
        columns, body, first_line = {"name": 0}, rows, 1

    existing = {
        d.name.strip().lower(): d
        for d in db.scalars(select(Doctor).where(Doctor.department_id == department_id)).all()
    }
    members = {
        u.email.lower(): u
        for u in db.scalars(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.department_id == department_id)
        ).all()
    }
    claimed = {d.user_id for d in existing.values() if d.user_id}

    out = ImportOut()
    seen: set[str] = set()

    def cell(row: list[str], field: str) -> str:
        index = columns.get(field)
        if index is None or index >= len(row):
            return ""
        return (row[index] or "").strip()

    for offset, row in enumerate(body):
        line = offset + first_line
        name = cell(row, "name")
        if not name:
            out.failed += 1
            out.rows.append(ImportRow(line=line, status="error", detail="No name in this row."))
            continue
        if len(name) > 160:
            out.failed += 1
            out.rows.append(ImportRow(line=line, name=name[:40], status="error",
                                      detail="That name is too long."))
            continue

        key = name.lower()
        if key in seen:
            out.skipped += 1
            out.rows.append(ImportRow(line=line, name=name, status="skipped",
                                      detail="Repeated in this file."))
            continue
        seen.add(key)

        grade = cell(row, "grade") or None
        active_cell = cell(row, "active").lower()
        is_active = active_cell not in FALSEY if active_cell else True

        doctor = existing.get(key)
        if doctor is None:
            doctor = Doctor(
                department_id=department_id, name=name, grade=grade, is_active=is_active
            )
            db.add(doctor)
            db.flush()
            existing[key] = doctor
            out.created += 1
            state = "created"
        else:
            doctor.grade = grade or doctor.grade
            doctor.is_active = is_active
            out.updated += 1
            state = "updated"

        detail = None
        email = cell(row, "email").lower()
        if email:
            user = members.get(email)
            if user is None:
                detail = "No member of this department has that address, so nothing was linked."
            elif doctor.user_id is None and user.id not in claimed:
                doctor.user_id = user.id
                claimed.add(user.id)
                detail = f"Linked to {user.name}."
        out.rows.append(ImportRow(line=line, name=name, status=state, detail=detail))

    db.commit()
    return out


# ─────────────────────── live calendar feeds ───────────────────────


@router.post("/{department_id}/doctors/{doctor_id}/feed", response_model=FeedOut, status_code=201)
def create_feed(
    department_id: uuid.UUID,
    doctor_id: uuid.UUID,
    request: Request,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Mint this doctor's standing calendar subscription.

    Unlike a share link, which freezes one schedule, this URL answers with
    whatever is published now — so a phone calendar picks up next month's rota
    without anyone re-importing anything. Calling it again rotates the token
    and retires the previous one.
    """
    doctor = db.get(Doctor, doctor_id)
    if doctor is None or doctor.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")

    now = utcnow()
    for old in db.scalars(
        select(CalendarFeed).where(
            CalendarFeed.doctor_id == doctor_id, CalendarFeed.revoked_at.is_(None)
        )
    ).all():
        old.revoked_at = now

    token = new_token()
    feed = CalendarFeed(
        department_id=department_id, doctor_id=doctor_id,
        token_hash=token_hash(token), created_by=membership.user_id,
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)

    return FeedOut(
        doctor_id=doctor.id, doctor_name=doctor.name, created_at=feed.created_at,
        # The only time the token is ever visible.
        url=f"{mail.base_url(request)}/api/feeds/{token}.ics",
    )


@router.get("/{department_id}/feeds", response_model=list[FeedOut])
def list_feeds(
    department_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(CalendarFeed, Doctor)
        .join(Doctor, Doctor.id == CalendarFeed.doctor_id)
        .where(CalendarFeed.department_id == department_id, CalendarFeed.revoked_at.is_(None))
        .order_by(Doctor.name)
    ).all()
    return [
        FeedOut(
            doctor_id=doctor.id, doctor_name=doctor.name, created_at=feed.created_at,
            last_read_at=feed.last_read_at, reads=feed.reads,
        )
        for feed, doctor in rows
    ]


@router.delete("/{department_id}/doctors/{doctor_id}/feed", status_code=204)
def revoke_feed(
    department_id: uuid.UUID,
    doctor_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    doctor = db.get(Doctor, doctor_id)
    if doctor is None or doctor.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")
    now = utcnow()
    for feed in db.scalars(
        select(CalendarFeed).where(
            CalendarFeed.doctor_id == doctor_id, CalendarFeed.revoked_at.is_(None)
        )
    ).all():
        feed.revoked_at = now
    db.commit()


# ──────────────── requests waiting on a coordinator ────────────────


def _time_off_row(row: TimeOffRequest, names: dict[uuid.UUID, str], department: str) -> TimeOffOut:
    return TimeOffOut(
        id=row.id, department_id=row.department_id, department_name=department,
        doctor_id=row.doctor_id, doctor_name=names.get(row.doctor_id, "a former colleague"),
        start_date=row.start_date, end_date=row.end_date, nights=len(row.dates),
        reason=row.reason, status=row.status, decided_at=row.decided_at,
        decision_note=row.decision_note, created_at=row.created_at,
    )


def _swap_row(row: SwapRequest, names: dict[uuid.UUID, str], schedules: dict) -> SwapOut:
    schedule = schedules.get(row.schedule_id)
    return SwapOut(
        id=row.id, department_id=row.department_id, schedule_id=row.schedule_id,
        schedule_name=schedule.name if schedule else None, date=row.date,
        from_doctor_id=row.from_doctor_id,
        from_doctor_name=names.get(row.from_doctor_id, "a former colleague"),
        to_doctor_id=row.to_doctor_id,
        to_doctor_name=names.get(row.to_doctor_id, "a former colleague"),
        message=row.message, status=row.status, decided_at=row.decided_at,
        decision_note=row.decision_note, created_at=row.created_at,
    )


@router.get("/{department_id}/requests", response_model=InboxOut)
def list_requests(
    department_id: uuid.UUID,
    pending_only: bool = True,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Everything the department's doctors are waiting to hear about."""
    time_off = select(TimeOffRequest).where(TimeOffRequest.department_id == department_id)
    swaps = select(SwapRequest).where(SwapRequest.department_id == department_id)
    if pending_only:
        time_off = time_off.where(TimeOffRequest.status == RequestStatus.pending)
        swaps = swaps.where(SwapRequest.status == RequestStatus.pending)

    leave_rows = db.scalars(time_off.order_by(TimeOffRequest.start_date)).all()
    swap_rows = db.scalars(swaps.order_by(SwapRequest.date)).all()

    names = {
        d.id: d.name
        for d in db.scalars(select(Doctor).where(Doctor.department_id == department_id)).all()
    }
    department = db.get(Department, department_id)
    schedules = {
        s.id: s
        for s in db.scalars(
            select(Schedule).where(Schedule.id.in_({r.schedule_id for r in swap_rows}))
        ).all()
    } if swap_rows else {}

    return InboxOut(
        time_off=[
            _time_off_row(r, names, department.name if department else "") for r in leave_rows
        ],
        swaps=[_swap_row(r, names, schedules) for r in swap_rows],
    )


@router.post("/{department_id}/time-off/{request_id}/decide", response_model=TimeOffOut)
def decide_time_off(
    department_id: uuid.UUID,
    request_id: uuid.UUID,
    body: DecisionIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Approve or decline booked leave.

    Approving writes the dates into the roster's leave, which is what the
    solver reads — so the next rota simply cannot put them on those nights.
    Rotas already built are not rewritten: re-tune does that, deliberately,
    when the coordinator is ready.
    """
    row = db.get(TimeOffRequest, request_id)
    if row is None or row.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
    if row.status != RequestStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "That request has already been decided.")

    if body.approve:
        booked = set(
            db.scalars(
                select(Leave.date).where(
                    Leave.doctor_id == row.doctor_id,
                    Leave.date >= row.start_date,
                    Leave.date <= row.end_date,
                )
            ).all()
        )
        for day in row.dates:
            if day not in booked:
                db.add(Leave(doctor_id=row.doctor_id, date=day, reason=row.reason or "Leave"))

    row.status = RequestStatus.approved if body.approve else RequestStatus.declined
    row.decided_by = membership.user_id
    row.decided_at = utcnow()
    row.decision_note = body.note
    db.commit()
    db.refresh(row)

    doctor = db.get(Doctor, row.doctor_id)
    department = db.get(Department, department_id)
    return _time_off_row(
        row, {doctor.id: doctor.name} if doctor else {},
        department.name if department else "",
    )


@router.post("/{department_id}/swaps/{request_id}/decide", response_model=SwapOut)
def decide_swap(
    department_id: uuid.UUID,
    request_id: uuid.UUID,
    body: DecisionIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Approve or decline a proposed swap.

    Approving performs the swap through the same code a coordinator's own edit
    uses, so it lands in the edit history and feeds the preference model
    identically. If the rota has moved on since the request was made — someone
    else already has that night — approval fails with the reason.
    """
    row = db.get(SwapRequest, request_id)
    if row is None or row.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
    if row.status != RequestStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "That request has already been decided.")

    schedule = db.get(Schedule, row.schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That schedule no longer exists.")

    if body.approve:
        try:
            service.apply_swap(
                db, schedule,
                day=row.date, doctor_out=row.from_doctor_id, doctor_in=row.to_doctor_id,
                actor_id=membership.user_id,
            )
        except ValueError as problem:
            raise HTTPException(status.HTTP_409_CONFLICT, str(problem))

    row.status = RequestStatus.approved if body.approve else RequestStatus.declined
    row.decided_by = membership.user_id
    row.decided_at = utcnow()
    row.decision_note = body.note
    db.commit()
    db.refresh(row)

    names = {
        d.id: d.name
        for d in db.scalars(
            select(Doctor).where(Doctor.id.in_({row.from_doctor_id, row.to_doctor_id}))
        ).all()
    }
    return _swap_row(row, names, {schedule.id: schedule})


# ───────────────────────────── history ─────────────────────────────


@router.get("/{department_id}/history", response_model=list[HistoryOut])
def department_history(
    department_id: uuid.UUID,
    limit: int = 100,
    membership: Membership = Depends(RequireRole(Role.member)),
    db: Session = Depends(get_db),
):
    """Who changed what, across every rota in this department."""
    return audit.describe(db, department_id=department_id, limit=limit)


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
