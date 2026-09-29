"""Job list, detail, and application tracking."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.llm import LLMUnavailable
from app.models import Application, ApplicationEvent, Job, JobAnalysis, JobStatus, change_status
from app.pipeline.run import rescore_job
from app.schemas import (
    ApplicationOut,
    EventOut,
    JobDetailOut,
    JobListOut,
    JobOut,
    TrackingUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])

SORTS = {
    "score": JobAnalysis.score,
    "similarity": JobAnalysis.similarity,
    "first_seen": Job.first_seen,
    "posted_date": Job.posted_date,
    "company": Job.company,
    "applied_date": Application.applied_date,
    "follow_up_date": Application.follow_up_date,
    "status_changed_at": Application.status_changed_at,
}


def end_of_today() -> datetime:
    """Follow-ups are due by date, so anything dated today counts."""
    now = datetime.now(timezone.utc)
    return now.replace(hour=23, minute=59, second=59, microsecond=0)


@router.get("", response_model=JobListOut)
def list_jobs(
    db: Session = Depends(get_db),
    status: list[str] | None = Query(default=None),
    source: list[str] | None = Query(default=None),
    min_score: int | None = Query(default=None, ge=0, le=100),
    remote_only: bool = False,
    english_only: bool = False,
    search: str | None = None,
    follow_up_due: bool = False,
    sort: str = Query(default="score"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> JobListOut:
    stmt = (
        select(Job)
        .outerjoin(JobAnalysis, JobAnalysis.job_id == Job.id)
        .outerjoin(Application, Application.job_id == Job.id)
        .options(selectinload(Job.analysis), selectinload(Job.application))
    )

    if status:
        stmt = stmt.where(Application.status.in_(status))
    if source:
        stmt = stmt.where(Job.source.in_(source))
    if min_score is not None:
        stmt = stmt.where(JobAnalysis.score >= min_score)
    if remote_only:
        stmt = stmt.where(Job.remote.is_(True))
    if english_only:
        stmt = stmt.where(or_(JobAnalysis.german_required.is_(False), JobAnalysis.german_required.is_(None)))
    if follow_up_due:
        stmt = stmt.where(
            Application.follow_up_date.isnot(None),
            Application.follow_up_date <= end_of_today(),
            Application.status.in_([JobStatus.APPLIED, JobStatus.INTERESTED]),
        )
    if search:
        needle = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(Job.title.ilike(needle), Job.company.ilike(needle), Job.description.ilike(needle))
        )

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()

    column = SORTS.get(sort, JobAnalysis.score)
    direction = column.desc() if order == "desc" else column.asc()
    stmt = stmt.order_by(direction.nulls_last(), Job.first_seen.desc()).limit(limit).offset(offset)

    jobs = db.execute(stmt).scalars().unique().all()
    return JobListOut(
        total=total,
        items=[JobOut.from_model(job) for job in jobs],
        limit=limit,
        offset=offset,
    )


def _get_job(db: Session, job_id: int) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _events(db: Session, job_id: int) -> list[ApplicationEvent]:
    return list(
        db.execute(
            select(ApplicationEvent)
            .where(ApplicationEvent.job_id == job_id)
            .order_by(ApplicationEvent.created_at.desc(), ApplicationEvent.id.desc())
        ).scalars()
    )


def _detail(db: Session, job: Job) -> JobDetailOut:
    return JobDetailOut.from_model(job, _events(db, job.id))


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: int, db: Session = Depends(get_db)) -> JobDetailOut:
    return _detail(db, _get_job(db, job_id))


@router.get("/{job_id}/events", response_model=list[EventOut])
def list_events(job_id: int, db: Session = Depends(get_db)) -> list[EventOut]:
    _get_job(db, job_id)
    return [EventOut.from_model(event) for event in _events(db, job_id)]


def _application(db: Session, job: Job) -> Application:
    application = db.execute(
        select(Application).where(Application.job_id == job.id)
    ).scalar_one_or_none()
    if application is None:
        application = Application(job_id=job.id, status=JobStatus.NEW)
        db.add(application)
        db.flush()
    return application


@router.patch("/{job_id}/status", response_model=ApplicationOut)
def update_tracking(
    job_id: int, payload: TrackingUpdate, db: Session = Depends(get_db)
) -> ApplicationOut:
    job = _get_job(db, job_id)
    application = _application(db, job)
    sent = payload.model_fields_set

    if payload.status is not None:
        if payload.status not in JobStatus.ALL:
            raise HTTPException(
                status_code=422, detail=f"status must be one of {', '.join(JobStatus.ALL)}"
            )
        event = change_status(application, payload.status, actor="user")
        if event is not None:
            db.add(event)

    if "applied_date" in sent:
        application.applied_date = payload.applied_date
    if "follow_up_date" in sent:
        application.follow_up_date = payload.follow_up_date
    if payload.notes is not None:
        application.notes = payload.notes
    if payload.contact is not None:
        application.contact = payload.contact.strip()
    if payload.log and payload.log.strip():
        db.add(ApplicationEvent(job_id=job.id, actor="user", note=payload.log.strip()))

    db.commit()
    db.refresh(application)
    return ApplicationOut.from_model(application)


@router.delete("/{job_id}/events/{event_id}", status_code=204, response_class=Response)
def delete_event(job_id: int, event_id: int, db: Session = Depends(get_db)) -> Response:
    event = db.get(ApplicationEvent, event_id)
    if event is None or event.job_id != job_id:
        raise HTTPException(status_code=404, detail="Event not found")
    db.delete(event)
    db.commit()
    return Response(status_code=204)


@router.post("/{job_id}/rescore", response_model=JobDetailOut)
def rescore(job_id: int, db: Session = Depends(get_db)) -> JobDetailOut:
    job = _get_job(db, job_id)
    try:
        rescore_job(db, job)
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Rescore failed")
        raise HTTPException(status_code=502, detail=f"Rescore failed: {exc}") from exc

    db.refresh(job)
    return _detail(db, job)


@router.delete("", status_code=200)
def delete_all_jobs(
    db: Session = Depends(get_db),
    confirm: bool = Query(default=False, description="required: guards against an accidental call"),
) -> dict:
    """Drop every stored posting, including ones no run owns.

    The run history survives - clearing it is a separate call on /api/runs.
    """
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass ?confirm=true to delete every job.")
    # Analysis and application rows follow via ON DELETE CASCADE.
    deleted = db.execute(delete(Job)).rowcount or 0
    db.commit()
    logger.info("Deleted all %d job(s)", deleted)
    return {"deleted_jobs": deleted}


@router.delete("/{job_id}", status_code=204, response_class=Response)
def delete_job(job_id: int, db: Session = Depends(get_db)) -> Response:
    job = _get_job(db, job_id)
    db.delete(job)
    db.commit()
    return Response(status_code=204)
