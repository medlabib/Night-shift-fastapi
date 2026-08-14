"""Learning what a department actually wants, from what it does.

The solver guarantees the hard rules. This module supplies the soft ones, by
watching which nights coordinators move people off and which they move them
onto, then turning that into weights the solver treats as preferences.

The signal is deliberately simple and auditable — a coordinator can read back
exactly what was learned and why, and switch any of it off. Nothing here can
override a hard constraint: a learned weight only ever breaks a tie between
rotas that are already legal.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Assignment, Doctor, EditEvent, PreferenceWeight, Schedule

# How strongly one observation moves a weight. Small, so a single edit is a
# nudge rather than a rule, and a habit has to repeat before it sticks.
LEARNING_RATE = 0.34
MAX_WEIGHT = 3.0
# Below this many observations a signal is noise, not a preference.
MIN_SAMPLES = 2
DECAY = 0.9  # applied per training run, so stale habits fade

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _clamp(value: float) -> float:
    return max(-MAX_WEIGHT, min(MAX_WEIGHT, value))


def observe(
    events: list[EditEvent], assignments_by_schedule: dict[uuid.UUID, list[Assignment]]
) -> dict[tuple[str | None, str], list[float]]:
    """Turn raw edits into per-feature observations.

    Moving a doctor *off* a night is evidence they would rather not work it;
    moving them *onto* one is evidence they would. Both are recorded against
    the day of the week, which generalises, and against the specific date,
    which does not but matters for known events.
    """
    observations: dict[tuple[str | None, str], list[float]] = defaultdict(list)

    for event in events:
        payload = event.payload or {}
        raw_date = payload.get("date")
        if not raw_date:
            continue
        try:
            day = dt.date.fromisoformat(raw_date)
        except ValueError:
            continue

        if event.kind == "unassign":
            losers, gainers = [payload.get("doctor_id")], []
        elif event.kind == "assign":
            losers, gainers = [], [payload.get("doctor_id")]
        elif event.kind == "swap":
            losers, gainers = [payload.get("doctor_out")], [payload.get("doctor_in")]
        else:
            continue

        for doctor_id in filter(None, losers):
            observations[doctor_id, f"dow:{day.weekday()}"].append(-1.0)
            observations[doctor_id, f"date:{day.isoformat()}"].append(-1.0)
        for doctor_id in filter(None, gainers):
            observations[doctor_id, f"dow:{day.weekday()}"].append(1.0)
            observations[doctor_id, f"date:{day.isoformat()}"].append(1.0)

    return observations


def train(db: Session, department_id: uuid.UUID) -> list[PreferenceWeight]:
    """Refit this department's preference weights from its edit history."""
    events = db.scalars(
        select(EditEvent)
        .where(EditEvent.department_id == department_id)
        .order_by(EditEvent.created_at)
    ).all()

    schedule_ids = {e.schedule_id for e in events}
    assignments: dict[uuid.UUID, list[Assignment]] = {}
    if schedule_ids:
        rows = db.scalars(
            select(Assignment).where(Assignment.schedule_id.in_(schedule_ids))
        ).all()
        for row in rows:
            assignments.setdefault(row.schedule_id, []).append(row)

    observations = observe(events, assignments)

    existing = {
        (str(w.subject_id) if w.subject_id else None, w.feature): w
        for w in db.scalars(
            select(PreferenceWeight).where(PreferenceWeight.department_id == department_id)
        ).all()
    }
    # Everything decays each run; only what is still being observed recovers.
    for weight in existing.values():
        weight.weight = _clamp(weight.weight * DECAY)

    valid_doctors = {
        str(d.id)
        for d in db.scalars(
            select(Doctor).where(Doctor.department_id == department_id)
        ).all()
    }

    touched: list[PreferenceWeight] = []
    for (subject, feature), samples in observations.items():
        if subject not in valid_doctors:
            continue  # the doctor has since left the roster
        if len(samples) < MIN_SAMPLES:
            continue

        direction = sum(samples) / len(samples)
        record = existing.get((subject, feature))
        if record is None:
            record = PreferenceWeight(
                department_id=department_id,
                subject_id=uuid.UUID(subject),
                feature=feature,
                weight=0.0,
                samples=0,
            )
            db.add(record)
            existing[subject, feature] = record

        record.weight = _clamp(record.weight + LEARNING_RATE * direction * len(samples) ** 0.5)
        record.samples = len(samples)
        record.note = explain(record)
        touched.append(record)

    # Drop anything that has decayed into irrelevance.
    for key, record in list(existing.items()):
        if abs(record.weight) < 0.15 and record not in touched:
            db.delete(record)
            existing.pop(key, None)

    db.commit()
    return sorted(existing.values(), key=lambda w: -abs(w.weight))


def explain(weight: PreferenceWeight) -> str:
    """Say in plain words what a learned weight means."""
    verb = "prefers" if weight.weight > 0 else "avoids"
    feature = weight.feature

    if feature.startswith("dow:"):
        what = f"{WEEKDAYS[int(feature.split(':', 1)[1])]}s"
    elif feature.startswith("date:"):
        what = dt.date.fromisoformat(feature.split(":", 1)[1]).strftime("%d %b %Y")
    elif feature.startswith("partner:"):
        what = "working alongside a particular colleague"
    else:
        what = feature

    strength = "strongly " if abs(weight.weight) > 1.6 else ""
    return f"{strength}{verb} {what} — from {weight.samples} edit(s)"


def describe(db: Session, department_id: uuid.UUID) -> list[dict]:
    """The learned model, in a form a coordinator can read and audit."""
    names = {
        d.id: d.name
        for d in db.scalars(
            select(Doctor).where(Doctor.department_id == department_id)
        ).all()
    }
    weights = db.scalars(
        select(PreferenceWeight).where(PreferenceWeight.department_id == department_id)
    ).all()

    return sorted(
        (
            {
                "id": str(w.id),
                "doctor": names.get(w.subject_id, "the department"),
                "doctor_id": str(w.subject_id) if w.subject_id else None,
                "feature": w.feature,
                "weight": round(w.weight, 2),
                "samples": w.samples,
                "explanation": w.note or explain(w),
            }
            for w in weights
        ),
        key=lambda row: -abs(row["weight"]),
    )
