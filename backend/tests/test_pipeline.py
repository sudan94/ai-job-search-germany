"""End-to-end pipeline tests with a fake source and a fake model."""

from __future__ import annotations

import json

import pytest

from app.llm import embedder
from app.models import Application, ApplicationEvent, Job, JobAnalysis
from app.pipeline import run as run_module
from app.pipeline.language import LanguageJudgment
from app.pipeline.scoring import ScoreResult
from app.sources.base import JobSource, RawJob

CV_TEXT = (
    "Backend engineer. PHP, Laravel, MySQL, Docker in production. "
    "Python, FastAPI and pandas from university and personal projects. Based in Berlin."
)


class FakeSource(JobSource):
    name = "arbeitnow"
    label = "Fake"

    def __init__(self, config, jobs):
        super().__init__(config)
        self._jobs = jobs

    def fetch(self, client):
        return self._jobs


def make_jobs() -> list[RawJob]:
    return [
        RawJob(
            source="arbeitnow",
            source_id="good-1",
            title="Backend Developer Python",
            company="Acme GmbH",
            location="Berlin",
            description=(
                "You will build APIs with Python, FastAPI, Docker and PostgreSQL. "
                "English is our company language."
            ),
        ),
        RawJob(
            source="arbeitnow",
            source_id="german-1",
            title="Backend Entwickler",
            company="Deutsche Firma GmbH",
            location="München",
            description="Wir suchen einen Entwickler. Verhandlungssicheres Deutsch ist erforderlich.",
        ),
        # Passes the title filter but is a poor match for this CV, so the
        # similarity ranking and the threshold still have something to do.
        RawJob(
            source="arbeitnow",
            source_id="weak-1",
            title="Frontend Developer React",
            company="Pixel GmbH",
            location="Hamburg",
            description="Build interfaces with React, CSS and Figma handoffs. Design systems work.",
        ),
    ]


@pytest.fixture
def fake_sources(monkeypatch):
    jobs = make_jobs()
    monkeypatch.setattr(run_module, "build_sources", lambda config: [FakeSource(config, jobs)])
    return jobs


@pytest.fixture
def fake_llm(monkeypatch):
    """A model that scores by keyword, so thresholds can be tested offline."""
    from app.llm import LLMClient

    monkeypatch.setattr(LLMClient, "available", property(lambda self: True))

    def fake_json_chat(self, system, user, schema, *, temperature=0.0, max_tokens=None):
        if schema is ScoreResult:
            # Key off the job title only - the CV section of the prompt mentions
            # Python too, so matching the whole prompt would score everything high.
            title = next((line for line in user.splitlines() if line.startswith("Title:")), "")
            score = 88 if "backend" in title.lower() else 20
            return ScoreResult(
                score=score, matched=["Python"], missing=["Kubernetes"], verdict="fake"
            )
        if schema is LanguageJudgment:
            return LanguageJudgment(
                working_language="english",
                german_required=False,
                confidence=0.8,
                evidence="fake judgment",
            )
        return schema()

    monkeypatch.setattr(LLMClient, "json_chat", fake_json_chat)
    monkeypatch.setattr(
        LLMClient,
        "text_chat",
        lambda self, system, user, *, temperature=0.6, max_tokens=None: "Dear Acme, plain text.",
    )


@pytest.fixture
def cv(db):
    """A CV embedded with the live backend, so similarity ranking is real."""
    from app.models import CVProfile

    profile = CVProfile(
        filename="cv.txt",
        raw_text=CV_TEXT,
        summary="Backend engineer moving from PHP to Python.",
        skills=json.dumps(["php", "python", "fastapi", "docker", "mysql"]),
        role_targets=json.dumps(["Backend Developer"]),
        embedding=json.dumps(embedder.embed_query(CV_TEXT)),
        embedding_model=f"{embedder.name}:builtin",
        is_active=True,
    )
    db.add(profile)
    db.commit()
    return profile


def test_run_without_cv_stores_jobs_but_does_not_score(db, fake_sources):
    run = run_module.run_pipeline(db, trigger="test")

    assert run.status == "success"
    assert run.fetched == 3
    assert run.new_jobs == 3
    assert run.scored == 0
    assert db.query(Job).count() == 3
    assert "No CV on file" in run.details


def test_second_run_finds_nothing_new(db, fake_sources):
    run_module.run_pipeline(db, trigger="first")
    second = run_module.run_pipeline(db, trigger="second")

    assert second.new_jobs == 0
    assert second.duplicates == 3
    assert db.query(Job).count() == 3


def test_german_required_job_is_dropped_before_any_model_call(db, fake_sources):
    run_module.run_pipeline(db, trigger="test")

    german = db.query(Job).filter_by(external_id="arbeitnow:german-1").one()
    analysis = db.query(JobAnalysis).filter_by(job_id=german.id).one()
    assert analysis.german_required is True
    assert analysis.stage == "language_rejected"
    application = db.query(Application).filter_by(job_id=german.id).one()
    assert application.status == "system_rejected"
    event = db.query(ApplicationEvent).filter_by(job_id=german.id).one()
    assert (event.actor, event.to_status, event.note) == ("system", "system_rejected", "German required")


def test_prefilter_ranks_the_relevant_job_above_the_irrelevant_one(db, fake_sources, cv):
    """The keyless lexical backend must still separate a Python role from sales."""
    run_module.run_pipeline(db, trigger="test")

    good = db.query(Job).filter_by(external_id="arbeitnow:good-1").one()
    weak = db.query(Job).filter_by(external_id="arbeitnow:weak-1").one()

    good_similarity = db.query(JobAnalysis).filter_by(job_id=good.id).one().similarity
    weak_similarity = db.query(JobAnalysis).filter_by(job_id=weak.id).one().similarity

    assert good_similarity > weak_similarity


def test_full_run_scores_and_filters(db, fake_sources, fake_llm, cv):
    run = run_module.run_pipeline(db, trigger="test")

    assert run.language_dropped == 1, "the German-required job never reaches scoring"
    assert run.scored == 2
    assert run.passed == 1, "only the Python role clears the threshold"
    assert run.letters_written == 0, "cover letters are no longer written"

    good = db.query(Job).filter_by(external_id="arbeitnow:good-1").one()
    analysis = db.query(JobAnalysis).filter_by(job_id=good.id).one()
    assert analysis.score == 88
    assert analysis.stage == "scored"
    assert json.loads(analysis.score_reasons)["matched"] == ["Python"]
    assert analysis.embedding, "the embedding is cached so re-runs never re-embed"

    application = db.query(Application).filter_by(job_id=good.id).one()
    assert application.status == "new"
    assert application.cover_letter is None

    weak = db.query(Job).filter_by(external_id="arbeitnow:weak-1").one()
    assert db.query(Application).filter_by(job_id=weak.id).one().status == "system_rejected"


def test_similarity_floor_drops_jobs_before_scoring(db, fake_sources, fake_llm, cv):
    from app.settings_store import get_settings, save_settings

    config = get_settings(db)
    config.similarity_floor = 0.99  # nothing can clear this
    save_settings(db, config)

    run = run_module.run_pipeline(db, trigger="test")
    assert run.similarity_dropped >= 1
    assert run.scored == 0


def test_run_budget_caps_the_number_of_scored_jobs(db, fake_sources, fake_llm, cv):
    from app.settings_store import get_settings, save_settings

    config = get_settings(db)
    config.max_llm_scores_per_run = 1
    config.target_matches_per_run = 0  # no target, so the ceiling is what bites
    save_settings(db, config)

    run = run_module.run_pipeline(db, trigger="test")
    assert run.scored == 1
    assert "ceiling of 1" in run.details


def test_a_run_stops_once_it_has_the_matches_it_was_asked_for(db, fake_sources, fake_llm, cv):
    """The whole point of the target: a good day costs less than a thin one."""
    from app.settings_store import get_settings, save_settings

    config = get_settings(db)
    config.target_matches_per_run = 1
    save_settings(db, config)

    run = run_module.run_pipeline(db, trigger="test")
    assert run.passed == 1
    assert run.scored == 1, "it stopped at the first match instead of scoring the rest"
    assert "target" in run.details

    weak = db.query(Job).filter_by(external_id="arbeitnow:weak-1").one()
    analysis = db.query(JobAnalysis).filter_by(job_id=weak.id).one()
    assert analysis.stage == "pending", "the skipped job waits for the next run"


def test_score_below_threshold_is_kept_but_marked_rejected(db, fake_sources, fake_llm, cv):
    from app.settings_store import get_settings, save_settings

    config = get_settings(db)
    config.min_score = 95  # nothing can pass
    save_settings(db, config)

    run = run_module.run_pipeline(db, trigger="test")
    assert run.passed == 0

    good = db.query(Job).filter_by(external_id="arbeitnow:good-1").one()
    assert db.query(Application).filter_by(job_id=good.id).one().status == "system_rejected"
    assert db.query(JobAnalysis).filter_by(job_id=good.id).one().score == 88, (
        "rejected jobs keep their score so the filter can be audited"
    )


def test_auto_reject_off_keeps_low_scores_new(db, fake_sources, fake_llm, cv):
    from app.settings_store import get_settings, save_settings

    config = get_settings(db)
    config.min_score = 95
    config.auto_reject_below_min_score = False
    save_settings(db, config)

    run = run_module.run_pipeline(db, trigger="test")
    assert run.passed == 0, "still not a match: the pass mark has not moved"
    good = db.query(Job).filter_by(external_id="arbeitnow:good-1").one()
    assert db.query(Application).filter_by(job_id=good.id).one().status == "new"


def test_english_only_off_keeps_german_jobs(db, fake_sources, fake_llm, cv):
    from app.settings_store import get_settings, save_settings

    config = get_settings(db)
    config.english_only = False
    save_settings(db, config)

    run = run_module.run_pipeline(db, trigger="test")
    assert run.language_dropped == 0

    german = db.query(Job).filter_by(external_id="arbeitnow:german-1").one()
    analysis = db.query(JobAnalysis).filter_by(job_id=german.id).one()
    assert analysis.german_required is True
    assert analysis.stage != "language_rejected"


def test_germany_only_drops_jobs_outside_germany(db, monkeypatch, fake_llm, cv):
    jobs = make_jobs() + [
        RawJob(
            source="arbeitnow",
            source_id="spain-1",
            title="Backend Developer Python",
            company="Sunny SL",
            location="Madrid, Spain",
            description="Python and FastAPI work from our Madrid office.",
        ),
        RawJob(
            source="arbeitnow",
            source_id="brazil-remote",
            title="Senior Backend Engineer",
            company="Swile",
            location="Remote, Brasil",
            remote=True,
            description="Remote Python role for our Brazilian team.",
        ),
    ]
    monkeypatch.setattr(run_module, "build_sources", lambda config: [FakeSource(config, jobs)])

    run = run_module.run_pipeline(db, trigger="test")

    assert run.fetched == 3, "the Spanish and Brazilian roles never reach the database"
    assert json.loads(run.details)["germany_dropped"] == 2
    assert db.query(Job).filter_by(external_id="arbeitnow:spain-1").one_or_none() is None


def test_germany_only_off_keeps_everything(db, monkeypatch, fake_llm, cv):
    from app.settings_store import get_settings, save_settings

    config = get_settings(db)
    config.germany_only = False
    save_settings(db, config)

    jobs = make_jobs() + [
        RawJob(
            source="arbeitnow",
            source_id="spain-1",
            title="Backend Developer",
            company="Sunny SL",
            location="Madrid, Spain",
            description="Python work in Madrid.",
        )
    ]
    monkeypatch.setattr(run_module, "build_sources", lambda config: [FakeSource(config, jobs)])

    run = run_module.run_pipeline(db, trigger="test")
    assert run.fetched == 4
    assert db.query(Job).filter_by(external_id="arbeitnow:spain-1").one_or_none() is not None


def test_applied_jobs_are_never_re_scored(db, fake_sources, fake_llm, cv):
    run_module.run_pipeline(db, trigger="first")

    good = db.query(Job).filter_by(external_id="arbeitnow:good-1").one()
    application = db.query(Application).filter_by(job_id=good.id).one()
    application.status = "applied"
    db.commit()

    second = run_module.run_pipeline(db, trigger="second")
    assert second.scored == 0
    assert db.query(Application).filter_by(job_id=good.id).one().status == "applied"


def test_a_refusal_skips_one_job_without_killing_the_run(db, fake_sources, fake_llm, cv, monkeypatch):
    from app.llm import LLMClient, LLMRefused

    def refusing_json_chat(self, system, user, schema, *, temperature=0.0, max_tokens=None):
        if schema is ScoreResult:
            raise LLMRefused("The model declined this request: policy.")
        return LanguageJudgment(
            working_language="english", german_required=False, confidence=0.8, evidence="fake"
        )

    monkeypatch.setattr(LLMClient, "json_chat", refusing_json_chat)

    run = run_module.run_pipeline(db, trigger="test")
    assert run.status == "success", "a refusal is not a run failure"
    assert run.scored == 0

    good = db.query(Job).filter_by(external_id="arbeitnow:good-1").one()
    analysis = db.query(JobAnalysis).filter_by(job_id=good.id).one()
    assert analysis.stage == "error"
    assert "declined" in analysis.error


def test_source_failure_is_logged_but_the_run_survives(db, monkeypatch, fake_llm, cv):
    class BrokenSource(FakeSource):
        def fetch(self, client):
            raise RuntimeError("boom")

    working = FakeSource(None, make_jobs())

    def build(config):
        broken = BrokenSource(config, [])
        working.config = config
        return [broken, working]

    monkeypatch.setattr(run_module, "build_sources", build)

    run = run_module.run_pipeline(db, trigger="test")
    assert run.status == "partial"
    assert any("boom" in error for error in run.error_list)
    assert run.new_jobs == 3, "the healthy source still contributed"


def test_ats_boards_ignore_the_max_age_cutoff(db, monkeypatch, fake_llm, cv):
    """A board only lists open jobs, so "published 6 weeks ago" is not stale."""
    from datetime import datetime, timedelta, timezone

    old = datetime.now(timezone.utc) - timedelta(days=60)
    aged = RawJob(
        source="arbeitnow",
        source_id="aged-1",
        title="Python Developer",
        company="Old Post GmbH",
        location="Berlin",
        description="Python and FastAPI.",
        posted_date=old,
    )

    class Board(FakeSource):
        listings_are_current = True

    monkeypatch.setattr(run_module, "build_sources", lambda config: [FakeSource(config, [aged])])
    assert run_module.run_pipeline(db, trigger="aggregator").fetched == 0

    monkeypatch.setattr(run_module, "build_sources", lambda config: [Board(config, [aged])])
    assert run_module.run_pipeline(db, trigger="board").fetched == 1
