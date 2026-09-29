"""The one interface every source implements.

A source knows how to talk to exactly one API and hand back `RawJob`s.  The
pipeline never learns where a job came from beyond the `source` string, so
adding a board or another ATS is a new file here plus one registry entry.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.settings_store import UserSettings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RawJob:
    """A posting as the source describes it, before normalization."""

    source: str
    source_id: str | None
    title: str
    company: str = ""
    location: str = ""
    remote: bool = False
    url: str = ""
    description: str = ""
    posted_date: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class SourceError(RuntimeError):
    """Raised when a source fails in a way the run should log but survive."""


class JobSource(ABC):
    #: stable key, also the value stored in `job.source` and in settings.sources
    name: str = "base"
    #: human-readable, shown in the dashboard
    label: str = "Base"
    #: False when the source needs credentials that are not configured
    requires_config: bool = False
    #: True when the API only ever returns postings that are still open, so the
    #: max-age cutoff must not apply.  An ATS board is the case that matters: it
    #: reports when a job was *published*, and a role published six weeks ago
    #: and still listed is still open.  On an aggregator the same date usually
    #: means the posting is stale, which is what the cutoff is for.
    listings_are_current: bool = False

    def __init__(self, config: UserSettings) -> None:
        self.config = config

    def is_configured(self) -> bool:
        return True

    @abstractmethod
    def fetch(self, client: httpx.Client) -> list[RawJob]:
        """Return everything this source has for the current settings."""

    # -- helpers shared by the adapters -------------------------------------

    def _get_json(self, client: httpx.Client, url: str, **kwargs) -> dict | list:
        response = client.get(url, **kwargs)
        response.raise_for_status()
        return response.json()

    @staticmethod
    def build_client() -> httpx.Client:
        return httpx.Client(
            timeout=settings.http_timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent, "Accept": "application/json"},
        )
