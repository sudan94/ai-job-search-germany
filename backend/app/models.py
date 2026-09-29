"""ORM models.

Job / JobAnalysis / Application are one-to-one: a posting, what the pipeline
decided about it, and what I did about it.  They are kept separate so a failed
stage never destroys the work of an earlier one - the Job row survives even if
scoring blows up.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus:
    NEW = "new"
    INTERESTED = "interested"
    APPLIED = "applied"
    #: Dropped by a pipeline filter: German required, below the similarity
    #: floor, or scored under the minimum.  Kept so the filters can be audited.
    SYSTEM_REJECTED = "system_rejected"
    #: Rejected by the company after I applied.
    REJECTED = "rejected"
    IGNORED = "ignored"

    ALL = (NEW, APPLIED, SYSTEM_REJECTED, REJECTED, INTERESTED, IGNORED)
    #: statuses that mean "I have made a decision" - never re-surface or re-score
    CLOSED = (APPLIED, REJECTED, IGNORED)
    #: statuses the pipeline may move between on its own; anything else is mine
    AUTOMATIC = (NEW, SYSTEM_REJECTED)


class AnalysisStage:
    PENDING = "pending"
    LANGUAGE_REJECTED = "language_rejected"
    BELOW_SIMILARITY = "below_similarity"
    SCORED = "scored"
    ERROR = "error"


class Job(Base):
    __tablename__ = "job"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512))
    company: Mapped[str] = mapped_column(String(255), default="")
    location: Mapped[str] = mapped_column(String(255), default="")
    remote: Mapped[bool] = mapped_column(Boolean, default=False)
    url: Mapped[str] = mapped_column(String(1024), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    posted_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_json: Mapped[str] = mapped_column(Text, default="{}")
    #: The run that first brought this posting in, so deleting a run can take
    #: its jobs with it.  Nullable: rows predating this column, and jobs stored
    #: outside a run, have no owner.  SET NULL is only a backstop - the delete
    #: endpoint removes the jobs itself.
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey("run_log.id", ondelete="SET NULL"), nullable=True, index=True
    )

    analysis: Mapped["JobAnalysis | None"] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )
    application: Mapped["Application | None"] = relationship(
        back_populates="job", uselist=False, cascade="all, delete-orphan"
    )

    @property
    def raw(self) -> dict[str, Any]:
        try:
            return json.loads(self.raw_json or "{}")
        except json.JSONDecodeError:
            return {}


class JobAnalysis(Base):
    __tablename__ = "job_analysis"
    __table_args__ = (UniqueConstraint("job_id", name="uq_job_analysis_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)

    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    #: JSON: {"matched": [...], "missing": [...], "verdict": "..."}
    score_reasons: Mapped[str] = mapped_column(Text, default="{}")

    working_language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    german_required: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    language_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    detected_language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    language_evidence: Mapped[str] = mapped_column(Text, default="")

    stage: Mapped[str] = mapped_column(String(32), default=AnalysisStage.PENDING, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: JSON list of floats - the JD embedding, kept so re-runs never re-embed.
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    job: Mapped[Job] = relationship(back_populates="analysis")

    @property
    def reasons(self) -> dict[str, Any]:
        try:
            return json.loads(self.score_reasons or "{}")
        except json.JSONDecodeError:
            return {}


class Application(Base):
    __tablename__ = "application"
    __table_args__ = (UniqueConstraint("job_id", name="uq_application_job"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.NEW, index=True)
    #: Legacy: cover letters were removed.  The columns stay because SQLite
    #: cannot drop them cheaply and `cover_letter_edited` is NOT NULL.
    cover_letter: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_letter_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cover_letter_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    applied_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    #: When to chase this application next; drives the "follow-ups due" list.
    follow_up_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    #: Recruiter or hiring manager: name, email, whatever I have.
    contact: Mapped[str] = mapped_column(Text, default="")
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    job: Mapped[Job] = relationship(back_populates="application")


class ApplicationEvent(Base):
    """One entry in a job's timeline: a status change or a note."""

    __tablename__ = "application_event"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    #: "user" for changes made in the dashboard, "system" for the pipeline
    actor: Mapped[str] = mapped_column(String(16), default="user")
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")


def change_status(
    application: Application, status: str, *, actor: str = "user", note: str = ""
) -> ApplicationEvent | None:
    """Set a status and return the timeline event for it, or None if unchanged.

    The caller adds the event to the session.  The pipeline and the API both go
    through here, so the timeline never misses a transition.
    """
    previous = application.status
    if previous == status:
        return None
    application.status = status
    application.status_changed_at = utcnow()
    if status == JobStatus.APPLIED and application.applied_date is None:
        application.applied_date = utcnow()
    elif status != JobStatus.REJECTED:
        # A company rejection follows an application, so it keeps the date;
        # any other move means the application did not happen.
        application.applied_date = None
    return ApplicationEvent(
        job_id=application.job_id,
        actor=actor,
        from_status=previous,
        to_status=status,
        note=note,
    )


class SchemaMigration(Base):
    """One row per data migration applied, so each runs exactly once."""

    __tablename__ = "schema_migration"

    name: Mapped[str] = mapped_column(String(128), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CVProfile(Base):
    __tablename__ = "cv_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str] = mapped_column(Text, default="")
    #: JSON list[str]
    skills: Mapped[str] = mapped_column(Text, default="[]")
    #: JSON list[str]
    role_targets: Mapped[str] = mapped_column(Text, default="[]")
    years_experience: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: JSON list[{"title","company","period","highlights"}]
    experience: Mapped[str] = mapped_column(Text, default="[]")
    languages: Mapped[str] = mapped_column(Text, default="[]")
    #: JSON list[{"degree","institution","period","details"}]
    education: Mapped[str] = mapped_column(Text, default="[]")
    #: JSON list[{"name","description","technologies"}]
    projects: Mapped[str] = mapped_column(Text, default="[]")
    #: JSON list[str]
    certifications: Mapped[str] = mapped_column(Text, default="[]")
    #: How many PDF pages the text came from, so a short read is visible.
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RunLog(Base):
    __tablename__ = "run_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    trigger: Mapped[str] = mapped_column(String(32), default="manual")

    fetched: Mapped[int] = mapped_column(Integer, default=0)
    new_jobs: Mapped[int] = mapped_column(Integer, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, default=0)
    language_dropped: Mapped[int] = mapped_column(Integer, default=0)
    similarity_dropped: Mapped[int] = mapped_column(Integer, default=0)
    scored: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    #: Legacy: cover letters were removed, so new runs leave this at 0.
    letters_written: Mapped[int] = mapped_column(Integer, default=0)

    #: JSON list[str]
    errors: Mapped[str] = mapped_column(Text, default="[]")
    #: JSON dict: per-source fetch counts, timings, notes
    details: Mapped[str] = mapped_column(Text, default="{}")

    @property
    def error_list(self) -> list[str]:
        try:
            return json.loads(self.errors or "[]")
        except json.JSONDecodeError:
            return []


class AppSetting(Base):
    """Single-row store for the dashboard-editable settings blob."""

    __tablename__ = "app_setting"

    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
