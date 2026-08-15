"""Bridge between the database and the solver's plain-Python domain."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    Assignment,
    AssignmentSource,
    Doctor as DoctorRow,
    EditEvent,
    Leave,
    PreferenceWeight,
    Schedule,
    ScheduleStatus,
)
from app.scheduling.domain import (
    CARRY_WINDOW_DAYS,
    DEFAULT_WEIGHTS,
    Doctor,
    RotaRequest,
    RotaResult,
    weight_for,
)
from app.scheduling.solver import solve, summarise
from app.schemas import AssignmentOut, ScheduleOut, ShortfallOut, ValidationOut


def load_roster(db: Session, department_id: uuid.UUID, only: list[uuid.UUID] | None = None):
    stmt = select(DoctorRow).where(
        DoctorRow.department_id == department_id, DoctorRow.is_active.is_(True)
    )
    if only:
        stmt = stmt.where(DoctorRow.id.in_(only))
    return db.scalars(stmt.order_by(DoctorRow.name)).all()


def load_leave(db: Session, doctor_ids: list[uuid.UUID]) -> dict[str, set[dt.date]]:
    if not doctor_ids:
        return {}
    rows = db.scalars(select(Leave).where(Leave.doctor_id.in_(doctor_ids))).all()
    out: dict[str, set[dt.date]] = {}
    for row in rows:
        out.setdefault(str(row.doctor_id), set()).add(row.date)
    return out


def load_preferences(db: Session, department_id: uuid.UUID) -> dict[tuple[str | None, str], float]:
    rows = db.scalars(
        select(PreferenceWeight).where(PreferenceWeight.department_id == department_id)
    ).all()
    return {
        (str(r.subject_id) if r.subject_id else None, r.feature): r.weight
        for r in rows
        if r.weight
    }


def load_history(
    db: Session,
    department_id: uuid.UUID,
    roster: list[DoctorRow],
    before: dt.date,
    window_days: int,
    *,
    exclude: uuid.UUID | None = None,
) -> tuple[dict[str, float], dict[str, float], set[str]]:
    """What each doctor already worked in the run-up to a new period.

    Only **published** rotas count. Drafts are proposals, and a coordinator who
    generates six attempts at October should not have all six charged against
    anyone. Only nights *before* the new period count, so an overlapping rota
    contributes its earlier half and nothing more.

    Returns carried points, carried weekend nights, and the ids of doctors who
    joined part-way through the window — they have no comparable record, and
    the solver treats them as average rather than as owing a heavy month.
    """
    points: dict[str, float] = {str(d.id): 0.0 for d in roster}
    weekends: dict[str, float] = {str(d.id): 0.0 for d in roster}
    if window_days <= 0 or not roster:
        return {}, {}, set()

    since = before - dt.timedelta(days=window_days)
    stmt = (
        select(Assignment)
        .join(Schedule, Schedule.id == Assignment.schedule_id)
        .where(
            Schedule.department_id == department_id,
            Schedule.status == ScheduleStatus.published,
            Assignment.doctor_id.in_([d.id for d in roster]),
            Assignment.date >= since,
            Assignment.date < before,
        )
    )
    if exclude is not None:
        stmt = stmt.where(Schedule.id != exclude)

    rows = db.scalars(stmt).all()
    if not rows:
        return {}, {}, set()

    for row in rows:
        key = str(row.doctor_id)
        points[key] = points.get(key, 0.0) + float(row.points)
        if row.date.weekday() >= 5:
            weekends[key] = weekends.get(key, 0.0) + 1

    cutoff = dt.datetime.combine(since, dt.time.min, tzinfo=dt.timezone.utc)
    partial = {
        str(d.id)
        for d in roster
        if d.created_at and d.created_at > cutoff and not points.get(str(d.id))
    }
    return points, weekends, partial


def build_request(
    db: Session,
    department_id: uuid.UUID,
    config: dict,
    *,
    locked: dict[str, set[dt.date]] | None = None,
    anchor: dict[str, set[dt.date]] | None = None,
    change_penalty: int = 0,
    use_preferences: bool = True,
    time_limit: float | None = None,
    schedule_id: uuid.UUID | None = None,
) -> RotaRequest:
    """Turn a stored schedule config into a solver request."""
    doctor_ids = [uuid.UUID(x) for x in config.get("doctor_ids", [])] or None
    roster = load_roster(db, department_id, doctor_ids)
    leave = load_leave(db, [d.id for d in roster])

    coverage = {
        dt.date.fromisoformat(k): int(v)
        for k, v in (config.get("coverage_by_date") or {}).items()
    }

    start = dt.date.fromisoformat(config["start_date"])
    prior_points, prior_weekends, partial = load_history(
        db, department_id, list(roster), start,
        int(config.get("carry_forward_days", CARRY_WINDOW_DAYS)),
        exclude=schedule_id,
    )

    return RotaRequest(
        doctors=[Doctor(id=str(d.id), name=d.name, grade=d.grade) for d in roster],
        start=start,
        end=dt.date.fromisoformat(config["end_date"]),
        coverage=coverage,
        default_coverage=int(config.get("coverage", 2)),
        graded=bool(config.get("graded")),
        grades=list(config.get("grades") or []),
        holidays={dt.date.fromisoformat(d) for d in config.get("holidays", [])},
        weights={**DEFAULT_WEIGHTS, **(config.get("weights") or {})},
        unavailable=leave,
        min_rest_nights=int(config.get("min_rest_nights", 1)),
        max_shifts_per_window=int(config.get("max_shifts_per_window", 2)),
        spread_window_nights=int(config.get("spread_window_nights", 7)),
        locked=locked or {},
        anchor=anchor,
        change_penalty=change_penalty,
        preferences=load_preferences(db, department_id) if use_preferences else {},
        prior_points=prior_points,
        prior_weekends=prior_weekends,
        prior_partial=partial,
        time_limit=time_limit or settings.solver_time_limit,
        workers=settings.workers,
    )


def persist_result(db: Session, schedule: Schedule, req: RotaRequest, result: RotaResult) -> None:
    """Replace a schedule's assignments with a solved rota, keeping locks."""
    kept = {
        (str(a.doctor_id), a.date): a
        for a in schedule.assignments
        if a.locked
    }
    for assignment in list(schedule.assignments):
        db.delete(assignment)
    db.flush()

    for doctor_id, days in result.assignments.items():
        for day in days:
            previous = kept.get((doctor_id, day))
            db.add(
                Assignment(
                    schedule_id=schedule.id,
                    doctor_id=uuid.UUID(doctor_id),
                    date=day,
                    points=req.points_for(day),
                    locked=previous is not None,
                    source=previous.source if previous else AssignmentSource.solver,
                )
            )

    schedule.metrics = {
        **result.metrics,
        "shortfalls": [
            {
                "date": s.date.isoformat(), "grade": s.grade,
                "required": s.required, "assigned": s.assigned, "reason": s.reason,
            }
            for s in result.shortfalls
        ],
        "diagnostics": result.diagnostics,
    }
    schedule.solver_status = result.status
    schedule.solve_seconds = round(result.solve_seconds, 3)


def schedule_out(db: Session, schedule: Schedule) -> ScheduleOut:
    names = {
        d.id: d
        for d in db.scalars(
            select(DoctorRow).where(DoctorRow.department_id == schedule.department_id)
        ).all()
    }
    assignments = sorted(schedule.assignments, key=lambda a: (a.date, names[a.doctor_id].name))
    metrics = dict(schedule.metrics or {})
    shortfalls = metrics.pop("shortfalls", [])
    diagnostics = metrics.pop("diagnostics", [])

    return ScheduleOut(
        id=schedule.id,
        department_id=schedule.department_id,
        name=schedule.name,
        start_date=schedule.start_date,
        end_date=schedule.end_date,
        status=schedule.status,
        config=schedule.config or {},
        metrics=metrics,
        solver_status=schedule.solver_status,
        solve_seconds=schedule.solve_seconds,
        created_at=schedule.created_at,
        updated_at=schedule.updated_at,
        assignments=[
            AssignmentOut(
                doctor_id=a.doctor_id,
                doctor_name=names[a.doctor_id].name,
                grade=names[a.doctor_id].grade,
                date=a.date,
                points=a.points,
                locked=a.locked,
                source=a.source.value,
            )
            for a in assignments
            if a.doctor_id in names
        ],
        shortfalls=[ShortfallOut(**s) for s in shortfalls],
        diagnostics=diagnostics,
    )


def current_assignments(schedule: Schedule) -> dict[str, set[dt.date]]:
    out: dict[str, set[dt.date]] = {}
    for a in schedule.assignments:
        out.setdefault(str(a.doctor_id), set()).add(a.date)
    return out


def locked_assignments(schedule: Schedule) -> dict[str, set[dt.date]]:
    out: dict[str, set[dt.date]] = {}
    for a in schedule.assignments:
        if a.locked:
            out.setdefault(str(a.doctor_id), set()).add(a.date)
    return out


def recompute_metrics(db: Session, schedule: Schedule) -> None:
    """Refresh fairness metrics after a manual edit, keeping any shortfall notes."""
    req = build_request(
        db, schedule.department_id, schedule.config,
        use_preferences=False, schedule_id=schedule.id,
    )
    result = RotaResult(
        assignments={k: sorted(v) for k, v in current_assignments(schedule).items()},
        status=schedule.solver_status or "MANUAL",
        solve_seconds=schedule.solve_seconds or 0.0,
    )
    previous = dict(schedule.metrics or {})
    schedule.metrics = {
        **summarise(req, result),
        "shortfalls": previous.get("shortfalls", []),
        "diagnostics": previous.get("diagnostics", []),
    }


def validate(db: Session, schedule: Schedule) -> ValidationOut:
    """Check a hand-edited rota against the same rules the solver enforces."""
    req = build_request(
        db, schedule.department_id, schedule.config,
        use_preferences=False, schedule_id=schedule.id,
    )
    by_doctor = current_assignments(schedule)
    by_night: dict[dt.date, list[str]] = {}
    for doctor_id, days in by_doctor.items():
        for day in days:
            by_night.setdefault(day, []).append(doctor_id)

    names = {d.id: d.name for d in req.doctors}
    grade_of = {d.id: d.grade for d in req.doctors}
    errors: list[str] = []
    warnings: list[str] = []

    for doctor_id, days in by_doctor.items():
        name = names.get(doctor_id, "A doctor")
        for day in sorted(days):
            if not req.is_available(doctor_id, day):
                errors.append(f"{name} is on leave on {day:%a %d %b}.")
        ordered = sorted(days)
        for a, b in zip(ordered, ordered[1:]):
            gap = (b - a).days
            if gap <= req.min_rest_nights:
                warnings.append(
                    f"{name} works {a:%a %d %b} and {b:%a %d %b} with "
                    f"{gap - 1} night(s) of rest between them."
                )

        # A run of merely-legal gaps is the thing coordinators actually object
        # to: a shift every other night for a fortnight obeys the minimum rest
        # at every step and is still punishing.
        span, cap = req.spread_window_nights, req.max_shifts_per_window
        if span >= 2 and len(ordered) > cap:
            for i in range(len(ordered) - cap):
                window = ordered[i : i + cap + 1]
                if (window[-1] - window[0]).days < span:
                    warnings.append(
                        f"{name} works {len(window)} nights between {window[0]:%a %d %b} "
                        f"and {window[-1]:%a %d %b} — more than {cap} in {span} nights."
                    )
                    break

    for day in req.days:
        on_call = by_night.get(day, [])
        if req.graded and req.grades:
            for grade in req.grades:
                need = req.required_for(day, grade)
                got = sum(1 for d in on_call if grade_of.get(d) == grade)
                if got < need:
                    errors.append(f"{day:%a %d %b}: {grade} has {got} of {need} on call.")
                elif got > need:
                    warnings.append(f"{day:%a %d %b}: {grade} has {got}, more than the {need} asked for.")
        else:
            need = req.required_on(day)
            if len(on_call) < need:
                errors.append(f"{day:%a %d %b}: {len(on_call)} of {need} on call.")
            elif len(on_call) > need:
                warnings.append(f"{day:%a %d %b}: {len(on_call)} on call, more than the {need} asked for.")

    return ValidationOut(ok=not errors, errors=errors, warnings=warnings)


def apply_swap(
    db: Session,
    schedule: Schedule,
    *,
    day: dt.date,
    doctor_out: uuid.UUID,
    doctor_in: uuid.UUID,
    actor_id: uuid.UUID | None,
    lock: bool = True,
) -> None:
    """Hand one night from one doctor to another, and record the edit.

    Shared by the coordinator's own swap and by approving a doctor's swap
    request, so an approved request goes through exactly the same path — and
    lands in the same history — as a hand edit.

    Raises `ValueError` when the move cannot be made; the caller decides what
    HTTP status that deserves.
    """
    if not (schedule.start_date <= day <= schedule.end_date):
        raise ValueError(
            f"{day} is outside this schedule ({schedule.start_date} to {schedule.end_date})."
        )

    outgoing = db.scalar(
        select(Assignment).where(
            Assignment.schedule_id == schedule.id,
            Assignment.doctor_id == doctor_out,
            Assignment.date == day,
        )
    )
    if outgoing is None:
        raise ValueError("That doctor is not on call that night.")

    already = db.scalar(
        select(Assignment).where(
            Assignment.schedule_id == schedule.id,
            Assignment.doctor_id == doctor_in,
            Assignment.date == day,
        )
    )
    if already is not None:
        raise ValueError("They are already on call that night.")

    outgoing.doctor_id = doctor_in
    outgoing.locked = lock
    outgoing.source = AssignmentSource.manual

    db.add(
        EditEvent(
            schedule_id=schedule.id,
            department_id=schedule.department_id,
            actor_id=actor_id,
            kind="swap",
            payload={
                "date": day.isoformat(),
                "doctor_out": str(doctor_out),
                "doctor_in": str(doctor_in),
            },
        )
    )
    db.flush()
    db.refresh(schedule)
    recompute_metrics(db, schedule)


def points_for_date(schedule: Schedule, day: dt.date) -> float:
    config = schedule.config or {}
    holidays = {dt.date.fromisoformat(d) for d in config.get("holidays", [])}
    weights = {**DEFAULT_WEIGHTS, **(config.get("weights") or {})}
    return weight_for(day, holidays, weights)


def run(db: Session, schedule: Schedule, req: RotaRequest) -> RotaResult:
    result = solve(req)
    persist_result(db, schedule, req, result)
    return result
