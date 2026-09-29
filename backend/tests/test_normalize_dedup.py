from __future__ import annotations

from app.models import Application, Job
from app.pipeline.dedup import pending_jobs, store_new_jobs
from app.pipeline.normalize import canonical, make_external_id, to_job
from app.sources.base import RawJob


def raw(**overrides) -> RawJob:
    defaults = dict(
        source="arbeitnow",
        source_id="python-dev-berlin-123",
        title="Backend Developer (m/w/d)",
        company="Acme GmbH",
        location="Berlin",
        description="We build things with Python.",
    )
    defaults.update(overrides)
    return RawJob(**defaults)


def test_external_id_prefers_source_id():
    assert make_external_id(raw()) == "arbeitnow:python-dev-berlin-123"


def test_external_id_falls_back_to_content_hash():
    a = make_external_id(raw(source_id=None))
    b = make_external_id(raw(source_id=None, title="  backend   developer (w/m/d) ", location="berlin"))
    assert a.startswith("hash:")
    assert a == b, "gender suffix, case and whitespace must not change the id"


def test_canonical_strips_gender_markers():
    assert canonical("Senior Python Developer (m/w/d)") == "senior python developer"


def test_store_new_jobs_dedups_within_batch(db):
    result = store_new_jobs(db, [raw(), raw(), raw(source_id="other", title="Data Engineer")])
    assert len(result.new_jobs) == 2
    assert result.duplicates == 1


def test_store_new_jobs_skips_already_seen(db):
    store_new_jobs(db, [raw()])
    second = store_new_jobs(db, [raw(), raw(source_id="new-one", title="ML Engineer")])
    assert [job.title for job in second.new_jobs] == ["ML Engineer"]
    assert second.duplicates == 1
    assert db.query(Job).count() == 2


def test_same_job_from_two_sources_collapses(db):
    result = store_new_jobs(
        db,
        [
            raw(source="arbeitnow", source_id=None),
            raw(source="adzuna", source_id=None, description="Different wording, same role."),
        ],
    )
    assert len(result.new_jobs) == 1


def test_every_new_job_gets_an_application_row(db):
    store_new_jobs(db, [raw()])
    assert db.query(Application).count() == 1
    assert db.query(Application).one().status == "new"


def test_pending_jobs_excludes_closed_statuses(db):
    result = store_new_jobs(db, [raw(), raw(source_id="two", title="Data Engineer")])
    application = db.query(Application).filter_by(job_id=result.new_jobs[0].id).one()
    application.status = "applied"
    db.commit()

    remaining = pending_jobs(db, result.new_jobs)
    assert [job.title for job in remaining] == ["Data Engineer"]


def test_to_job_truncates_and_serializes_raw():
    job = to_job(raw(raw={"nested": {"value": 1}}))
    assert job.external_id.startswith("arbeitnow:")
    assert '"nested"' in job.raw_json
