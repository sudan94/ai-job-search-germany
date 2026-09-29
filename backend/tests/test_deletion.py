"""Deleting jobs and runs, including the cascade from a run to its jobs."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models import Application, Job, JobAnalysis, RunLog


def seed_run(db, **counts) -> RunLog:
    run = RunLog(status="success", trigger="test", **counts)
    db.add(run)
    db.commit()
    return run


def seed_job(db, *, title, run_id=None, status="new") -> Job:
    job = Job(
        external_id=f"test:{title}",
        source="arbeitnow",
        title=title,
        company="Acme GmbH",
        location="Berlin",
        description="Python, FastAPI, PostgreSQL.",
        run_id=run_id,
    )
    db.add(job)
    db.flush()
    db.add(JobAnalysis(job_id=job.id, score=80, stage="scored"))
    db.add(Application(job_id=job.id, status=status))
    db.commit()
    return job


def counts(db) -> tuple[int, int, int, int]:
    db.rollback()  # drop this session's snapshot; the API wrote through another one
    return tuple(
        db.execute(select(func.count()).select_from(model)).scalar_one()
        for model in (Job, JobAnalysis, Application, RunLog)
    )


def test_deleting_a_job_takes_its_analysis_and_application(client, db):
    job = seed_job(db, title="Junior Python Developer")

    assert client.delete(f"/api/jobs/{job.id}").status_code == 204
    assert counts(db)[:3] == (0, 0, 0), "no orphaned analysis or application rows"


def test_deleting_a_missing_job_is_404(client):
    assert client.delete("/api/jobs/4242").status_code == 404


def test_delete_all_jobs_needs_confirmation(client, db):
    seed_job(db, title="Junior PHP Developer")

    assert client.delete("/api/jobs").status_code == 400
    assert counts(db)[0] == 1, "the unconfirmed call changed nothing"

    body = client.delete("/api/jobs", params={"confirm": True}).json()
    assert body["deleted_jobs"] == 1
    assert counts(db)[:3] == (0, 0, 0)


def test_deleting_a_run_takes_the_jobs_it_found(client, db):
    first = seed_run(db, new_jobs=1)
    second = seed_run(db, new_jobs=1)
    seed_job(db, title="From the first run", run_id=first.id)
    seed_job(db, title="From the second run", run_id=second.id)
    seed_job(db, title="No run at all")

    body = client.delete(f"/api/runs/{first.id}").json()
    assert body == {"deleted_runs": 1, "deleted_jobs": 1}

    db.rollback()
    remaining = {job.title for job in db.execute(select(Job)).scalars()}
    assert remaining == {"From the second run", "No run at all"}
    assert counts(db)[1:3] == (2, 2), "only the deleted job's rows went"


def test_deleting_a_running_run_is_refused(client, db):
    run = RunLog(status="running", trigger="test")
    db.add(run)
    db.commit()

    assert client.delete(f"/api/runs/{run.id}").status_code == 409
    assert counts(db)[3] == 1


def test_deleting_a_missing_run_is_404(client):
    assert client.delete("/api/runs/4242").status_code == 404


def test_clearing_the_run_history_needs_confirmation(client, db):
    run = seed_run(db, new_jobs=1)
    seed_job(db, title="From a run", run_id=run.id)
    seed_job(db, title="Orphan")

    assert client.delete("/api/runs").status_code == 400
    assert counts(db)[3] == 1, "the unconfirmed call changed nothing"

    body = client.delete("/api/runs", params={"confirm": True}).json()
    assert body == {"deleted_runs": 1, "deleted_jobs": 1}

    db.rollback()
    remaining = {job.title for job in db.execute(select(Job)).scalars()}
    assert remaining == {"Orphan"}, "jobs no run owns survive; the Jobs tab clears those"
