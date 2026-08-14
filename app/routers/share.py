"""Read-only share links.

A link carries a random token; only its hash is stored. Anyone holding the link
sees the rota without an account, and the coordinator can scope it to a single
doctor, give it an expiry, or revoke it outright.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import RequireRole
from app.models import Department, Doctor, Membership, Role, Schedule, ShareLink
from app.scheduling import service
from app.schemas import ShareIn, ShareOut
from app.security import expires_in, new_token, token_hash, utcnow

router = APIRouter(tags=["sharing"])

manage = APIRouter(
    prefix="/api/departments/{department_id}/schedules/{schedule_id}/shares",
    tags=["sharing"],
)


def _schedule(db: Session, department_id: uuid.UUID, schedule_id: uuid.UUID) -> Schedule:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None or schedule.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found.")
    return schedule


@manage.post("", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
def create_share(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    body: ShareIn,
    request: Request,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    schedule = _schedule(db, department_id, schedule_id)

    if body.doctor_id is not None:
        doctor = db.get(Doctor, body.doctor_id)
        if doctor is None or doctor.department_id != department_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Doctor not found.")

    token = new_token()
    link = ShareLink(
        schedule_id=schedule.id,
        token_hash=token_hash(token),
        label=body.label,
        doctor_id=body.doctor_id,
        expires_at=expires_in(body.expires_in_days * 86400) if body.expires_in_days else None,
        created_by=membership.user_id,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    out = ShareOut.model_validate(link)
    # The only time the token is ever visible.
    out.url = f"{str(request.base_url).rstrip('/')}/s/{token}"
    return out


@manage.get("", response_model=list[ShareOut])
def list_shares(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    schedule = _schedule(db, department_id, schedule_id)
    links = db.scalars(
        select(ShareLink)
        .where(ShareLink.schedule_id == schedule.id)
        .order_by(ShareLink.created_at.desc())
    ).all()
    return [ShareOut.model_validate(link) for link in links]


@manage.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    share_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.coordinator)),
    db: Session = Depends(get_db),
):
    schedule = _schedule(db, department_id, schedule_id)
    link = db.get(ShareLink, share_id)
    if link is None or link.schedule_id != schedule.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Share link not found.")
    link.revoked_at = utcnow()
    db.commit()


router.include_router(manage)


# ───────────────────────── public, no account ─────────────────────────


def resolve_share(token: str, db: Session) -> tuple[ShareLink, Schedule]:
    link = db.scalar(select(ShareLink).where(ShareLink.token_hash == token_hash(token)))
    if link is None or not link.is_live():
        # One message for missing, revoked and expired alike.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link is no longer available.")
    schedule = db.get(Schedule, link.schedule_id)
    if schedule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link is no longer available.")
    return link, schedule


@router.get("/api/shared/{token}", tags=["sharing"])
def read_shared(token: str, db: Session = Depends(get_db)) -> dict:
    link, schedule = resolve_share(token, db)
    link.views += 1
    db.commit()

    payload = service.schedule_out(db, schedule)
    department = db.get(Department, schedule.department_id)

    assignments = payload.assignments
    focus = None
    if link.doctor_id:
        focus = next((a.doctor_name for a in assignments if a.doctor_id == link.doctor_id), None)
        assignments = [a for a in assignments if a.doctor_id == link.doctor_id]

    return {
        "schedule": {
            "name": payload.name,
            "start_date": payload.start_date,
            "end_date": payload.end_date,
            "status": payload.status,
            "config": payload.config,
            "metrics": {} if link.doctor_id else payload.metrics,
            "assignments": assignments,
        },
        "department": {"name": department.name if department else "",
                       "hospital": department.hospital if department else None},
        "focus_doctor": focus,
        "read_only": True,
    }


@router.get("/api/shared/{token}/ics", tags=["sharing"])
def shared_ics(token: str, db: Session = Depends(get_db)):
    """Calendar subscription for a shared rota."""
    from fastapi.responses import Response

    link, schedule = resolve_share(token, db)
    payload = service.schedule_out(db, schedule)
    rows = [a for a in payload.assignments if not link.doctor_id or a.doctor_id == link.doctor_id]

    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Night Shift//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH", f"X-WR-CALNAME:{payload.name}",
    ]
    for i, row in enumerate(rows):
        lines += [
            "BEGIN:VEVENT",
            f"UID:{schedule.id}-{i}@night-shift",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{row.date.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(row.date + dt.timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:Night shift — {row.doctor_name}",
            f"DESCRIPTION:{row.points} points",
            "TRANSP:OPAQUE", "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")

    return Response(
        "\r\n".join(lines),
        media_type="text/calendar",
        headers={"Content-Disposition": f'attachment; filename="{schedule.id}.ics"'},
    )
