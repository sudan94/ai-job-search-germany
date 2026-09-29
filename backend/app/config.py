"""Environment-backed configuration.

Everything a user tunes day to day (thresholds, keywords, sources) lives in the
database and is editable from the dashboard - see `app.settings_store`.  This
module only holds process-level configuration: secrets, model names, where the
database file is, whether the in-process scheduler runs.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent

#: Used whenever no gateway is configured.  Always passed to the SDK explicitly
#: - see the note on `openai_base_url` below.
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # OpenAI / compatible gateway. The same key covers chat and embeddings;
    # without it the prefilter falls back to a keyless lexical backend.
    openai_api_key: str | None = None
    #: Optional gateway.  `.env` ships this key blank, and an empty string is
    #: not the same as unset: the OpenAI SDK reads OPENAI_BASE_URL from the
    #: environment itself, so a blank value there makes every request relative
    #: and fails as "Connection error".  Blanks are normalized to None below and
    #: the base URL is always passed to the client explicitly.
    openai_base_url: str | None = None
    chat_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"

    # Adzuna
    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None

    # JSearch (Google for Jobs, which carries Indeed and StepStone postings).
    # A key from openwebninja.com works as is; for a RapidAPI key set the host
    # to jsearch.p.rapidapi.com.  The host decides the URL and auth header.
    jsearch_api_key: str | None = None
    jsearch_api_host: str = "api.openwebninja.com"

    # Storage
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'job_portal.db').as_posix()}"

    # Scheduling
    timezone: str = "Europe/Berlin"
    enable_scheduler: bool = True
    catch_up_on_startup: bool = True

    # HTTP
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    http_timeout_seconds: float = 30.0
    user_agent: str = "job-portal/1.0 (personal job search tool)"

    log_level: str = "INFO"

    @field_validator(
        "openai_api_key",
        "openai_base_url",
        "adzuna_app_id",
        "adzuna_app_key",
        "jsearch_api_key",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value):
        """A key left blank in `.env` means "not configured", not "empty string"."""
        if isinstance(value, str):
            return value.strip() or None
        return value

    @property
    def openai_base_url_effective(self) -> str:
        return self.openai_base_url or DEFAULT_OPENAI_BASE_URL

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def adzuna_configured(self) -> bool:
        return bool(self.adzuna_app_id and self.adzuna_app_key)

    @property
    def jsearch_configured(self) -> bool:
        return bool(self.jsearch_api_key)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.database_url.startswith("sqlite:///"):
        db_path = Path(settings.database_url.replace("sqlite:///", "", 1))
        db_path.parent.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
