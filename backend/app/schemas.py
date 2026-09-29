"""API request/response shapes."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models import Application, ApplicationEvent, CVProfile, Job, JobAnalysis, RunLog


def _loads(value: str | None, default: Any) -> Any:
    try:
        return json.loads(value) if value else default
    except json.JSONDecodeError:
        return default


class AnalysisOut(BaseModel):
    similarity: float | None = None
    score: int | None = None
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    verdict: str = ""
    working_language: str | None = None
    german_required: bool | None = None
    language_confidence: float | None = None
    detected_language: str | None = None
    language_evidence: str = ""
    stage: str = "pending"
    error: str | None = None
    analyzed_at: datetime | None = None

    @classmethod
    def from_model(cls, analysis: JobAnalysis | None) -> "AnalysisOut | None":
        if analysis is None:
            return None
        reasons = _loads(analysis.score_reasons, {})
        return cls(
            similarity=analysis.similarity,
            score=analysis.score,
            matched=reasons.get("matched", []),
            missing=reasons.get("missing", []),
            verdict=reasons.get("verdict", ""),
            working_language=analysis.working_language,
            german_required=analysis.german_required,
            language_confidence=analysis.language_confidence,
            detected_language=analysis.detected_language,
            language_evidence=analysis.language_evidence,
            stage=analysis.stage,
            error=analysis.error,
            analyzed_at=analysis.analyzed_at,
        )


class ApplicationOut(BaseModel):
    status: str = "new"
    applied_date: datetime | None = None
    follow_up_date: datetime | None = None
    contact: str = ""
    notes: str = ""
    status_changed_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_model(cls, application: Application | None) -> "ApplicationOut":
        if application is None:
            return cls()
        return cls(
            status=application.status,
            applied_date=application.applied_date,
            follow_up_date=application.follow_up_date,
            contact=application.contact or "",
            notes=application.notes,
            status_changed_at=application.status_changed_at,
            updated_at=application.updated_at,
        )


class EventOut(BaseModel):
    id: int
    created_at: datetime
    actor: str
    from_status: str | None
    to_status: str | None
    note: str

    @classmethod
    def from_model(cls, event: ApplicationEvent) -> "EventOut":
        return cls(
            id=event.id,
            created_at=event.created_at,
            actor=event.actor,
            from_status=event.from_status,
            to_status=event.to_status,
            note=event.note,
        )


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    source: str
    #: The board behind an aggregated result (Indeed, StepStone...); empty otherwise.
    publisher: str = ""
    title: str
    company: str
    location: str
    remote: bool
    url: str
    posted_date: datetime | None
    first_seen: datetime
    analysis: AnalysisOut | None = None
    application: ApplicationOut = Field(default_factory=ApplicationOut)

    @classmethod
    def from_model(cls, job: Job) -> "JobOut":
        return cls(
            id=job.id,
            external_id=job.external_id,
            source=job.source,
            publisher=str(job.raw.get("publisher") or "") if job.source == "jsearch" else "",
            title=job.title,
            company=job.company,
            location=job.location,
            remote=job.remote,
            url=job.url,
            posted_date=job.posted_date,
            first_seen=job.first_seen,
            analysis=AnalysisOut.from_model(job.analysis),
            application=ApplicationOut.from_model(job.application),
        )


class JobDetailOut(JobOut):
    description: str = ""
    #: The job's timeline, newest first.
    events: list[EventOut] = Field(default_factory=list)

    @classmethod
    def from_model(cls, job: Job, events: list[ApplicationEvent] | None = None) -> "JobDetailOut":
        base = JobOut.from_model(job).model_dump()
        return cls(
            **base,
            description=job.description,
            events=[EventOut.from_model(event) for event in events or []],
        )


class JobListOut(BaseModel):
    total: int
    items: list[JobOut]
    limit: int
    offset: int


class TrackingUpdate(BaseModel):
    """Partial update of what I did about a job.

    Only fields actually sent are applied, so `follow_up_date: null` clears the
    date while leaving it out keeps it.
    """

    status: str | None = None
    notes: str | None = None
    contact: str | None = None
    applied_date: datetime | None = None
    follow_up_date: datetime | None = None
    #: Free-text entry for the timeline, e.g. "Phone screen with Anna".
    log: str | None = None


class RunOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    trigger: str
    fetched: int
    new_jobs: int
    duplicates: int
    language_dropped: int
    similarity_dropped: int
    scored: int
    passed: int
    errors: list[str] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)

    @classmethod
    def from_model(cls, run: RunLog) -> "RunOut":
        return cls(
            id=run.id,
            started_at=run.started_at,
            finished_at=run.finished_at,
            status=run.status,
            trigger=run.trigger,
            fetched=run.fetched,
            new_jobs=run.new_jobs,
            duplicates=run.duplicates,
            language_dropped=run.language_dropped,
            similarity_dropped=run.similarity_dropped,
            scored=run.scored,
            passed=run.passed,
            errors=_loads(run.errors, []),
            details=_loads(run.details, {}),
        )


class CVOut(BaseModel):
    id: int
    filename: str
    summary: str
    skills: list[str]
    role_targets: list[str]
    years_experience: float | None
    experience: list[dict]
    languages: list[str]
    education: list[dict] = Field(default_factory=list)
    projects: list[dict] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    page_count: int | None = None
    #: Length of the extracted text, so a short read is visible at a glance.
    text_chars: int = 0
    has_embedding: bool
    embedding_model: str | None
    updated_at: datetime
    #: Set on upload when a stage degraded (no key, model error, embedding
    #: failure).  The profile is still stored; the user needs to know it is thin.
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_model(cls, profile: CVProfile, warnings: list[str] | None = None) -> "CVOut":
        return cls(
            id=profile.id,
            filename=profile.filename,
            summary=profile.summary,
            skills=_loads(profile.skills, []),
            role_targets=_loads(profile.role_targets, []),
            years_experience=profile.years_experience,
            experience=_loads(profile.experience, []),
            languages=_loads(profile.languages, []),
            education=_loads(profile.education, []),
            projects=_loads(profile.projects, []),
            certifications=_loads(profile.certifications, []),
            page_count=profile.page_count,
            text_chars=len(profile.raw_text or ""),
            has_embedding=bool(profile.embedding),
            embedding_model=profile.embedding_model,
            updated_at=profile.updated_at,
            warnings=warnings or [],
        )


class CVTextIn(BaseModel):
    text: str = Field(min_length=100)
    filename: str = "pasted-cv.txt"


class StatsOut(BaseModel):
    total_jobs: int
    by_status: dict[str, int]
    passing: int
    #: Applied or interested jobs whose follow-up date is today or earlier.
    follow_ups_due: int = 0
    last_run: RunOut | None = None
    llm_enabled: bool
    has_cv: bool
    #: The current pass mark, so the jobs table can default to matches only.
    min_score: int = 0
    matches_only_default: bool = True


class SourceInfo(BaseModel):
    name: str
    label: str
    enabled: bool
    configured: bool
    requires_config: bool


class HealthOut(BaseModel):
    status: str = "ok"
    version: str
    llm_enabled: bool
    scheduler_running: bool
    next_run: datetime | None = None
