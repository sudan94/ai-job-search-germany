"""Offline test fixtures: a throwaway SQLite file, no network, no model calls."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_tmpdir = tempfile.mkdtemp(prefix="job-portal-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_tmpdir, 'test.db').as_posix()}"
os.environ["OPENAI_API_KEY"] = ""
os.environ["JSEARCH_API_KEY"] = ""
os.environ["ADZUNA_APP_ID"] = ""
os.environ["ADZUNA_APP_KEY"] = ""
os.environ["ENABLE_SCHEDULER"] = "false"
os.environ["CATCH_UP_ON_STARTUP"] = "false"

from app.db import Base, SessionLocal, engine, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(bind=engine)
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
