"""Shared vocabulary for rota building.

Deliberately free of SQLAlchemy and FastAPI so the solver can be exercised from
tests, notebooks or a script without touching a database.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

# Point weights. Holidays outrank the day of the week they fall on.
DEFAULT_WEIGHTS = {"weekday": 1.0, "saturday": 1.5, "sunday": 2.0, "holiday": 2.0}

# Points are scaled to integers for CP-SAT, which is exact only over integers.
SCALE = 10

# How far carried-forward history is allowed to tilt a new rota. Without a
# ceiling, one doctor returning from a long absence would absorb an entire
# month to "catch up" — technically fairer over the quarter, unliveable in
# September. Ten points is roughly a week of extra nights.
CARRY_CAP_POINTS = 10.0
CARRY_CAP_WEEKENDS = 3.0
# How far back to look when carrying balance forward, in days.
CARRY_WINDOW_DAYS = 90


def weight_for(day: dt.date, holidays: set[dt.date], weights: dict[str, float] | None = None) -> float:
    w = {**DEFAULT_WEIGHTS, **(weights or {})}
    if day in holidays:
        return float(w["holiday"])
    if day.weekday() == 5:
        return float(w["saturday"])
    if day.weekday() == 6:
        return float(w["sunday"])
    return float(w["weekday"])


def date_range(start: dt.date, end: dt.date) -> list[dt.date]:
    if end < start:
        return []
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


@dataclass(frozen=True)
class Doctor:
    id: str
    name: str
    grade: str | None = None


@dataclass
class RotaRequest:
    """Everything the solver needs to build one rota."""

    doctors: list[Doctor]
    start: dt.date
    end: dt.date

    # Nightly headcount. In a graded department this is *per grade*, matching
    # how a department staffs each tier independently.
    coverage: dict[dt.date, int] = field(default_factory=dict)
    default_coverage: int = 2

    graded: bool = False
    grades: list[str] = field(default_factory=list)
    # Optional per-date, per-grade override: {date: {grade: count}}
    grade_coverage: dict[dt.date, dict[str, int]] = field(default_factory=dict)

    holidays: set[dt.date] = field(default_factory=set)
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    # doctor id -> dates that doctor cannot work
    unavailable: dict[str, set[dt.date]] = field(default_factory=dict)

    # Nights of rest required between two shifts. 1 forbids back-to-back nights.
    min_rest_nights: int = 1
    # A minimum gap alone still permits working every other night for a
    # fortnight, so shift density is capped over a rolling window as well:
    # at most `max_shifts_per_window` shifts in any `spread_window_nights`.
    max_shifts_per_window: int = 2
    spread_window_nights: int = 7
    max_shifts: dict[str, int] = field(default_factory=dict)

    # Pinned assignments kept as-is during a fine-tune re-solve: {doctor_id: {dates}}
    locked: dict[str, set[dt.date]] = field(default_factory=dict)
    # Nights explicitly cleared by a coordinator: {doctor_id: {dates}}
    forbidden: dict[str, set[dt.date]] = field(default_factory=dict)

    # Previous rota to stay close to, when fine-tuning: {doctor_id: {dates}}
    anchor: dict[str, set[dt.date]] | None = None
    change_penalty: int = 0

    # Learned soft preferences: {(doctor_id | None, feature): weight}
    # Features: "dow:<0-6>", "date:<iso>", "partner:<doctor_id>".
    preferences: dict[tuple[str | None, str], float] = field(default_factory=dict)

    # ── balance carried in from earlier periods ──
    # Fairness measured only inside one rota resets every month, so whoever
    # draws the heaviest September can draw the heaviest October too. These
    # are what each doctor already worked in the look-back window; the solver
    # adds them to this period's totals and evens out the sum.
    prior_points: dict[str, float] = field(default_factory=dict)
    prior_weekends: dict[str, float] = field(default_factory=dict)
    # Doctors who were not on the roster for the whole window. They have no
    # comparable history, so they count as average rather than as having done
    # nothing — joining last week is not a reason to be handed a heavy month.
    prior_partial: set[str] = field(default_factory=set)
    carry_cap_points: float = CARRY_CAP_POINTS
    carry_cap_weekends: float = CARRY_CAP_WEEKENDS

    time_limit: float = 10.0
    workers: int = 8

    @property
    def days(self) -> list[dt.date]:
        return date_range(self.start, self.end)

    def required_on(self, day: dt.date) -> int:
        return int(self.coverage.get(day, self.default_coverage))

    def required_for(self, day: dt.date, grade: str) -> int:
        per_grade = self.grade_coverage.get(day)
        if per_grade and grade in per_grade:
            return int(per_grade[grade])
        return self.required_on(day)

    def points_for(self, day: dt.date) -> float:
        return weight_for(day, self.holidays, self.weights)

    def is_available(self, doctor_id: str, day: dt.date) -> bool:
        return day not in self.unavailable.get(doctor_id, set())

    def doctors_in(self, grade: str) -> list[Doctor]:
        return [d for d in self.doctors if d.grade == grade]

    @property
    def carries_forward(self) -> bool:
        return bool(self.prior_points or self.prior_weekends)

    def seats(self) -> int:
        """Total doctor-nights this request asks for."""
        if self.graded and self.grades:
            return sum(
                self.required_for(day, grade) for day in self.days for grade in self.grades
            )
        return sum(self.required_on(day) for day in self.days)


@dataclass
class Shortfall:
    date: dt.date
    grade: str | None
    required: int
    assigned: int
    reason: str


@dataclass
class RotaResult:
    """A solved rota plus everything needed to explain it."""

    assignments: dict[str, list[dt.date]]      # doctor id -> nights worked
    status: str                                 # OPTIMAL | FEASIBLE | RELAXED | INFEASIBLE
    solve_seconds: float
    objective: float | None = None
    shortfalls: list[Shortfall] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return self.status in {"OPTIMAL", "FEASIBLE", "RELAXED"}

    def nights(self) -> dict[dt.date, list[str]]:
        """Invert to date -> doctor ids."""
        out: dict[dt.date, list[str]] = {}
        for doctor_id, days in self.assignments.items():
            for day in days:
                out.setdefault(day, []).append(doctor_id)
        return out
