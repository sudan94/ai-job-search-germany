"""In-process daily timer, plus catch-up for missed runs.

A laptop that was asleep at 09:00 never fires the timer, so startup also asks
"did today's run happen?" and runs it if not.  On a machine that is off for days
this is the only thing that keeps the tool current; on an always-on host the
cron trigger does the work and catch-up is a no-op.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import settings
from app.db import session_scope
from app.models import RunLog
from app.settings_store import UserSettings, get_settings

logger = logging.getLogger(__name__)

JOB_ID = "daily-scan"
_scheduler: BackgroundScheduler | None = None


def tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.timezone)
    except Exception:
        logger.warning("Unknown timezone %s, falling back to UTC", settings.timezone)
        return ZoneInfo("UTC")


def _daily_job() -> None:
    from app.routers.runs import run_in_background

    if not run_in_background("scheduled"):
        logger.warning("Scheduled run skipped: a run is already in progress.")


def start(config: UserSettings | None = None) -> BackgroundScheduler | None:
    """Start the timer if it is enabled both in env and in user settings."""
    global _scheduler

    if not settings.enable_scheduler:
        logger.info("Scheduler disabled by ENABLE_SCHEDULER; drive runs from cron instead.")
        return None

    if config is None:
        with session_scope() as db:
            config = get_settings(db)

    if not config.scheduler_enabled:
        logger.info("Scheduler disabled in user settings.")
        return None

    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=tz())
        _scheduler.start()

    reschedule(config)
    return _scheduler


def reschedule(config: UserSettings) -> None:
    if _scheduler is None:
        return

    existing = _scheduler.get_job(JOB_ID)
    if not config.scheduler_enabled:
        if existing:
            _scheduler.remove_job(JOB_ID)
            logger.info("Daily scan unscheduled.")
        return

    hour, minute = config.run_hour_minute
    trigger = CronTrigger(hour=hour, minute=minute, timezone=tz())
    if existing:
        _scheduler.reschedule_job(JOB_ID, trigger=trigger)
    else:
        _scheduler.add_job(
            _daily_job,
            trigger=trigger,
            id=JOB_ID,
            name="Daily job scan",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
    logger.info("Daily scan scheduled for %02d:%02d %s", hour, minute, settings.timezone)


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def is_running() -> bool:
    return _scheduler is not None and _scheduler.running


def next_run_time() -> datetime | None:
    if _scheduler is None:
        return None
    job = _scheduler.get_job(JOB_ID)
    return job.next_run_time if job else None


def needs_catch_up(config: UserSettings) -> bool:
    """True when today's scheduled slot has passed and no run happened since."""
    zone = tz()
    now = datetime.now(zone)
    hour, minute = config.run_hour_minute
    slot = datetime.combine(now.date(), time(hour, minute), tzinfo=zone)
    if now < slot:
        # Before today's slot: was yesterday's missed too?
        slot -= timedelta(days=1)

    with session_scope() as db:
        last = db.execute(select(RunLog).order_by(RunLog.started_at.desc()).limit(1)).scalar_one_or_none()
        if last is None:
            return True
        started = last.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=ZoneInfo("UTC"))
        return started.astimezone(zone) < slot


def catch_up_if_needed(config: UserSettings) -> bool:
    if not settings.catch_up_on_startup or not config.scheduler_enabled:
        return False
    if not needs_catch_up(config):
        return False

    from app.routers.runs import run_in_background

    logger.info("Catch-up: today's scan has not happened yet, starting it now.")
    return run_in_background("catch-up")
