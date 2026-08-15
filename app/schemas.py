"""Request and response bodies."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import RequestStatus, Role, ScheduleStatus
from app.scheduling.domain import CARRY_WINDOW_DAYS


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ───────────────────────────── auth ─────────────────────────────


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    department_name: str | None = Field(default=None, max_length=160)
    locale: str | None = Field(default=None, max_length=8)


class LocaleIn(BaseModel):
    locale: str = Field(min_length=2, max_length=8)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class PasswordChangeIn(BaseModel):
    current_password: str
    new_password: str


class PasswordResetRequestIn(BaseModel):
    email: EmailStr


class PasswordResetIn(BaseModel):
    token: str
    new_password: str


class UserOut(ORMModel):
    id: uuid.UUID
    email: EmailStr
    name: str
    is_verified: bool = False
    locale: str = "en"
    created_at: dt.datetime


class MembershipOut(ORMModel):
    department_id: uuid.UUID
    role: Role


class SessionOut(BaseModel):
    user: UserOut
    departments: list["DepartmentOut"] = []


# ───────────────────────── departments & roster ─────────────────────────


class DepartmentIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    hospital: str | None = Field(default=None, max_length=160)
    timezone: str = "UTC"
    settings: dict = Field(default_factory=dict)


class DepartmentOut(ORMModel):
    id: uuid.UUID
    name: str
    hospital: str | None = None
    timezone: str
    settings: dict = {}
    role: Role | None = None


class InviteIn(BaseModel):
    email: EmailStr
    role: Role = Role.member
    # Invite them *as* a roster entry, so accepting lands them on their shifts.
    doctor_id: uuid.UUID | None = None


class InviteOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    role: Role
    expires_at: dt.datetime
    # Returned once, at creation, so it can be sent on. Never stored in clear.
    invite_url: str | None = None


class DoctorIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    grade: str | None = Field(default=None, max_length=80)
    is_active: bool = True


class DoctorOut(ORMModel):
    id: uuid.UUID
    name: str
    grade: str | None = None
    is_active: bool
    leave: list[dt.date] = []
    # Who, if anyone, signs in as this person.
    user_id: uuid.UUID | None = None
    user_name: str | None = None
    has_feed: bool = False


class LeaveIn(BaseModel):
    dates: list[dt.date]
    reason: str | None = None


class LinkDoctorIn(BaseModel):
    """Attach a roster entry to an account that is already in the department."""

    user_id: uuid.UUID


class ImportRow(BaseModel):
    line: int
    name: str | None = None
    status: str          # created | updated | skipped | error
    detail: str | None = None


class ImportOut(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    rows: list[ImportRow] = []


class FeedOut(BaseModel):
    doctor_id: uuid.UUID
    doctor_name: str
    created_at: dt.datetime | None = None
    last_read_at: dt.datetime | None = None
    reads: int = 0
    # Returned once, at creation. Only the hash is ever stored.
    url: str | None = None


# ───────────────────────────── schedules ─────────────────────────────


class GenerateIn(BaseModel):
    """A rota request. Doctor ids come from the department's roster."""

    name: str | None = None
    start_date: dt.date
    end_date: dt.date

    coverage: int = Field(default=2, ge=0, le=50)
    coverage_by_date: dict[dt.date, int] = Field(default_factory=dict)

    graded: bool = False
    grades: list[str] = Field(default_factory=list)

    holidays: list[dt.date] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)

    min_rest_nights: int = Field(default=1, ge=0, le=14)
    # A minimum gap alone still allows every-other-night runs, so density is
    # capped over a rolling window too.
    max_shifts_per_window: int = Field(default=2, ge=1, le=14)
    spread_window_nights: int = Field(default=7, ge=0, le=28)
    # How far back to carry each doctor's balance, so fairness accumulates
    # across months instead of resetting. 0 scores this period alone.
    carry_forward_days: int = Field(default=CARRY_WINDOW_DAYS, ge=0, le=730)
    doctor_ids: list[uuid.UUID] | None = None
    use_preferences: bool = True
    time_limit: float | None = Field(default=None, gt=0, le=120)


class AssignmentOut(BaseModel):
    doctor_id: uuid.UUID
    doctor_name: str
    grade: str | None = None
    date: dt.date
    points: float
    locked: bool = False
    source: str = "solver"


class ShortfallOut(BaseModel):
    date: dt.date
    grade: str | None = None
    required: int
    assigned: int
    reason: str


class ScheduleOut(ORMModel):
    id: uuid.UUID
    department_id: uuid.UUID
    name: str
    start_date: dt.date
    end_date: dt.date
    status: ScheduleStatus
    config: dict = {}
    metrics: dict = {}
    solver_status: str | None = None
    solve_seconds: float | None = None
    created_at: dt.datetime
    updated_at: dt.datetime
    assignments: list[AssignmentOut] = []
    shortfalls: list[ShortfallOut] = []
    diagnostics: list[str] = []


class ScheduleSummary(ORMModel):
    id: uuid.UUID
    name: str
    start_date: dt.date
    end_date: dt.date
    status: ScheduleStatus
    metrics: dict = {}
    updated_at: dt.datetime


class AssignIn(BaseModel):
    doctor_id: uuid.UUID
    date: dt.date
    lock: bool = True


class UnassignIn(BaseModel):
    doctor_id: uuid.UUID
    date: dt.date


class SwapIn(BaseModel):
    date: dt.date
    doctor_out: uuid.UUID
    doctor_in: uuid.UUID
    lock: bool = True


class LockIn(BaseModel):
    doctor_id: uuid.UUID
    date: dt.date
    locked: bool


class RetuneIn(BaseModel):
    """Re-solve, keeping locked assignments and staying close to the current rota."""

    keep_locked: bool = True
    stay_close: bool = True
    time_limit: float | None = Field(default=None, gt=0, le=120)


class ValidationOut(BaseModel):
    ok: bool
    errors: list[str] = []
    warnings: list[str] = []


# ───────────────────────────── sharing ─────────────────────────────


# ─────────────────── doctor self-service and audit ───────────────────


class TimeOffIn(BaseModel):
    doctor_id: uuid.UUID | None = None   # only needed when one login covers several rosters
    start_date: dt.date
    end_date: dt.date
    reason: str | None = Field(default=None, max_length=200)


class TimeOffOut(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    department_name: str | None = None
    doctor_id: uuid.UUID
    doctor_name: str
    start_date: dt.date
    end_date: dt.date
    nights: int
    reason: str | None = None
    status: RequestStatus
    decided_at: dt.datetime | None = None
    decision_note: str | None = None
    created_at: dt.datetime


class SwapProposeIn(BaseModel):
    schedule_id: uuid.UUID
    date: dt.date
    to_doctor_id: uuid.UUID
    from_doctor_id: uuid.UUID | None = None
    message: str | None = Field(default=None, max_length=400)


class SwapOut(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    schedule_id: uuid.UUID
    schedule_name: str | None = None
    date: dt.date
    from_doctor_id: uuid.UUID
    from_doctor_name: str
    to_doctor_id: uuid.UUID
    to_doctor_name: str
    message: str | None = None
    status: RequestStatus
    decided_at: dt.datetime | None = None
    decision_note: str | None = None
    created_at: dt.datetime


class DecisionIn(BaseModel):
    approve: bool
    note: str | None = Field(default=None, max_length=400)


class InboxOut(BaseModel):
    """Everything waiting on a coordinator, in one call."""

    time_off: list[TimeOffOut] = []
    swaps: list[SwapOut] = []


class MyShift(BaseModel):
    date: dt.date
    points: float
    department_id: uuid.UUID
    department_name: str
    schedule_id: uuid.UUID
    schedule_name: str
    status: ScheduleStatus
    doctor_id: uuid.UUID
    # Who else is on that night, so a swap can be aimed at someone.
    alongside: list[str] = []


class MyProfile(BaseModel):
    user: UserOut
    doctors: list[DoctorOut] = []
    departments: list[DepartmentOut] = []
    shifts: list[MyShift] = []


class HistoryOut(BaseModel):
    id: uuid.UUID
    schedule_id: uuid.UUID
    schedule_name: str | None = None
    kind: str
    actor: str | None = None
    summary: str
    payload: dict = {}
    created_at: dt.datetime


class ShareIn(BaseModel):
    label: str | None = Field(default=None, max_length=120)
    doctor_id: uuid.UUID | None = None
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class ShareOut(ORMModel):
    id: uuid.UUID
    label: str | None = None
    doctor_id: uuid.UUID | None = None
    expires_at: dt.datetime | None = None
    revoked_at: dt.datetime | None = None
    views: int = 0
    created_at: dt.datetime
    url: str | None = None


SessionOut.model_rebuild()
