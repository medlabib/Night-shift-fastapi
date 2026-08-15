"""Database schema.

Ownership runs User → Membership → Department → {Doctor, Schedule}. Everything a
coordinator touches hangs off a Department, so authorisation is always a single
membership check.
"""

from __future__ import annotations

import datetime as dt
import enum
import uuid

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db import Base


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Role(str, enum.Enum):
    """Department roles, ordered least to most privileged."""

    member = "member"           # sees the rota, submits leave
    coordinator = "coordinator"  # builds and edits rotas
    owner = "owner"             # also manages members and the department


ROLE_RANK = {Role.member: 0, Role.coordinator: 1, Role.owner: 2}


class ScheduleStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    archived = "archived"


class AssignmentSource(str, enum.Enum):
    solver = "solver"
    manual = "manual"


class RequestStatus(str, enum.Enum):
    """Where a doctor-raised request has got to."""

    pending = "pending"
    approved = "approved"
    declined = "declined"
    withdrawn = "withdrawn"


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# ───────────────────────────── accounts ─────────────────────────────


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email_verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped on password change and logout-everywhere; stale sessions then fail.
    session_epoch: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Which language to write to them in. The interface remembers its own
    # choice per device; email has no device to ask, so it asks this.
    locale: Mapped[str] = mapped_column(String(8), default="en", nullable=False)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_verified(self) -> bool:
        return self.email_verified_at is not None


class Department(Base, TimestampMixin):
    __tablename__ = "departments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    hospital: Mapped[str | None] = mapped_column(String(160))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)
    # Point weights and any department-wide defaults, so a hospital that pays
    # Saturdays differently is not stuck with ours.
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )
    doctors: Mapped[list[Doctor]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )
    schedules: Mapped[list[Schedule]] = relationship(
        back_populates="department", cascade="all, delete-orphan"
    )


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "department_id", name="uq_membership"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"), default=Role.member, nullable=False)

    user: Mapped[User] = relationship(back_populates="memberships")
    department: Mapped[Department] = relationship(back_populates="memberships")


class Invitation(Base, TimestampMixin):
    __tablename__ = "invitations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"), default=Role.member, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    accepted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    # Invite someone *as* a roster entry: accepting claims that doctor, so
    # they land on their own shifts rather than an empty department.
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("doctors.id", ondelete="SET NULL"))


# ───────────────────────────── roster ─────────────────────────────


class Doctor(Base, TimestampMixin):
    __tablename__ = "doctors"
    __table_args__ = (UniqueConstraint("department_id", "name", name="uq_doctor_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    grade: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Optional link to a login, so a doctor can see their own shifts.
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    department: Mapped[Department] = relationship(back_populates="doctors")
    leave: Mapped[list[Leave]] = relationship(
        back_populates="doctor", cascade="all, delete-orphan"
    )


class Leave(Base, TimestampMixin):
    __tablename__ = "leave"
    __table_args__ = (UniqueConstraint("doctor_id", "date", name="uq_leave_day"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))

    doctor: Mapped[Doctor] = relationship(back_populates="leave")


# ─────────────────────── doctor-raised requests ───────────────────────
# Leave and swaps come *from* the doctor and are decided by a coordinator.
# Nothing here changes a rota on its own: approval is what writes to the
# roster or the schedule, through the same paths a coordinator edit uses.


class TimeOffRequest(Base, TimestampMixin):
    __tablename__ = "time_off_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, name="request_status"), default=RequestStatus.pending, nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(400))

    doctor: Mapped[Doctor] = relationship()

    @property
    def dates(self) -> list[dt.date]:
        span = (self.end_date - self.start_date).days
        return [self.start_date + dt.timedelta(days=i) for i in range(span + 1)]


class SwapRequest(Base, TimestampMixin):
    """One doctor asking a colleague to take a specific night."""

    __tablename__ = "swap_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), index=True, nullable=False
    )
    from_doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    to_doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    message: Mapped[str | None] = mapped_column(String(400))
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus, name="request_status"), default=RequestStatus.pending, nullable=False
    )
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(String(400))


class CalendarFeed(Base, TimestampMixin):
    """A doctor's standing ICS subscription, spanning every published rota.

    A share link is a snapshot of one schedule; this is the opposite — one URL
    whose contents change as new rotas are published, so a phone calendar stays
    current without anyone re-importing anything.
    """

    __tablename__ = "calendar_feeds"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    last_read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    reads: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    doctor: Mapped[Doctor] = relationship()

    def is_live(self) -> bool:
        return self.revoked_at is None


# ───────────────────────────── schedules ─────────────────────────────


class Schedule(Base, TimestampMixin):
    __tablename__ = "schedules"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    status: Mapped[ScheduleStatus] = mapped_column(
        Enum(ScheduleStatus, name="schedule_status"), default=ScheduleStatus.draft, nullable=False
    )
    # The full request that produced this rota: coverage, holidays, grades.
    # Kept verbatim so a schedule can always be re-solved or fine-tuned later.
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    solver_status: Mapped[str | None] = mapped_column(String(40))
    solve_seconds: Mapped[float | None] = mapped_column(Float)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    department: Mapped[Department] = relationship(back_populates="schedules")
    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="schedule", cascade="all, delete-orphan"
    )
    share_links: Mapped[list[ShareLink]] = relationship(
        back_populates="schedule", cascade="all, delete-orphan"
    )


class Assignment(Base, TimestampMixin):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("schedule_id", "doctor_id", "date", name="uq_assignment"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), index=True, nullable=False
    )
    doctor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"), index=True, nullable=False
    )
    date: Mapped[dt.date] = mapped_column(Date, index=True, nullable=False)
    points: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    # Locked assignments are pinned during a fine-tune re-solve.
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    source: Mapped[AssignmentSource] = mapped_column(
        Enum(AssignmentSource, name="assignment_source"),
        default=AssignmentSource.solver,
        nullable=False,
    )

    schedule: Mapped[Schedule] = relationship(back_populates="assignments")
    doctor: Mapped[Doctor] = relationship()


class ShareLink(Base, TimestampMixin):
    __tablename__ = "share_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # Only the hash is stored: a leaked database does not hand out live links.
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    label: Mapped[str | None] = mapped_column(String(120))
    # Restricts the view to a single doctor's shifts when set.
    doctor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"))
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    views: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    schedule: Mapped[Schedule] = relationship(back_populates="share_links")

    def is_live(self, now: dt.datetime | None = None) -> bool:
        now = now or dt.datetime.now(dt.timezone.utc)
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > now


# ───────────────────────── learning signals ─────────────────────────


class EditEvent(Base):
    """Every manual change, kept as training signal for the preference model."""

    __tablename__ = "edit_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    schedule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("schedules.id", ondelete="CASCADE"), index=True, nullable=False
    )
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(40), nullable=False)  # assign | unassign | swap
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PreferenceWeight(Base, TimestampMixin):
    """A learned soft preference, fed to the solver's objective.

    `subject` is the doctor the weight applies to (null = department-wide) and
    `feature` is what was learned, e.g. `dow:5` for Fridays or `partner:<uuid>`.
    Positive weight means "prefer", negative means "avoid".
    """

    __tablename__ = "preference_weights"
    __table_args__ = (
        UniqueConstraint("department_id", "subject_id", "feature", name="uq_preference"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    department_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("departments.id", ondelete="CASCADE"), index=True, nullable=False
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("doctors.id", ondelete="CASCADE"), index=True
    )
    feature: Mapped[str] = mapped_column(String(120), nullable=False)
    weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    samples: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class LoginAttempt(Base):
    """Throttling record for failed logins, keyed by email and client address."""

    __tablename__ = "login_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), index=True, nullable=False)
    ip: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
