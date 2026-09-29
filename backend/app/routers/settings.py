"""Dashboard-editable settings."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas import SourceInfo
from app.settings_store import UserSettings, get_settings, save_settings
from app.sources import describe_sources

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("", response_model=UserSettings)
def read_settings(db: Session = Depends(get_db)) -> UserSettings:
    return get_settings(db)


@router.put("", response_model=UserSettings)
def write_settings(payload: UserSettings, db: Session = Depends(get_db)) -> UserSettings:
    previous = get_settings(db)
    saved = save_settings(db, payload)
    # A new pass mark should re-sort the jobs already scored, not only future ones.
    if (previous.min_score, previous.auto_reject_below_min_score) != (
        saved.min_score,
        saved.auto_reject_below_min_score,
    ):
        from app.pipeline.run import reapply_threshold

        reapply_threshold(db, saved)
    # Re-arm the timer so a changed run time takes effect without a restart.
    from app.scheduler import reschedule

    reschedule(saved)
    return saved


@router.get("/sources", response_model=list[SourceInfo])
def read_sources(db: Session = Depends(get_db)) -> list[SourceInfo]:
    return [SourceInfo(**info) for info in describe_sources(get_settings(db))]
