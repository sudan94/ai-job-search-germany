"""The daily run: sources -> normalize -> dedup -> language -> embed -> score.

Each stage commits its own work, so a failure late in the run never throws away
what earlier stages achieved.  Ordering is chosen for cost:

* the free German-required regex runs on every new job and drops the obvious
  rejects before anything is billed,
* the embedding prefilter runs next (fractions of a cent per job),
* the model-backed language judgment and the rubric score only ever see jobs
  that survived both.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cv.profile import get_active_profile
from app.llm import LLMRefused, embedder, llm
from app.models import (
    AnalysisStage,
    Application,
    Job,
    JobAnalysis,
    JobStatus,
    RunLog,
    change_status,
)
from app.pipeline import language, scoring
from app.pipeline.dedup import pending_jobs, store_new_jobs
from app.pipeline.geo import is_germany_related
from app.pipeline.relevance import RelevanceRules, title_rejection
from app.settings_store import UserSettings, get_settings
from app.sources import build_sources
from app.sources.base import JobSource, RawJob, SourceError

logger = logging.getLogger(__name__)

#: Cap on how many previously unanalysed jobs a run picks up as backlog.
BACKLOG_LIMIT = 200


@dataclass
class RunCounters:
    fetched: int = 0
    new_jobs: int = 0
    duplicates: int = 0
    #: Dropped by the Germany-only filter before anything was stored.
    geo_dropped: int = 0
    #: Dropped by the title filter: wrong seniority, discipline or stack.
    off_target: int = 0
    #: The exclusion terms that did the most work, for tuning the list.
    off_target_reasons: dict[str, int] = field(default_factory=dict)
    language_dropped: int = 0
    similarity_dropped: int = 0
    scored: int = 0
    passed: int = 0
    errors: list[str] = field(default_factory=list)
    per_source: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    similarity_range: list[float] = field(default_factory=list)


def run_pipeline(
    db: Session,
    *,
    trigger: str = "manual",
    include_backlog: bool = True,
) -> RunLog:
    started = time.monotonic()
    config = get_settings(db)
    counters = RunCounters()

    run = RunLog(status="running", trigger=trigger)
    db.add(run)
    db.commit()
    db.refresh(run)

    try:
        raws = _fetch_all(config, counters)
        counters.fetched = len(raws)

        dedup = store_new_jobs(db, raws, run_id=run.id)
        counters.new_jobs = len(dedup.new_jobs)
        counters.duplicates = dedup.duplicates

        todo = pending_jobs(db, dedup.new_jobs)
        if include_backlog:
            todo += _backlog(db, exclude_ids={j.id for j in todo})

        profile = get_active_profile(db)
        if profile is None:
            counters.notes.append("No CV on file: stored jobs without scoring them.")
        elif not llm.available:
            counters.notes.append(
                "OPENAI_API_KEY is not set: stored and ranked jobs with heuristic "
                "language signals only, no scores."
            )

        _analyze(db, todo, profile=profile, config=config, counters=counters)

    except Exception as exc:  # the run log must survive any failure
        logger.exception("Run failed")
        counters.errors.append(f"run: {exc.__class__.__name__}: {exc}")

    _finalize(db, run, counters, duration=time.monotonic() - started)
    return run


# --------------------------------------------------------------------------- fetch


def _fetch_all(config: UserSettings, counters: RunCounters) -> list[RawJob]:
    sources = build_sources(config)
    if not sources:
        counters.errors.append("No sources are enabled or configured.")
        return []

    rules = config.relevance_rules() if config.relevance_filter else None

    collected: list[RawJob] = []
    with JobSource.build_client() as client:
        for source in sources:
            try:
                jobs = source.fetch(client)
            except SourceError as exc:
                counters.errors.append(f"{source.name}: {exc}")
                counters.per_source[source.name] = 0
                continue
            except Exception as exc:
                logger.exception("Source %s crashed", source.name)
                counters.errors.append(f"{source.name}: {exc.__class__.__name__}: {exc}")
                counters.per_source[source.name] = 0
                continue

            if not source.listings_are_current:
                jobs = _filter_by_age(jobs, config.max_age_days)
            if config.germany_only:
                kept = [job for job in jobs if _is_germany_related(job)]
                counters.geo_dropped += len(jobs) - len(kept)
                jobs = kept
            if rules is not None:
                jobs = _filter_by_title(jobs, rules, counters)
            counters.per_source[source.name] = len(jobs)
            collected.extend(jobs)

    return collected


def _filter_by_title(
    jobs: list[RawJob], rules: RelevanceRules, counters: RunCounters
) -> list[RawJob]:
    """Keep only titles that name a role I target, at a seniority I can apply to.

    Dropped here rather than stored and marked: an off-target posting is not a
    near miss to audit later, it is noise, and leaving it out keeps both the
    jobs table and the scoring budget for jobs worth looking at.  The reasons
    are counted so the run can report which terms did the filtering.
    """
    kept: list[RawJob] = []
    for job in jobs:
        reason = title_rejection(job.title, rules)
        if reason is None:
            kept.append(job)
            continue
        counters.off_target += 1
        counters.off_target_reasons[reason] = counters.off_target_reasons.get(reason, 0) + 1
    return kept


def _is_germany_related(job: RawJob) -> bool:
    return is_germany_related(
        location=job.location,
        source=job.source,
        company=job.company,
        description=job.description,
    )


def _filter_by_age(jobs: list[RawJob], max_age_days: int) -> list[RawJob]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    kept = []
    for job in jobs:
        posted = job.posted_date
        if posted is None:
            kept.append(job)  # unknown date: let it through, dedup handles repeats
            continue
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=timezone.utc)
        if posted >= cutoff:
            kept.append(job)
    return kept


def _backlog(db: Session, exclude_ids: set[int]) -> list[Job]:
    """Jobs stored earlier that never got a usable analysis (no CV, no key, error)."""
    stmt = (
        select(Job)
        .join(Application, Application.job_id == Job.id)
        .outerjoin(JobAnalysis, JobAnalysis.job_id == Job.id)
        .where(
            Application.status.notin_(JobStatus.CLOSED),
            (JobAnalysis.id.is_(None))
            | (JobAnalysis.stage.in_([AnalysisStage.PENDING, AnalysisStage.ERROR])),
        )
        .order_by(Job.first_seen.desc())
        .limit(BACKLOG_LIMIT)
    )
    return [job for job in db.execute(stmt).scalars().all() if job.id not in exclude_ids]


# --------------------------------------------------------------------------- analyze


def _analysis_for(db: Session, job: Job) -> JobAnalysis:
    analysis = db.execute(
        select(JobAnalysis).where(JobAnalysis.job_id == job.id)
    ).scalar_one_or_none()
    if analysis is None:
        analysis = JobAnalysis(job_id=job.id)
        db.add(analysis)
    return analysis


def _analyze(
    db: Session,
    jobs: list[Job],
    *,
    profile,
    config: UserSettings,
    counters: RunCounters,
) -> None:
    if not jobs:
        return

    cv_embedding = scoring.embedding_of(profile) if profile else None

    # Stage 1 - free heuristics on everything.
    survivors: list[tuple[Job, JobAnalysis]] = []
    for job in jobs:
        analysis = _analysis_for(db, job)
        verdict = language.heuristic_verdict(job.description or job.title)
        if verdict is not None:
            _apply_language(analysis, verdict)
            if config.english_only and verdict.german_required:
                _reject(db, job, analysis, AnalysisStage.LANGUAGE_REJECTED)
                counters.language_dropped += 1
                continue
        else:
            analysis.detected_language = language.detect_language(job.description)
        survivors.append((job, analysis))
    db.commit()

    # Stage 2 - similarity prefilter. Runs with or without a key: the
    # embedding backend is OpenAI or the built-in lexical one.
    cv_backend = scoring.embedding_backend_of(profile)
    if cv_embedding and cv_backend and cv_backend != embedder.name:
        counters.notes.append(
            f"CV was embedded with '{cv_backend}' but the active backend is "
            f"'{embedder.name}'. Similarity was skipped - re-upload the CV to compare again."
        )
        cv_embedding = None

    scored_candidates: list[tuple[Job, JobAnalysis, float]] = []
    if cv_embedding:
        scored_candidates = _prefilter(db, survivors, cv_embedding, counters)
    else:
        counters.notes.append("No comparable CV embedding: jobs were ranked by recency instead.")
        scored_candidates = [(job, analysis, 0.0) for job, analysis in survivors]

    if not llm.available:
        # Everything cheap is done; scoring needs a key.
        for _job, analysis, _similarity in scored_candidates:
            analysis.stage = AnalysisStage.PENDING
        db.commit()
        return

    # Best matches first, so a capped run spends its budget where it counts.
    scored_candidates.sort(key=lambda item: item[2], reverse=True)
    if scored_candidates and cv_embedding:
        counters.similarity_range = [
            round(scored_candidates[-1][2], 4),
            round(scored_candidates[0][2], 4),
        ]

    # Stages 3 and 4 - language judgment and rubric score, one job at a
    # time down the similarity ranking.  Interleaved rather than run as two
    # passes so the loop can stop the moment it has the matches it was asked
    # for: on a good day that costs a fraction of the ceiling, and the jobs it
    # skips are the worst-matching ones, which stay pending for the next run.
    target = config.target_matches_per_run
    ceiling = config.max_llm_scores_per_run

    for index, (job, analysis, _similarity) in enumerate(scored_candidates):
        if target and counters.passed >= target:
            counters.notes.append(
                f"Stopped after {counters.scored} scored: {counters.passed} matches is the "
                f"target. {len(scored_candidates) - index} lower-ranked jobs stay pending."
            )
            break
        if ceiling and counters.scored >= ceiling:
            counters.notes.append(
                f"Hit the ceiling of {ceiling} scored jobs with {counters.passed} match(es). "
                f"{len(scored_candidates) - index} lower-ranked jobs stay pending."
            )
            break

        if analysis.german_required is None:
            verdict = language.judge(job.description, title=job.title, company=job.company)
            _apply_language(analysis, verdict)
        if config.english_only and analysis.german_required:
            _reject(db, job, analysis, AnalysisStage.LANGUAGE_REJECTED)
            counters.language_dropped += 1
            db.commit()
            continue

        try:
            result = scoring.score_job(
                profile=profile,
                title=job.title,
                company=job.company,
                location=job.location,
                description=job.description,
                remote=job.remote,
            )
        except LLMRefused as exc:
            # One posting the model declined to judge. Record it and move on.
            logger.info("Scoring refused for job %s: %s", job.id, exc)
            analysis.stage = AnalysisStage.ERROR
            analysis.error = str(exc)[:500]
            db.commit()
            continue
        except Exception as exc:
            logger.warning("Scoring failed for job %s: %s", job.id, exc)
            counters.errors.append(f"score job {job.id}: {exc.__class__.__name__}: {exc}")
            analysis.stage = AnalysisStage.ERROR
            analysis.error = str(exc)[:500]
            db.commit()
            continue

        analysis.score = result.score
        analysis.score_reasons = json.dumps(result.model_dump(exclude={"score"}), ensure_ascii=False)
        analysis.stage = AnalysisStage.SCORED
        analysis.error = None
        analysis.analyzed_at = datetime.now(timezone.utc)
        counters.scored += 1

        application = _application_for(db, job)
        _apply_threshold(db, application, result.score, config)
        if result.score >= config.min_score:
            counters.passed += 1
        db.commit()


def _prefilter(
    db: Session,
    survivors: list[tuple[Job, JobAnalysis]],
    cv_embedding: list[float],
    counters: RunCounters,
) -> list[tuple[Job, JobAnalysis, float]]:
    """Embed anything not embedded yet, then score every job for similarity."""
    config = get_settings(db)

    todo = [(job, analysis) for job, analysis in survivors if not analysis.embedding]
    if todo:
        texts = [
            scoring.job_embedding_text(job.title, job.company, job.location, job.description)
            for job, _analysis in todo
        ]
        try:
            vectors = scoring.embed_job_texts(texts)
        except Exception as exc:
            logger.warning("Embedding batch failed: %s", exc)
            counters.errors.append(f"embed: {exc.__class__.__name__}: {exc}")
            vectors = []
        for (_job, analysis), vector in zip(todo, vectors):
            analysis.embedding = json.dumps(vector)
        db.commit()

    candidates: list[tuple[Job, JobAnalysis, float]] = []
    for job, analysis in survivors:
        if not analysis.embedding:
            continue  # embedding failed; leave it pending rather than guessing
        try:
            similarity = scoring.similarity_against_cv(json.loads(analysis.embedding), cv_embedding)
        except (json.JSONDecodeError, TypeError):
            continue

        analysis.similarity = similarity
        if config.similarity_floor and similarity < config.similarity_floor:
            _reject(db, job, analysis, AnalysisStage.BELOW_SIMILARITY)
            counters.similarity_dropped += 1
            continue
        candidates.append((job, analysis, similarity))

    db.commit()
    return candidates


def _apply_language(analysis: JobAnalysis, verdict: language.LanguageVerdict) -> None:
    analysis.working_language = verdict.working_language
    analysis.german_required = verdict.german_required
    analysis.language_confidence = verdict.confidence
    analysis.language_evidence = verdict.evidence[:500]
    if verdict.detected_language:
        analysis.detected_language = verdict.detected_language


def _application_for(db: Session, job: Job) -> Application:
    application = db.execute(
        select(Application).where(Application.job_id == job.id)
    ).scalar_one_or_none()
    if application is None:
        application = Application(job_id=job.id, status=JobStatus.NEW)
        db.add(application)
        db.flush()
    return application


_REJECTION_NOTES = {
    AnalysisStage.LANGUAGE_REJECTED: "German required",
    AnalysisStage.BELOW_SIMILARITY: "Below the similarity floor",
}


def _set_status(db: Session, application: Application, status: str, note: str) -> None:
    event = change_status(application, status, actor="system", note=note)
    if event is not None:
        db.add(event)


def _reject(db: Session, job: Job, analysis: JobAnalysis, stage: str) -> None:
    analysis.stage = stage
    analysis.analyzed_at = datetime.now(timezone.utc)
    application = _application_for(db, job)
    if application.status == JobStatus.NEW:
        note = _REJECTION_NOTES.get(stage, stage)
        _set_status(db, application, JobStatus.SYSTEM_REJECTED, note)


def _apply_threshold(
    db: Session, application: Application, score: int, config: UserSettings
) -> None:
    """Move a scored job between new and system_rejected by the pass mark.

    Only automatic statuses move: once I have marked a job interested, applied,
    rejected or ignored, the pipeline never overrides that.
    """
    if application.status not in JobStatus.AUTOMATIC:
        return
    if score < config.min_score and config.auto_reject_below_min_score:
        _set_status(
            db,
            application,
            JobStatus.SYSTEM_REJECTED,
            f"Score {score} is below the minimum of {config.min_score}",
        )
    else:
        # Passed, the threshold was lowered, or auto-reject was switched off.
        _set_status(db, application, JobStatus.NEW, f"Score {score}, minimum {config.min_score}")


def reapply_threshold(db: Session, config: UserSettings) -> int:
    """Re-sort already-scored jobs after the pass mark or auto-reject changed.

    Without this a new threshold only reached jobs scored after it was saved.
    Language and similarity rejections are left alone: they did not fail on score.
    Returns how many jobs changed status.
    """
    rows = db.execute(
        select(Application, JobAnalysis.score)
        .join(JobAnalysis, JobAnalysis.job_id == Application.job_id)
        .where(
            Application.status.in_(JobStatus.AUTOMATIC),
            JobAnalysis.stage == AnalysisStage.SCORED,
            JobAnalysis.score.isnot(None),
        )
    ).all()
    changed = 0
    for application, score in rows:
        before = application.status
        _apply_threshold(db, application, score, config)
        changed += application.status != before
    db.commit()
    return changed


def _finalize(db: Session, run: RunLog, counters: RunCounters, *, duration: float) -> None:
    run.finished_at = datetime.now(timezone.utc)
    run.fetched = counters.fetched
    run.new_jobs = counters.new_jobs
    run.duplicates = counters.duplicates
    run.language_dropped = counters.language_dropped
    run.similarity_dropped = counters.similarity_dropped
    run.scored = counters.scored
    run.passed = counters.passed
    run.errors = json.dumps(counters.errors[:50], ensure_ascii=False)
    run.details = json.dumps(
        {
            "per_source": counters.per_source,
            "notes": counters.notes,
            "duration_seconds": round(duration, 1),
            "llm_enabled": llm.available,
            "model": llm.model,
            "embedding_backend": embedder.name,
            "germany_dropped": counters.geo_dropped,
            "off_target": counters.off_target,
            # Most-used exclusion reasons first: this is how you tune the list.
            "off_target_reasons": dict(
                sorted(counters.off_target_reasons.items(), key=lambda kv: kv[1], reverse=True)[:12]
            ),
            "similarity_range": counters.similarity_range,
        },
        ensure_ascii=False,
    )
    if counters.errors and counters.fetched == 0:
        run.status = "error"
    elif counters.errors:
        run.status = "partial"
    else:
        run.status = "success"
    db.commit()
    logger.info(
        "Run %s finished: %s (fetched=%d new=%d scored=%d passed=%d)",
        run.id,
        run.status,
        run.fetched,
        run.new_jobs,
        run.scored,
        run.passed,
    )


# ----------------------------------------------------------------- single-job reruns


def rescore_job(db: Session, job: Job) -> JobAnalysis:
    """Re-run language + score for one job, ignoring caches.  Used by the UI."""
    config = get_settings(db)
    profile = get_active_profile(db)
    if profile is None:
        raise ValueError("Upload a CV before scoring jobs.")

    cv_embedding = scoring.embedding_of(profile)
    analysis = _analysis_for(db, job)

    job_embedding = scoring.embed_job_text(job.title, job.company, job.location, job.description)
    analysis.embedding = json.dumps(job_embedding)
    if cv_embedding:
        analysis.similarity = scoring.similarity_against_cv(job_embedding, cv_embedding)

    verdict = language.judge(job.description, title=job.title, company=job.company)
    _apply_language(analysis, verdict)

    result = scoring.score_job(
        profile=profile,
        title=job.title,
        company=job.company,
        location=job.location,
        description=job.description,
        remote=job.remote,
    )
    analysis.score = result.score
    analysis.score_reasons = json.dumps(result.model_dump(exclude={"score"}), ensure_ascii=False)
    analysis.stage = AnalysisStage.SCORED
    analysis.error = None
    analysis.analyzed_at = datetime.now(timezone.utc)

    application = _application_for(db, job)
    _apply_threshold(db, application, result.score, config)
    db.commit()
    return analysis

