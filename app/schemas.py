"""Request and response bodies."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import Role, ScheduleStatus


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ───────────────────────────── auth ─────────────────────────────


class SignupIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=120)
    department_name: str | None = Field(default=None, max_length=160)


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


class LeaveIn(BaseModel):
    dates: list[dt.date]
    reason: str | None = None


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
