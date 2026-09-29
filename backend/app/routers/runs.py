"""Run history and manual triggers."""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db import get_db, session_scope
from app.models import Application, Job, JobAnalysis, JobStatus, RunLog
from app.pipeline.run import run_pipeline
from app.schemas import RunOut, StatsOut
from app.settings_store import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["runs"])

#: One run at a time - two concurrent runs would double-spend the LLM budget.
_run_lock = threading.Lock()


def run_in_background(trigger: str) -> bool:
    """Start a run unless one is already going.  Returns True if it started."""
    if not _run_lock.acquire(blocking=False):
        return False

    def _worker() -> None:
        try:
            with session_scope() as db:
                run_pipeline(db, trigger=trigger)
        except Exception:
            logger.exception("Background run crashed")
        finally:
            _run_lock.release()

    threading.Thread(target=_worker, name=f"run-{trigger}", daemon=True).start()
    return True


def run_is_active() -> bool:
    return _run_lock.locked()


@router.get("/runs", response_model=list[RunOut])
def list_runs(db: Session = Depends(get_db), limit: int = Query(default=30, ge=1, le=200)):
    runs = db.execute(select(RunLog).order_by(RunLog.started_at.desc()).limit(limit)).scalars().all()
    return [RunOut.from_model(run) for run in runs]


@router.post("/runs", status_code=202)
def trigger_run(db: Session = Depends(get_db)):
    if not run_in_background("manual"):
        raise HTTPException(status_code=409, detail="A run is already in progress.")
    return {"status": "started"}


@router.get("/runs/active")
def active_run():
    return {"active": run_is_active()}


def _delete_jobs_of(db: Session, run_ids: list[int]) -> int:
    """Delete the jobs these runs first brought in.

    The analysis and application rows go with them: both foreign keys are
    declared ON DELETE CASCADE and SQLite enforces it (`PRAGMA foreign_keys=ON`
    in `db.py`), so a bulk delete does not leave them behind.
    """
    if not run_ids:
        return 0
    result = db.execute(delete(Job).where(Job.run_id.in_(run_ids)))
    return result.rowcount or 0


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, db: Session = Depends(get_db)) -> dict:
    """Delete one run and every job it found."""
    run = db.get(RunLog, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status == "running":
        raise HTTPException(status_code=409, detail="That run is still going. Wait for it to finish.")

    deleted_jobs = _delete_jobs_of(db, [run_id])
    db.delete(run)
    db.commit()
    logger.info("Deleted run %s and %d job(s)", run_id, deleted_jobs)
    return {"deleted_runs": 1, "deleted_jobs": deleted_jobs}


@router.delete("/runs")
def delete_all_runs(
    db: Session = Depends(get_db),
    confirm: bool = Query(default=False, description="required: guards against an accidental call"),
) -> dict:
    """Clear the whole run history and every job those runs found."""
    if not confirm:
        raise HTTPException(status_code=400, detail="Pass ?confirm=true to clear the run history.")
    if run_is_active():
        raise HTTPException(status_code=409, detail="A run is in progress. Wait for it to finish.")

    run_ids = list(db.execute(select(RunLog.id)).scalars().all())
    deleted_jobs = _delete_jobs_of(db, run_ids)
    deleted_runs = db.execute(delete(RunLog)).rowcount or 0
    db.commit()
    logger.info("Cleared %d run(s) and %d job(s)", deleted_runs, deleted_jobs)
    return {"deleted_runs": deleted_runs, "deleted_jobs": deleted_jobs}


@router.get("/stats", response_model=StatsOut)
def stats(db: Session = Depends(get_db)) -> StatsOut:
    from app.cv.profile import get_active_profile
    from app.llm import llm
    from app.routers.jobs import end_of_today

    config = get_settings(db)

    by_status = {
        status: count
        for status, count in db.execute(
            select(Application.status, func.count()).group_by(Application.status)
        ).all()
    }
    for status in JobStatus.ALL:
        by_status.setdefault(status, 0)

    total = sum(by_status.values())
    passing = db.execute(
        select(func.count()).select_from(JobAnalysis).where(JobAnalysis.score >= config.min_score)
    ).scalar_one()
    follow_ups_due = db.execute(
        select(func.count())
        .select_from(Application)
        .where(
            Application.follow_up_date.isnot(None),
            Application.follow_up_date <= end_of_today(),
            Application.status.in_([JobStatus.APPLIED, JobStatus.INTERESTED]),
        )
    ).scalar_one()
    last_run = db.execute(
        select(RunLog).order_by(RunLog.started_at.desc()).limit(1)
    ).scalar_one_or_none()

    return StatsOut(
        total_jobs=total,
        by_status=by_status,
        passing=passing,
        follow_ups_due=follow_ups_due,
        last_run=RunOut.from_model(last_run) if last_run else None,
        llm_enabled=llm.available,
        has_cv=get_active_profile(db) is not None,
        min_score=config.min_score,
        matches_only_default=config.jobs_matches_only_default,
    )
