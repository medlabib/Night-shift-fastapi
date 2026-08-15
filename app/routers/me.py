"""What a doctor can do with their own account.

The rest of the API is coordinator-shaped: you act on a department. This is the
other side of it — a doctor signs in, sees their own nights, asks for leave, and
asks a named colleague to take a shift. None of it changes a rota directly. A
request is a request until a coordinator decides on it, and approval runs
through the same code a coordinator's own edit does.

Which roster entries "mine" means is `Doctor.user_id`: one login can be linked
to a doctor in more than one department, which is ordinary enough for someone
who covers two rotas.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mail
from app.db import get_db
from app.deps import current_user
from app.models import (
    Assignment,
    CalendarFeed,
    Department,
    Doctor,
    Leave,
    Membership,
    RequestStatus,
    Schedule,
    SwapRequest,
    TimeOffRequest,
    User,
)
from app.schemas import (
    DepartmentOut,
    DoctorOut,
    FeedOut,
    MyProfile,
    MyShift,
    SwapOut,
    SwapProposeIn,
    TimeOffIn,
    TimeOffOut,
    UserOut,
)
from app.security import new_token, token_hash

router = APIRouter(prefix="/api/me", tags=["me"])

# How far ahead the personal view looks. A rota a year out is not what someone
# opens this page for.
HORIZON_DAYS = 120
MAX_LEAVE_SPAN = 90


def _my_doctors(db: Session, user: User) -> list[Doctor]:
    return list(
        db.scalars(
            select(Doctor).where(Doctor.user_id == user.id).order_by(Doctor.name)
        ).all()
    )


def _pick(doctors: list[Doctor], doctor_id: uuid.UUID | None) -> Doctor:
    """Which of my roster entries this request is about."""
    if not doctors:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Your account is not linked to anyone on a roster. Ask a coordinator to link it.",
        )
    if doctor_id is None:
        if len(doctors) > 1:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "You are on more than one roster — say which one this is for.",
            )
        return doctors[0]
    found = next((d for d in doctors if d.id == doctor_id), None)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That is not one of your roster entries.")
    return found


def _time_off_out(row: TimeOffRequest, doctor: Doctor, department: Department | None) -> TimeOffOut:
    return TimeOffOut(
        id=row.id,
        department_id=row.department_id,
        department_name=department.name if department else None,
        doctor_id=row.doctor_id,
        doctor_name=doctor.name,
        start_date=row.start_date,
        end_date=row.end_date,
        nights=len(row.dates),
        reason=row.reason,
        status=row.status,
        decided_at=row.decided_at,
        decision_note=row.decision_note,
        created_at=row.created_at,
    )


def _swap_out(row: SwapRequest, names: dict[uuid.UUID, str], schedule: Schedule | None) -> SwapOut:
    return SwapOut(
        id=row.id,
        department_id=row.department_id,
        schedule_id=row.schedule_id,
        schedule_name=schedule.name if schedule else None,
        date=row.date,
        from_doctor_id=row.from_doctor_id,
        from_doctor_name=names.get(row.from_doctor_id, "a former colleague"),
        to_doctor_id=row.to_doctor_id,
        to_doctor_name=names.get(row.to_doctor_id, "a former colleague"),
        message=row.message,
        status=row.status,
        decided_at=row.decided_at,
        decision_note=row.decision_note,
        created_at=row.created_at,
    )


# ───────────────────────────── my rota ─────────────────────────────


@router.get("", response_model=MyProfile)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> MyProfile:
    """Who I am, which rosters I am on, and what I am working next."""
    doctors = _my_doctors(db, user)
    departments = db.execute(
        select(Department, Membership.role)
        .join(Membership, Membership.department_id == Department.id)
        .where(Membership.user_id == user.id)
        .order_by(Department.name)
    ).all()

    return MyProfile(
        user=UserOut.model_validate(user),
        doctors=[
            DoctorOut(
                id=d.id, name=d.name, grade=d.grade, is_active=d.is_active,
                leave=sorted(l.date for l in d.leave), user_id=d.user_id, user_name=user.name,
            )
            for d in doctors
        ],
        departments=[
            DepartmentOut(
                id=d.id, name=d.name, hospital=d.hospital, timezone=d.timezone,
                settings=d.settings or {}, role=role,
            )
            for d, role in departments
        ],
        shifts=_shifts(db, doctors),
    )


@router.get("/shifts", response_model=list[MyShift])
def my_shifts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _shifts(db, _my_doctors(db, user))


def _shifts(db: Session, doctors: list[Doctor]) -> list[MyShift]:
    if not doctors:
        return []
    today = dt.date.today()
    horizon = today + dt.timedelta(days=HORIZON_DAYS)
    mine = {d.id for d in doctors}

    rows = db.execute(
        select(Assignment, Schedule, Department)
        .join(Schedule, Schedule.id == Assignment.schedule_id)
        .join(Department, Department.id == Schedule.department_id)
        .where(
            Assignment.doctor_id.in_(mine),
            Assignment.date >= today,
            Assignment.date <= horizon,
        )
        .order_by(Assignment.date)
    ).all()
    if not rows:
        return []

    # Who else is on each of those nights, so a swap can be aimed at someone.
    wanted = {(a.schedule_id, a.date) for a, _, _ in rows}
    company: dict[tuple[uuid.UUID, dt.date], list[str]] = {}
    others = db.execute(
        select(Assignment, Doctor.name)
        .join(Doctor, Doctor.id == Assignment.doctor_id)
        .where(
            Assignment.schedule_id.in_({s for s, _ in wanted}),
            Assignment.date.in_({d for _, d in wanted}),
        )
    ).all()
    for assignment, name in others:
        if assignment.doctor_id in mine:
            continue
        company.setdefault((assignment.schedule_id, assignment.date), []).append(name)

    return [
        MyShift(
            date=assignment.date,
            points=assignment.points,
            department_id=department.id,
            department_name=department.name,
            schedule_id=schedule.id,
            schedule_name=schedule.name,
            status=schedule.status,
            doctor_id=assignment.doctor_id,
            alongside=sorted(company.get((schedule.id, assignment.date), [])),
        )
        for assignment, schedule, department in rows
    ]


# ───────────────────────────── leave ─────────────────────────────


@router.post("/time-off", response_model=TimeOffOut, status_code=status.HTTP_201_CREATED)
def request_time_off(
    body: TimeOffIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    doctor = _pick(_my_doctors(db, user), body.doctor_id)

    if body.end_date < body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The end date is before the start.")
    if (body.end_date - body.start_date).days > MAX_LEAVE_SPAN:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Ask for {MAX_LEAVE_SPAN} nights or fewer at a time.",
        )
    if body.end_date < dt.date.today():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Those dates are in the past.")

    overlapping = db.scalar(
        select(TimeOffRequest).where(
            TimeOffRequest.doctor_id == doctor.id,
            TimeOffRequest.status == RequestStatus.pending,
            TimeOffRequest.start_date <= body.end_date,
            TimeOffRequest.end_date >= body.start_date,
        )
    )
    if overlapping is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have a request waiting for those dates."
        )

    row = TimeOffRequest(
        department_id=doctor.department_id,
        doctor_id=doctor.id,
        start_date=body.start_date,
        end_date=body.end_date,
        reason=body.reason,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _time_off_out(row, doctor, db.get(Department, doctor.department_id))


@router.get("/time-off", response_model=list[TimeOffOut])
def my_time_off(user: User = Depends(current_user), db: Session = Depends(get_db)):
    doctors = {d.id: d for d in _my_doctors(db, user)}
    if not doctors:
        return []
    rows = db.scalars(
        select(TimeOffRequest)
        .where(TimeOffRequest.doctor_id.in_(doctors))
        .order_by(TimeOffRequest.start_date.desc())
    ).all()
    departments = {
        d.id: d
        for d in db.scalars(
            select(Department).where(
                Department.id.in_({r.department_id for r in rows})
            )
        ).all()
    } if rows else {}
    return [_time_off_out(r, doctors[r.doctor_id], departments.get(r.department_id)) for r in rows]


@router.delete("/time-off/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_time_off(
    request_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    doctors = {d.id for d in _my_doctors(db, user)}
    row = db.get(TimeOffRequest, request_id)
    if row is None or row.doctor_id not in doctors:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
    if row.status != RequestStatus.pending:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "That request has already been decided."
        )
    row.status = RequestStatus.withdrawn
    db.commit()


# ───────────────────────────── swaps ─────────────────────────────


@router.post("/swaps", response_model=SwapOut, status_code=status.HTTP_201_CREATED)
def propose_swap(
    body: SwapProposeIn, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    """Ask a named colleague to take one of my nights."""
    schedule = db.get(Schedule, body.schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found.")

    candidates = [d for d in _my_doctors(db, user) if d.department_id == schedule.department_id]
    doctor = _pick(candidates, body.from_doctor_id)

    mine = db.scalar(
        select(Assignment).where(
            Assignment.schedule_id == schedule.id,
            Assignment.doctor_id == doctor.id,
            Assignment.date == body.date,
        )
    )
    if mine is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "You are not on call that night.")

    target = db.get(Doctor, body.to_doctor_id)
    if target is None or target.department_id != schedule.department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")
    if target.id == doctor.id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick a different colleague.")

    taken = db.scalar(
        select(Assignment).where(
            Assignment.schedule_id == schedule.id,
            Assignment.doctor_id == target.id,
            Assignment.date == body.date,
        )
    )
    if taken is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "They are already on call that night.")

    on_leave = db.scalar(
        select(Leave).where(Leave.doctor_id == target.id, Leave.date == body.date)
    )
    if on_leave is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, f"{target.name} is on leave that night.")

    duplicate = db.scalar(
        select(SwapRequest).where(
            SwapRequest.schedule_id == schedule.id,
            SwapRequest.from_doctor_id == doctor.id,
            SwapRequest.date == body.date,
            SwapRequest.status == RequestStatus.pending,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "You already have a swap waiting for that night."
        )

    row = SwapRequest(
        department_id=schedule.department_id,
        schedule_id=schedule.id,
        from_doctor_id=doctor.id,
        to_doctor_id=target.id,
        date=body.date,
        message=body.message,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _swap_out(row, {doctor.id: doctor.name, target.id: target.name}, schedule)


@router.get("/swaps", response_model=list[SwapOut])
def my_swaps(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Swaps I proposed, and swaps proposed to me."""
    mine = {d.id for d in _my_doctors(db, user)}
    if not mine:
        return []
    rows = db.scalars(
        select(SwapRequest)
        .where(
            SwapRequest.from_doctor_id.in_(mine) | SwapRequest.to_doctor_id.in_(mine)
        )
        .order_by(SwapRequest.created_at.desc())
    ).all()
    if not rows:
        return []

    ids = {r.from_doctor_id for r in rows} | {r.to_doctor_id for r in rows}
    names = {
        d.id: d.name for d in db.scalars(select(Doctor).where(Doctor.id.in_(ids))).all()
    }
    schedules = {
        s.id: s
        for s in db.scalars(
            select(Schedule).where(Schedule.id.in_({r.schedule_id for r in rows}))
        ).all()
    }
    return [_swap_out(r, names, schedules.get(r.schedule_id)) for r in rows]


@router.delete("/swaps/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
def withdraw_swap(
    request_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    mine = {d.id for d in _my_doctors(db, user)}
    row = db.get(SwapRequest, request_id)
    if row is None or row.from_doctor_id not in mine:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found.")
    if row.status != RequestStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "That request has already been decided.")
    row.status = RequestStatus.withdrawn
    db.commit()


# ───────────────────────── my calendar feed ─────────────────────────


@router.post("/feed", response_model=FeedOut, status_code=status.HTTP_201_CREATED)
def create_my_feed(
    request: Request,
    doctor_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    """My own subscription URL, without having to ask a coordinator for it.

    It only ever contains my nights, so there is nothing to authorise beyond
    being the person it belongs to. Calling it again rotates the token, which
    is also how you revoke a link you pasted somewhere you regret.
    """
    doctor = _pick(_my_doctors(db, user), doctor_id)

    now = dt.datetime.now(dt.timezone.utc)
    for old in db.scalars(
        select(CalendarFeed).where(
            CalendarFeed.doctor_id == doctor.id, CalendarFeed.revoked_at.is_(None)
        )
    ).all():
        old.revoked_at = now

    token = new_token()
    feed = CalendarFeed(
        department_id=doctor.department_id, doctor_id=doctor.id,
        token_hash=token_hash(token), created_by=user.id,
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)

    return FeedOut(
        doctor_id=doctor.id, doctor_name=doctor.name, created_at=feed.created_at,
        url=f"{mail.base_url(request)}/api/feeds/{token}.ics",
    )


@router.delete("/feed", status_code=status.HTTP_204_NO_CONTENT)
def revoke_my_feed(
    doctor_id: uuid.UUID | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    doctor = _pick(_my_doctors(db, user), doctor_id)
    now = dt.datetime.now(dt.timezone.utc)
    for feed in db.scalars(
        select(CalendarFeed).where(
            CalendarFeed.doctor_id == doctor.id, CalendarFeed.revoked_at.is_(None)
        )
    ).all():
        feed.revoked_at = now
    db.commit()
