"""Generate, browse, hand-edit and fine-tune rotas."""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import RequireRole
from app.models import (
    Assignment,
    AssignmentSource,
    Doctor,
    EditEvent,
    Membership,
    Role,
    Schedule,
    ScheduleStatus,
)
from app.scheduling import service
from app.scheduling.solver import structural_blockers
from app.schemas import (
    AssignIn,
    GenerateIn,
    LockIn,
    RetuneIn,
    ScheduleOut,
    ScheduleSummary,
    SwapIn,
    UnassignIn,
    ValidationOut,
)

router = APIRouter(prefix="/api/departments/{department_id}/schedules", tags=["schedules"])


def _config(body: GenerateIn) -> dict:
    return {
        "start_date": body.start_date.isoformat(),
        "end_date": body.end_date.isoformat(),
        "coverage": body.coverage,
        "coverage_by_date": {d.isoformat(): n for d, n in body.coverage_by_date.items()},
        "graded": body.graded,
        "grades": body.grades,
        "holidays": [d.isoformat() for d in body.holidays],
        "weights": body.weights,
        "min_rest_nights": body.min_rest_nights,
        "max_shifts_per_window": body.max_shifts_per_window,
        "spread_window_nights": body.spread_window_nights,
        "doctor_ids": [str(x) for x in (body.doctor_ids or [])],
    }


def _load(db: Session, department_id: uuid.UUID, schedule_id: uuid.UUID) -> Schedule:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None or schedule.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found.")
    return schedule


def _doctor(db: Session, department_id: uuid.UUID, doctor_id: uuid.UUID) -> Doctor:
    doctor = db.get(Doctor, doctor_id)
    if doctor is None or doctor.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")
    return doctor


def _in_period(schedule: Schedule, day: dt.date) -> None:
    if not (schedule.start_date <= day <= schedule.end_date):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{day} is outside this schedule ({schedule.start_date} to {schedule.end_date}).",
        )


def _record(db: Session, schedule: Schedule, membership: Membership, kind: str, payload: dict):
    db.add(
        EditEvent(
            schedule_id=schedule.id,
            department_id=schedule.department_id,
            actor_id=membership.user_id,
            kind=kind,
            payload=payload,
        )
    )


# ───────────────────────────── generate ─────────────────────────────


@router.post("", response_model=ScheduleOut, status_code=status.HTTP_201_CREATED)
def generate(
    department_id: uuid.UUID,
    body: GenerateIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    if body.end_date < body.start_date:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "End date is before the start date.")
    if (body.end_date - body.start_date).days > 365:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Keep a schedule to a year or less.")

    config = _config(body)
    schedule = Schedule(
        department_id=department_id,
        name=body.name or f"Rota {body.start_date:%d %b} – {body.end_date:%d %b %Y}",
        start_date=body.start_date,
        end_date=body.end_date,
        config=config,
        created_by=membership.user_id,
    )
    db.add(schedule)
    db.flush()

    req = service.build_request(
        db, department_id, config,
        use_preferences=body.use_preferences, time_limit=body.time_limit,
    )
    if not req.doctors:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "No active doctors on the roster for this schedule.",
        )

    # Refuse the arithmetically impossible outright, rather than storing a
    # third of a rota. Merely tight requests still get built, with their gaps
    # reported as shortfalls.
    blockers = structural_blockers(req)
    if blockers:
        db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"message": "No rota satisfies these rules.", "reasons": blockers},
        )

    result = service.run(db, schedule, req)
    if not result.feasible:
        db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"message": "No rota satisfies these rules.", "reasons": result.diagnostics},
        )

    db.commit()
    db.refresh(schedule)
    return service.schedule_out(db, schedule)


@router.get("", response_model=list[ScheduleSummary])
def list_schedules(
    department_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.member)),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Schedule)
        .where(Schedule.department_id == department_id)
        .order_by(Schedule.start_date.desc())
    ).all()
    return [ScheduleSummary.model_validate(s) for s in rows]


@router.get("/{schedule_id}", response_model=ScheduleOut)
def get_schedule(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.member)),
    db: Session = Depends(get_db),
):
    return service.schedule_out(db, _load(db, department_id, schedule_id))


@router.delete("/{schedule_id}", status_code=204)
def delete_schedule(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    db.delete(_load(db, department_id, schedule_id))
    db.commit()


@router.post("/{schedule_id}/publish", response_model=ScheduleOut)
def publish(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    schedule = _load(db, department_id, schedule_id)
    check = service.validate(db, schedule)
    if not check.ok:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"message": "Fix these before publishing.", "errors": check.errors},
        )
    schedule.status = ScheduleStatus.published
    db.commit()
    db.refresh(schedule)
    return service.schedule_out(db, schedule)


# ───────────────────────────── editing ─────────────────────────────


@router.post("/{schedule_id}/assign", response_model=ScheduleOut)
def assign(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    body: AssignIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    schedule = _load(db, department_id, schedule_id)
    _doctor(db, department_id, body.doctor_id)
    _in_period(schedule, body.date)

    existing = db.scalar(
        select(Assignment).where(
            Assignment.schedule_id == schedule.id,
            Assignment.doctor_id == body.doctor_id,
            Assignment.date == body.date,
        )
    )
    if existing is None:
        db.add(
            Assignment(
                schedule_id=schedule.id,
                doctor_id=body.doctor_id,
                date=body.date,
                points=service.points_for_date(schedule, body.date),
                locked=body.lock,
                source=AssignmentSource.manual,
            )
        )
        _record(db, schedule, membership, "assign",
                {"doctor_id": str(body.doctor_id), "date": body.date.isoformat()})

    db.flush()
    db.refresh(schedule)
    service.recompute_metrics(db, schedule)
    db.commit()
    db.refresh(schedule)
    return service.schedule_out(db, schedule)


@router.post("/{schedule_id}/unassign", response_model=ScheduleOut)
def unassign(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    body: UnassignIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    schedule = _load(db, department_id, schedule_id)
    existing = db.scalar(
        select(Assignment).where(
            Assignment.schedule_id == schedule.id,
            Assignment.doctor_id == body.doctor_id,
            Assignment.date == body.date,
        )
    )
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That doctor is not on call that night.")

    db.delete(existing)
    _record(db, schedule, membership, "unassign",
            {"doctor_id": str(body.doctor_id), "date": body.date.isoformat()})
    db.flush()
    db.refresh(schedule)
    service.recompute_metrics(db, schedule)
    db.commit()
    db.refresh(schedule)
    return service.schedule_out(db, schedule)


@router.post("/{schedule_id}/swap", response_model=ScheduleOut)
def swap(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    body: SwapIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Hand one night from one doctor to another, in a single step."""
    schedule = _load(db, department_id, schedule_id)
    _doctor(db, department_id, body.doctor_in)
    _in_period(schedule, body.date)

    outgoing = db.scalar(
        select(Assignment).where(
            Assignment.schedule_id == schedule.id,
            Assignment.doctor_id == body.doctor_out,
            Assignment.date == body.date,
        )
    )
    if outgoing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That doctor is not on call that night.")

    already = db.scalar(
        select(Assignment).where(
            Assignment.schedule_id == schedule.id,
            Assignment.doctor_id == body.doctor_in,
            Assignment.date == body.date,
        )
    )
    if already is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "They are already on call that night.")

    outgoing.doctor_id = body.doctor_in
    outgoing.locked = body.lock
    outgoing.source = AssignmentSource.manual
    _record(db, schedule, membership, "swap", {
        "date": body.date.isoformat(),
        "doctor_out": str(body.doctor_out),
        "doctor_in": str(body.doctor_in),
    })
    db.flush()
    db.refresh(schedule)
    service.recompute_metrics(db, schedule)
    db.commit()
    db.refresh(schedule)
    return service.schedule_out(db, schedule)


@router.post("/{schedule_id}/lock", response_model=ScheduleOut)
def set_lock(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    body: LockIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Pin or unpin one night so a re-solve leaves it alone."""
    schedule = _load(db, department_id, schedule_id)
    existing = db.scalar(
        select(Assignment).where(
            Assignment.schedule_id == schedule.id,
            Assignment.doctor_id == body.doctor_id,
            Assignment.date == body.date,
        )
    )
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That doctor is not on call that night.")
    existing.locked = body.locked
    db.commit()
    db.refresh(schedule)
    return service.schedule_out(db, schedule)


@router.get("/{schedule_id}/validate", response_model=ValidationOut)
def validate_schedule(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.member)),
    db: Session = Depends(get_db),
):
    return service.validate(db, _load(db, department_id, schedule_id))


@router.post("/{schedule_id}/retune", response_model=ScheduleOut)
def retune(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    body: RetuneIn,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    """Re-solve around the parts a coordinator has already settled.

    Locked nights are held fixed; the rest is rebuilt. With `stay_close` the
    solver also pays a penalty for moving anything else, so the rota people
    have already seen changes as little as possible.
    """
    schedule = _load(db, department_id, schedule_id)
    locked = service.locked_assignments(schedule) if body.keep_locked else {}
    anchor = service.current_assignments(schedule) if body.stay_close else None

    req = service.build_request(
        db, department_id, schedule.config,
        locked=locked,
        anchor=anchor,
        change_penalty=3 if body.stay_close else 0,
        time_limit=body.time_limit,
    )
    result = service.run(db, schedule, req)
    if not result.feasible:
        db.rollback()
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {
                "message": "No rota satisfies these rules with those nights pinned.",
                "reasons": result.diagnostics,
            },
        )

    _record(db, schedule, membership, "retune",
            {"kept_locked": body.keep_locked, "stay_close": body.stay_close})
    db.commit()
    db.refresh(schedule)
    return service.schedule_out(db, schedule)
