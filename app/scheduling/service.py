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
    Leave,
    PreferenceWeight,
    Schedule,
)
from app.scheduling.domain import DEFAULT_WEIGHTS, Doctor, RotaRequest, RotaResult, weight_for
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
) -> RotaRequest:
    """Turn a stored schedule config into a solver request."""
    doctor_ids = [uuid.UUID(x) for x in config.get("doctor_ids", [])] or None
    roster = load_roster(db, department_id, doctor_ids)
    leave = load_leave(db, [d.id for d in roster])

    coverage = {
        dt.date.fromisoformat(k): int(v)
        for k, v in (config.get("coverage_by_date") or {}).items()
    }

    return RotaRequest(
        doctors=[Doctor(id=str(d.id), name=d.name, grade=d.grade) for d in roster],
        start=dt.date.fromisoformat(config["start_date"]),
        end=dt.date.fromisoformat(config["end_date"]),
        coverage=coverage,
        default_coverage=int(config.get("coverage", 2)),
        graded=bool(config.get("graded")),
        grades=list(config.get("grades") or []),
        holidays={dt.date.fromisoformat(d) for d in config.get("holidays", [])},
        weights={**DEFAULT_WEIGHTS, **(config.get("weights") or {})},
        unavailable=leave,
        min_rest_nights=int(config.get("min_rest_nights", 1)),
        locked=locked or {},
        anchor=anchor,
        change_penalty=change_penalty,
        preferences=load_preferences(db, department_id) if use_preferences else {},
        time_limit=time_limit or settings.solver_time_limit,
        workers=settings.solver_workers,
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
    req = build_request(db, schedule.department_id, schedule.config, use_preferences=False)
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
    req = build_request(db, schedule.department_id, schedule.config, use_preferences=False)
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


def points_for_date(schedule: Schedule, day: dt.date) -> float:
    config = schedule.config or {}
    holidays = {dt.date.fromisoformat(d) for d in config.get("holidays", [])}
    weights = {**DEFAULT_WEIGHTS, **(config.get("weights") or {})}
    return weight_for(day, holidays, weights)


def run(db: Session, schedule: Schedule, req: RotaRequest) -> RotaResult:
    result = solve(req)
    persist_result(db, schedule, req, result)
    return result
