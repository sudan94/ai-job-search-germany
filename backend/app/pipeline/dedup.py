"""Skip anything already seen - before any expensive work happens."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, Job, JobStatus
from app.pipeline.normalize import content_fingerprint, make_external_id, to_job
from app.sources.base import RawJob

logger = logging.getLogger(__name__)


@dataclass
class DedupResult:
    new_jobs: list[Job]
    duplicates: int


def store_new_jobs(db: Session, raws: list[RawJob], *, run_id: int | None = None) -> DedupResult:
    """Insert everything unseen; touch `last_seen` on everything we already have.

    `run_id` marks which run first brought a posting in, so deleting that run
    from the UI can take its jobs with it.  A posting seen again by a later run
    keeps its original owner - it was not that run's find.
    """
    if not raws:
        return DedupResult(new_jobs=[], duplicates=0)

    # Collapse duplicates inside this batch first (two sources, one job).
    batch: dict[str, RawJob] = {}
    batch_fingerprints: set[str] = set()
    in_batch_dupes = 0
    for raw in raws:
        external_id = make_external_id(raw)
        fingerprint = content_fingerprint(raw)
        if external_id in batch or fingerprint in batch_fingerprints:
            in_batch_dupes += 1
            # Keep whichever version carries a real description.
            existing = batch.get(external_id)
            if existing is not None and len(raw.description) > len(existing.description):
                batch[external_id] = raw
            continue
        batch[external_id] = raw
        batch_fingerprints.add(fingerprint)

    known = set(
        db.execute(select(Job.external_id).where(Job.external_id.in_(list(batch)))).scalars().all()
    )

    now = datetime.now(timezone.utc)
    if known:
        for job in db.execute(select(Job).where(Job.external_id.in_(list(known)))).scalars():
            job.last_seen = now

    new_jobs: list[Job] = []
    for external_id, raw in batch.items():
        if external_id in known:
            continue
        job = to_job(raw)
        job.run_id = run_id
        db.add(job)
        db.flush()  # need job.id for the application row
        db.add(Application(job_id=job.id, status=JobStatus.NEW))
        new_jobs.append(job)

    db.commit()
    duplicates = len(known) + in_batch_dupes
    logger.info("Dedup: %d new, %d already seen", len(new_jobs), duplicates)
    return DedupResult(new_jobs=new_jobs, duplicates=duplicates)


def pending_jobs(db: Session, jobs: list[Job]) -> list[Job]:
    """Drop jobs I have already decided on - they never get another LLM call."""
    if not jobs:
        return []
    closed = set(
        db.execute(
            select(Application.job_id).where(
                Application.job_id.in_([j.id for j in jobs]),
                Application.status.in_(JobStatus.CLOSED),
            )
        )
        .scalars()
        .all()
    )
    return [job for job in jobs if job.id not in closed]
