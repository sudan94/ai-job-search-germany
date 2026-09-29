"""PDF text extraction reads every page, and the status migration runs once."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.cv.profile import extract_text


def _pdf(pages: list[str]) -> bytes:
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    for body in pages:
        page = document.new_page()
        page.insert_text((72, 72), body)
    data = document.tobytes()
    document.close()
    return data


def test_every_pdf_page_is_read():
    pages = [f"Page {n}: Python developer, FastAPI, PostgreSQL, Docker, projects." for n in range(1, 4)]
    extracted = extract_text("cv.pdf", _pdf(pages))
    assert extracted.pages == 3
    for n in range(1, 4):
        assert f"Page {n}:" in extracted.text


def test_text_files_have_no_page_count():
    extracted = extract_text("cv.md", ("Python developer. " * 10).encode())
    assert extracted.pages is None


def test_old_rejected_rows_become_system_rejected_once(db):
    from app import db as db_module
    from app.models import Application, Job

    job = Job(external_id="x:1", source="x", title="t")
    db.add(job)
    db.flush()
    db.add(Application(job_id=job.id, status="rejected"))
    db.commit()

    # Pretend this is an old database that never ran the migration.
    db.execute(text("DELETE FROM schema_migration"))
    db.commit()
    db_module._apply_data_migrations(fresh=False)
    db.expire_all()
    assert db.query(Application).one().status == "system_rejected"

    # A company rejection set afterwards must survive the next startup.
    db.query(Application).one().status = "rejected"
    db.commit()
    db_module.init_db()
    db.expire_all()
    assert db.query(Application).one().status == "rejected"
