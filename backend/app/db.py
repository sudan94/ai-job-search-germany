"""SQLAlchemy setup.  SQLite today, Postgres-ready (only the URL changes)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import logging

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

_is_sqlite = settings.database_url.startswith("sqlite")

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    pool_pre_ping=True,
    future=True,
)

if _is_sqlite:

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Session for background work (pipeline, scheduler, CLI)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


#: Columns added after the first release, as {table: {column: DDL type}}.
#: `create_all` only ever creates missing tables, so an existing database keeps
#: its old shape and fails with "no such column" until these are added.  There
#: is no migration tool here on purpose - one personal SQLite file does not
#: justify Alembic - but a database that survives an upgrade does.
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "job": {"run_id": "INTEGER"},
    "application": {
        "follow_up_date": "DATETIME",
        "contact": "TEXT NOT NULL DEFAULT ''",
        "status_changed_at": "DATETIME",
    },
    "cv_profile": {
        "education": "TEXT NOT NULL DEFAULT '[]'",
        "projects": "TEXT NOT NULL DEFAULT '[]'",
        "certifications": "TEXT NOT NULL DEFAULT '[]'",
        "page_count": "INTEGER",
    },
}

#: One-off data changes, applied once each and recorded in `schema_migration`.
_DATA_MIGRATIONS: list[tuple[str, str]] = [
    # "rejected" used to mean "dropped by a filter".  It now means "rejected by
    # the company", so every existing row moves to the new system status.
    (
        "2026-09-rejected-to-system-rejected",
        "UPDATE application SET status = 'system_rejected' WHERE status = 'rejected'",
    ),
]


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, columns in _ADDED_COLUMNS.items():
        if table not in existing_tables:
            continue  # create_all just made it with every column
        present = {column["name"] for column in inspector.get_columns(table)}
        for name, ddl_type in columns.items():
            if name in present:
                continue
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))
            logger.info("Added missing column %s.%s", table, name)


def _apply_data_migrations(*, fresh: bool) -> None:
    """Run each pending data migration once.  A fresh database has no old rows,
    so its migrations are only recorded, never executed."""
    with engine.begin() as connection:
        done = set(connection.execute(text("SELECT name FROM schema_migration")).scalars())
        for name, statement in _DATA_MIGRATIONS:
            if name in done:
                continue
            if not fresh:
                connection.execute(text(statement))
                logger.info("Applied data migration %s", name)
            connection.execute(
                text(
                    "INSERT INTO schema_migration (name, applied_at) "
                    "VALUES (:name, CURRENT_TIMESTAMP)"
                ),
                {"name": name},
            )


def init_db() -> None:
    from app import models  # noqa: F401  (register mappers)

    fresh = "application" not in inspect(engine).get_table_names()
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    _apply_data_migrations(fresh=fresh)
