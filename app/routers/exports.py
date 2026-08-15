"""PDF and CSV export.

PDFs are rendered server-side with WeasyPrint so every coordinator gets the
same output regardless of browser, in three layouts:

  vertical    one row per night, A4 portrait — the diary
  horizontal  doctors as columns, A4 landscape — the wall chart
  calendar    month grid, A4 landscape — the noticeboard
"""

from __future__ import annotations

import calendar
import datetime as dt
import io
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response, StreamingResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import RequireRole
from app.i18n import Translator, normalise
from app.models import Department, Membership, Role, Schedule
from app.scheduling import service
from app.scheduling.domain import weight_for

router = APIRouter(tags=["exports"])

TEMPLATES = Environment(
    loader=FileSystemLoader(
        __file__.rsplit("/", 2)[0] + "/templates"
    ),
    autoescape=select_autoescape(["html"]),
)

LAYOUTS = {
    "vertical": ("pdf/vertical.html", "A4 portrait"),
    "horizontal": ("pdf/horizontal.html", "A4 landscape"),
    "calendar": ("pdf/calendar.html", "A4 landscape"),
}

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _context(db: Session, schedule: Schedule, *, focus_doctor: uuid.UUID | None = None,
             lang: str = "en") -> dict:
    payload = service.schedule_out(db, schedule)
    department = db.get(Department, schedule.department_id)
    config = schedule.config or {}
    holidays = {dt.date.fromisoformat(d) for d in config.get("holidays", [])}
    weights = config.get("weights") or {}

    assignments = payload.assignments
    focus_name = None
    if focus_doctor:
        focus_name = next(
            (a.doctor_name for a in assignments if a.doctor_id == focus_doctor), None
        )
        assignments = [a for a in assignments if a.doctor_id == focus_doctor]

    by_date: dict[dt.date, list] = {}
    for row in assignments:
        by_date.setdefault(row.date, []).append(row)

    nights = []
    day = schedule.start_date
    while day <= schedule.end_date:
        on_call = sorted(by_date.get(day, []), key=lambda a: (a.grade or "", a.doctor_name))
        nights.append({
            "date": day,
            "weekend": day.weekday() >= 5,
            "holiday": day in holidays,
            "weight": f"{weight_for(day, holidays, weights):g}",
            "doctors": on_call,
            "doctor_ids": {a.doctor_id for a in on_call},
        })
        day += dt.timedelta(days=1)

    per_doctor = sorted(
        (
            {
                "id": uuid.UUID(doctor_id),
                "name": stats["name"],
                "grade": stats["grade"],
                "shifts": stats["shifts"],
                "points": stats["points"],
                "weekend_shifts": stats["weekend_shifts"],
                "holiday_shifts": stats["holiday_shifts"],
            }
            for doctor_id, stats in (payload.metrics.get("per_doctor") or {}).items()
        ),
        key=lambda d: d["name"],
    )
    if focus_doctor:
        per_doctor = [d for d in per_doctor if d["id"] == focus_doctor]

    tr = Translator(lang)

    # Weeks starting Monday, padded so every row has seven cells.
    months = []
    for (year, month), group in _by_month(nights):
        first = dt.date(year, month, 1)
        lead = first.weekday()
        cells = [None] * lead + group
        cells += [None] * (-len(cells) % 7)
        months.append({
            "label": tr.month_year(year, month),
            "weeks": [cells[i:i + 7] for i in range(0, len(cells), 7)],
        })

    return {
        "schedule": payload,
        "department": department,
        "nights": nights,
        "months": months,
        "assignments": assignments,
        "doctors": per_doctor,
        "per_doctor": per_doctor,
        "metrics": payload.metrics or {},
        "shortfalls": [s.model_dump() for s in payload.shortfalls],
        "graded": bool(config.get("graded")),
        "weekday_names": tr.weekday_headers,
        "t": tr,
        "tr": tr,
        "lang": tr.lang,
        "dir": tr.dir,
        "generated_at": dt.datetime.now(),
        "focus_doctor": focus_name,
        "show_summary": True,
    }


def _by_month(nights: list[dict]):
    grouped: dict[tuple[int, int], list] = {}
    for night in nights:
        grouped.setdefault((night["date"].year, night["date"].month), []).append(night)
    return sorted(grouped.items())


def render_pdf(db: Session, schedule: Schedule, layout: str,
               focus_doctor: uuid.UUID | None = None, lang: str = "en") -> bytes:
    from weasyprint import HTML  # imported lazily: it pulls in Pango and Cairo

    template_name, page_size = LAYOUTS[layout]
    context = _context(db, schedule, focus_doctor=focus_doctor, lang=lang)
    context["page_size"] = page_size
    html = TEMPLATES.get_template(template_name).render(**context)
    return HTML(string=html).write_pdf()


def _disposition(schedule: Schedule, layout: str, suffix: str, inline: bool = False) -> str:
    """Build a Content-Disposition that survives a non-Latin schedule name.

    HTTP headers are latin-1, and `str.isalnum()` is true for Arabic and
    accented letters — so a name like "جدول" sailed past a naive filter and
    made the header un-encodable. The plain `filename` is now ASCII-only,
    with RFC 5987 `filename*` carrying the real name for clients that
    understand it.
    """
    stem = f"{schedule.name}-{layout}".lower()
    ascii_safe = "".join(
        c if (c.isascii() and c.isalnum()) or c in "-_" else "-" for c in stem
    ).strip("-")
    while "--" in ascii_safe:
        ascii_safe = ascii_safe.replace("--", "-")
    ascii_safe = ascii_safe or "rota"

    full = quote(f"{schedule.name}-{layout}.{suffix}", safe="")
    kind = "inline" if inline else "attachment"
    return f"{kind}; filename=\"{ascii_safe}.{suffix}\"; filename*=UTF-8\'\'{full}"


@router.get(
    "/api/departments/{department_id}/schedules/{schedule_id}/pdf",
    response_class=Response,
)
def schedule_pdf(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    layout: str = Query("vertical", pattern="^(vertical|horizontal|calendar)$"),
    doctor_id: uuid.UUID | None = None,
    lang: str = Query("en", pattern="^(en|fr|ar)$"),
    membership: Membership = Depends(RequireRole(Role.member)),
    db: Session = Depends(get_db),
):
    schedule = db.get(Schedule, schedule_id)
    if schedule is None or schedule.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found.")

    pdf = render_pdf(db, schedule, layout, doctor_id, lang)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": _disposition(schedule, layout, "pdf")},
    )


@router.get("/api/shared/{token}/pdf", response_class=Response, tags=["sharing"])
def shared_pdf(
    token: str,
    layout: str = Query("vertical", pattern="^(vertical|horizontal|calendar)$"),
    lang: str = Query("en", pattern="^(en|fr|ar)$"),
    db: Session = Depends(get_db),
):
    """A shared link can print the rota too, scoped the same way it reads it."""
    from app.routers.share import resolve_share

    link, schedule = resolve_share(token, db)
    pdf = render_pdf(db, schedule, layout, link.doctor_id, lang)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": _disposition(schedule, layout, "pdf", inline=True)},
    )


@router.get("/api/departments/{department_id}/schedules/{schedule_id}/csv")
def schedule_csv(
    department_id: uuid.UUID,
    schedule_id: uuid.UUID,
    membership: Membership = Depends(RequireRole(Role.member)),
    db: Session = Depends(get_db),
):
    import csv

    schedule = db.get(Schedule, schedule_id)
    if schedule is None or schedule.department_id != department_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Schedule not found.")

    context = _context(db, schedule)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Date", "Weekday", "Weight", "On call", "Grades", "Count"])
    for night in context["nights"]:
        writer.writerow([
            night["date"].isoformat(),
            night["date"].strftime("%a"),
            night["weight"],
            "; ".join(d.doctor_name for d in night["doctors"]),
            "; ".join(d.grade or "" for d in night["doctors"]),
            len(night["doctors"]),
        ])
    buffer.seek(0)

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": _disposition(schedule, "rota", "csv")},
    )
