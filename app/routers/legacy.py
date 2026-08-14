"""The original public POST /schedule, now answered by the CP-SAT solver.

Kept so anything already calling the API keeps working and gets the better
engine for free. The request and response shapes are unchanged, quirks and all:
graded responses still key nights by timestamp and nest stats under each grade.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.scheduling.domain import DEFAULT_WEIGHTS, Doctor, RotaRequest
from app.scheduling.solver import solve

router = APIRouter(tags=["legacy"])


class ScheduleInput(BaseModel):
    doctor_names: str
    start_date: str
    end_date: str
    same_num_doctors: str
    num_doctors: Optional[int] = None
    num_doctors_per_night: Optional[Dict[str, int]] = None
    holiday_days: str = ""
    find: int = 0
    department_is_graded: str = "N"
    doctors_grades: Optional[Dict[str, str]] = None
    shift_requirements: Optional[Dict[str, List[str]]] = None
    grades: Optional[List[str]] = None
    doctor_not_present: Optional[Dict[str, str]] = None


def _dates(raw: str | None) -> set[dt.date]:
    if not raw or not raw.strip():
        return set()
    return {dt.date.fromisoformat(p.strip()) for p in raw.split(",") if p.strip()}


@router.post("/schedule")
def schedule(data: ScheduleInput) -> dict:
    try:
        start = dt.date.fromisoformat(data.start_date)
        end = dt.date.fromisoformat(data.end_date)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Dates must be YYYY-MM-DD.")

    names = [n.strip() for n in data.doctor_names.split(",") if n.strip()]
    if not names:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "No doctors supplied.")

    graded = data.department_is_graded == "Y"
    grades = list(data.grades or [])
    doctor_grades = data.doctors_grades or {}
    doctors = [
        Doctor(id=name, name=name, grade=doctor_grades.get(name) if graded else None)
        for name in names
    ]

    coverage: dict[dt.date, int] = {}
    if data.same_num_doctors != "Y" and data.num_doctors_per_night:
        for key, value in data.num_doctors_per_night.items():
            coverage[dt.date.fromisoformat(key[:10])] = int(value)

    unavailable = {
        name: _dates(raw) for name, raw in (data.doctor_not_present or {}).items()
    }

    req = RotaRequest(
        doctors=doctors,
        start=start,
        end=end,
        coverage=coverage,
        default_coverage=int(data.num_doctors or 0) if data.same_num_doctors == "Y" else 0,
        graded=graded,
        grades=grades,
        holidays=_dates(data.holiday_days),
        weights=dict(DEFAULT_WEIGHTS),
        unavailable=unavailable,
        min_rest_nights=1,
        time_limit=settings.solver_time_limit,
        workers=settings.solver_workers,
    )

    result = solve(req)
    if not result.feasible:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            " ".join(result.diagnostics) or "No rota satisfies these rules.",
        )

    nights = result.nights()
    per_doctor = result.metrics["per_doctor"]

    if graded:
        # Timestamp keys and per-grade nesting, exactly as before.
        schedule_out: dict = {
            f"{day.isoformat()}T00:00:00": {
                name: req.points_for(day) for name in sorted(nights.get(day, []))
            }
            for day in req.days
            if nights.get(day)
        }
        points: dict = {g: {} for g in grades}
        num_shifts: dict = {g: {} for g in grades}
        num_weekend: dict = {g: {} for g in grades}
        for name, stats in per_doctor.items():
            grade = stats["grade"] or (grades[0] if grades else "")
            if grade not in points:
                points[grade], num_shifts[grade], num_weekend[grade] = {}, {}, {}
            if stats["shifts"]:
                points[grade][name] = stats["points"]
                num_shifts[grade][name] = stats["shifts"]
            if stats["weekend_shifts"]:
                num_weekend[grade][name] = stats["weekend_shifts"]
    else:
        schedule_out = {
            day.isoformat(): [[name, req.points_for(day)] for name in sorted(nights.get(day, []))]
            for day in req.days
            if nights.get(day)
        }
        points = {n: s["points"] for n, s in per_doctor.items()}
        num_shifts = {n: s["shifts"] for n, s in per_doctor.items() if s["shifts"]}
        num_weekend = {n: s["weekend_shifts"] for n, s in per_doctor.items() if s["weekend_shifts"]}

    return {
        "schedule": schedule_out,
        "points": points,
        "num_shifts": num_shifts,
        "num_weekend_shifts": num_weekend,
        "schedule_name": "Schedule " + str(uuid.uuid4()),
        # Lower is fairer, as before. Now it is the solver's objective.
        "score": round(result.metrics["points_spread"] + result.metrics["weekend_spread"], 3),
        "solver": {
            "status": result.status,
            "seconds": round(result.solve_seconds, 3),
            "coverage": result.metrics["coverage"],
            "balance": result.metrics["balance"],
            "shortfalls": [
                {"date": s.date.isoformat(), "grade": s.grade,
                 "required": s.required, "assigned": s.assigned, "reason": s.reason}
                for s in result.shortfalls
            ],
        },
    }
