"""Reading back the edit history.

Every hand edit is already recorded, as training signal for the preference
model. The same rows answer a different question — who changed what, and when
— so this turns them into something a coordinator can read.

Names are resolved at read time rather than stored in the event, so a doctor
who is renamed reads correctly in the history too. A doctor who has since been
deleted leaves a row that says so instead of a bare id.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Doctor, EditEvent, Schedule, User
from app.schemas import HistoryOut


def _day(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return f"{dt.date.fromisoformat(raw):%a %d %b}"
    except (ValueError, TypeError):
        return str(raw)


def _summary(event: EditEvent, names: dict[str, str], actor: str) -> str:
    payload = event.payload or {}
    when = _day(payload.get("date"))

    def who(key: str) -> str:
        value = payload.get(key)
        return names.get(str(value), "a doctor who has since left") if value else "someone"

    if event.kind == "assign":
        return f"{actor} put {who('doctor_id')} on call on {when}"
    if event.kind == "unassign":
        return f"{actor} took {who('doctor_id')} off {when}"
    if event.kind == "swap":
        return f"{actor} moved {when} from {who('doctor_out')} to {who('doctor_in')}"
    if event.kind == "retune":
        kept = "keeping pinned nights" if payload.get("kept_locked") else "ignoring pins"
        close = ", staying close to the previous rota" if payload.get("stay_close") else ""
        return f"{actor} re-tuned the rota, {kept}{close}"
    return f"{actor} made a {event.kind} change"


def describe(
    db: Session,
    *,
    department_id: uuid.UUID,
    schedule_id: uuid.UUID | None = None,
    limit: int = 200,
) -> list[HistoryOut]:
    """The edit history, newest first, in plain sentences."""
    stmt = select(EditEvent).where(EditEvent.department_id == department_id)
    if schedule_id is not None:
        stmt = stmt.where(EditEvent.schedule_id == schedule_id)
    events = db.scalars(
        stmt.order_by(EditEvent.created_at.desc()).limit(max(1, min(limit, 500)))
    ).all()
    if not events:
        return []

    names = {
        str(d.id): d.name
        for d in db.scalars(select(Doctor).where(Doctor.department_id == department_id)).all()
    }
    actor_ids = {e.actor_id for e in events if e.actor_id}
    actors = (
        {u.id: u.name for u in db.scalars(select(User).where(User.id.in_(actor_ids))).all()}
        if actor_ids
        else {}
    )
    schedule_ids = {e.schedule_id for e in events}
    schedules = {
        s.id: s.name
        for s in db.scalars(select(Schedule).where(Schedule.id.in_(schedule_ids))).all()
    }

    return [
        HistoryOut(
            id=event.id,
            schedule_id=event.schedule_id,
            schedule_name=schedules.get(event.schedule_id),
            kind=event.kind,
            actor=actors.get(event.actor_id),
            summary=_summary(event, names, actors.get(event.actor_id) or "Someone"),
            payload=event.payload or {},
            created_at=event.created_at,
        )
        for event in events
    ]
