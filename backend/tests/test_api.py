from __future__ import annotations

from app.models import Application, Job, JobAnalysis


def seed_job(db, *, title="Backend Developer", score=80, status="new") -> Job:
    job = Job(
        external_id=f"test:{title}",
        source="arbeitnow",
        title=title,
        company="Acme GmbH",
        location="Berlin",
        remote=True,
        url="https://example.com/job",
        description="Python, FastAPI, PostgreSQL.",
    )
    db.add(job)
    db.flush()
    db.add(
        JobAnalysis(
            job_id=job.id,
            score=score,
            similarity=0.5,
            score_reasons='{"matched": ["Python"], "missing": ["Kubernetes"], "verdict": "good fit"}',
            german_required=False,
            working_language="english",
            stage="scored",
        )
    )
    db.add(Application(job_id=job.id, status=status))
    db.commit()
    return job


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["llm_enabled"] is False


def test_settings_roundtrip(client):
    defaults = client.get("/api/settings").json()
    assert defaults["min_score"] == 65
    assert defaults["english_only"] is True

    defaults["min_score"] = 72
    defaults["keywords"] = ["python developer", "  ", "data engineer"]
    updated = client.put("/api/settings", json=defaults).json()
    assert updated["min_score"] == 72
    assert updated["keywords"] == ["python developer", "data engineer"], "blanks are dropped"

    assert client.get("/api/settings").json()["min_score"] == 72


def test_settings_rejects_bad_values(client):
    payload = client.get("/api/settings").json()
    payload["min_score"] = 900
    assert client.put("/api/settings", json=payload).status_code == 422

    payload["min_score"] = 65
    payload["daily_run_time"] = "9am"
    assert client.put("/api/settings", json=payload).status_code == 422


def test_sources_listing(client):
    sources = client.get("/api/settings/sources").json()
    names = {source["name"] for source in sources}
    assert {
        "arbeitnow", "arbeitsagentur", "adzuna", "greenhouse", "lever", "ashby", "jsearch"
    } == names
    for keyed in ("adzuna", "jsearch"):
        source = next(s for s in sources if s["name"] == keyed)
        assert source["configured"] is False, "no keys in the test env"


def test_job_list_filters_and_sorts(client, db):
    seed_job(db, title="High Score", score=90)
    seed_job(db, title="Low Score", score=40, status="system_rejected")

    body = client.get("/api/jobs").json()
    assert body["total"] == 2
    assert [item["title"] for item in body["items"]] == ["High Score", "Low Score"]

    filtered = client.get("/api/jobs", params={"min_score": 70}).json()
    assert [item["title"] for item in filtered["items"]] == ["High Score"]

    by_status = client.get("/api/jobs", params={"status": "system_rejected"}).json()
    assert [item["title"] for item in by_status["items"]] == ["Low Score"]

    searched = client.get("/api/jobs", params={"search": "high"}).json()
    assert searched["total"] == 1


def test_job_detail_includes_description_and_analysis(client, db):
    job = seed_job(db)
    body = client.get(f"/api/jobs/{job.id}").json()
    assert body["description"].startswith("Python")
    assert body["analysis"]["matched"] == ["Python"]
    assert body["analysis"]["missing"] == ["Kubernetes"]
    assert body["application"]["status"] == "new"


def test_status_transitions_set_and_clear_applied_date(client, db):
    job = seed_job(db)

    applied = client.patch(f"/api/jobs/{job.id}/status", json={"status": "applied"}).json()
    assert applied["status"] == "applied"
    assert applied["applied_date"] is not None

    ignored = client.patch(f"/api/jobs/{job.id}/status", json={"status": "ignored"}).json()
    assert ignored["applied_date"] is None

    notes = client.patch(f"/api/jobs/{job.id}/status", json={"notes": "called them"}).json()
    assert notes["notes"] == "called them"
    assert notes["status"] == "ignored", "notes-only update keeps the status"


def test_invalid_status_is_rejected(client, db):
    job = seed_job(db)
    assert client.patch(f"/api/jobs/{job.id}/status", json={"status": "maybe"}).status_code == 422


def test_company_rejection_keeps_the_applied_date(client, db):
    job = seed_job(db)
    applied = client.patch(f"/api/jobs/{job.id}/status", json={"status": "applied"}).json()
    rejected = client.patch(f"/api/jobs/{job.id}/status", json={"status": "rejected"}).json()
    assert rejected["status"] == "rejected"
    assert rejected["applied_date"] == applied["applied_date"]


def test_status_changes_build_a_timeline(client, db):
    job = seed_job(db)
    client.patch(f"/api/jobs/{job.id}/status", json={"status": "interested"})
    client.patch(f"/api/jobs/{job.id}/status", json={"status": "applied"})
    client.patch(f"/api/jobs/{job.id}/status", json={"log": "Phone screen booked"})
    client.patch(f"/api/jobs/{job.id}/status", json={"status": "applied"})  # no-op

    events = client.get(f"/api/jobs/{job.id}").json()["events"]
    assert [(e["from_status"], e["to_status"], e["note"]) for e in events] == [
        (None, None, "Phone screen booked"),
        ("interested", "applied", ""),
        ("new", "interested", ""),
    ], "newest first, and an unchanged status adds nothing"

    deleted = client.delete(f"/api/jobs/{job.id}/events/{events[0]['id']}")
    assert deleted.status_code == 204
    assert len(client.get(f"/api/jobs/{job.id}/events").json()) == 2


def test_follow_up_date_is_set_cleared_and_filtered(client, db):
    due = seed_job(db, title="Due")
    later = seed_job(db, title="Later")
    client.patch(
        f"/api/jobs/{due.id}/status",
        json={"status": "applied", "follow_up_date": "2020-01-01T00:00:00Z", "contact": " Anna "},
    )
    client.patch(
        f"/api/jobs/{later.id}/status",
        json={"status": "applied", "follow_up_date": "2999-01-01T00:00:00Z"},
    )

    body = client.get("/api/jobs", params={"follow_up_due": True}).json()
    assert [item["title"] for item in body["items"]] == ["Due"]
    assert body["items"][0]["application"]["contact"] == "Anna"
    assert client.get("/api/stats").json()["follow_ups_due"] == 1

    notes_only = client.patch(f"/api/jobs/{due.id}/status", json={"notes": "x"}).json()
    assert notes_only["follow_up_date"] is not None, "a field that is not sent is kept"
    cleared = client.patch(f"/api/jobs/{due.id}/status", json={"follow_up_date": None}).json()
    assert cleared["follow_up_date"] is None
    assert client.get("/api/stats").json()["follow_ups_due"] == 0


def test_raising_the_threshold_re_sorts_scored_jobs(client, db):
    good = seed_job(db, title="Good", score=70)
    mine = seed_job(db, title="Mine", score=50, status="interested")

    settings = client.get("/api/settings").json()
    settings["min_score"] = 75
    client.put("/api/settings", json=settings)
    assert client.get(f"/api/jobs/{good.id}").json()["application"]["status"] == "system_rejected"
    assert client.get(f"/api/jobs/{mine.id}").json()["application"]["status"] == "interested", (
        "a status I set myself is never overridden"
    )

    settings["auto_reject_below_min_score"] = False
    client.put("/api/settings", json=settings)
    assert client.get(f"/api/jobs/{good.id}").json()["application"]["status"] == "new"


def test_cover_letter_endpoints_are_gone(client, db):
    job = seed_job(db)
    assert client.post(f"/api/jobs/{job.id}/cover-letter/generate").status_code in (404, 405)
    assert "cover_letter" not in client.get(f"/api/jobs/{job.id}").json()["application"]


def test_missing_job_is_404(client):
    assert client.get("/api/jobs/9999").status_code == 404


def test_stats(client, db):
    seed_job(db, title="One", score=90)
    seed_job(db, title="Two", score=30, status="ignored")

    body = client.get("/api/stats").json()
    assert body["total_jobs"] == 2
    assert body["by_status"]["ignored"] == 1
    assert body["passing"] == 1
    assert body["has_cv"] is False


def test_runs_empty_then_listed(client, db):
    assert client.get("/api/runs").json() == []

    from app.models import RunLog

    db.add(RunLog(status="success", trigger="test", fetched=10, new_jobs=4, passed=2))
    db.commit()

    runs = client.get("/api/runs").json()
    assert runs[0]["fetched"] == 10
    assert runs[0]["errors"] == []


def test_cv_endpoint_is_empty_before_upload(client):
    assert client.get("/api/cv").json() is None
    assert client.get("/api/cv/raw").status_code == 404


def test_cv_text_upload_without_model_uses_heuristics(client):
    text = (
        "Sudan Upadhaya. Backend engineer with 4 years of experience. "
        "PHP, Laravel, MySQL, Docker and Git in production. Python, FastAPI and pandas "
        "from university coursework and personal projects. Based in Germany. " * 3
    )
    body = client.post("/api/cv/text", json={"text": text, "filename": "cv.txt"}).json()
    assert "php" in body["skills"]
    assert "python" in body["skills"]
    assert body["has_embedding"] is True, "the lexical backend needs no key"
    assert body["embedding_model"].startswith("lexical:")
    assert client.get("/api/cv").json()["filename"] == "cv.txt"
