"""Adzuna aggregator - free tier, needs app_id/app_key from developer.adzuna.com."""

from __future__ import annotations

import logging
import time
from datetime import datetime

import httpx

from app.config import settings
from app.sources.base import JobSource, RawJob, SourceError

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.adzuna.com/v1/api/jobs/de/search/{page}"
PAGE_SIZE = 50
#: The free tier is generous but not unlimited - stay polite between calls.
DELAY_SECONDS = 0.4


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class AdzunaSource(JobSource):
    name = "adzuna"
    label = "Adzuna"
    requires_config = True

    def is_configured(self) -> bool:
        return settings.adzuna_configured

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        if not self.is_configured():
            raise SourceError("ADZUNA_APP_ID / ADZUNA_APP_KEY are not set")

        wanted = self.config.results_per_source
        seen: dict[str, RawJob] = {}
        errors: list[str] = []

        for keyword in self.config.keywords or [""]:
            if len(seen) >= wanted:
                break
            params: dict[str, object] = {
                "app_id": settings.adzuna_app_id,
                "app_key": settings.adzuna_app_key,
                "results_per_page": PAGE_SIZE,
                "what": keyword,
                "max_days_old": self.config.max_age_days,
                "content-type": "application/json",
            }
            if self.config.locations and not self.config.remote_only:
                params["where"] = self.config.locations[0]
                params["distance"] = self.config.radius_km

            try:
                payload = self._get_json(client, SEARCH_URL.format(page=1), params=params)
            except httpx.HTTPError as exc:
                errors.append(f"'{keyword}': {exc}")
                continue
            finally:
                time.sleep(DELAY_SECONDS)

            for entry in (payload or {}).get("results", []) or []:
                job = self._to_raw_job(entry)
                if job is None or job.source_id in seen:
                    continue
                if self.config.remote_only and not job.remote:
                    continue
                seen[job.source_id] = job
                if len(seen) >= wanted:
                    break

        if errors and not seen:
            raise SourceError("; ".join(errors[:3]))

        logger.info("Adzuna: %d jobs", len(seen))
        return list(seen.values())

    @staticmethod
    def _to_raw_job(entry: dict) -> RawJob | None:
        title = (entry.get("title") or "").strip()
        if not title:
            return None
        description = entry.get("description") or ""
        location = (entry.get("location") or {}).get("display_name") or ""
        haystack = f"{title} {description} {location}".lower()
        return RawJob(
            source="adzuna",
            source_id=str(entry.get("id") or ""),
            title=title,
            company=((entry.get("company") or {}).get("display_name") or "").strip(),
            location=location,
            remote=any(w in haystack for w in ("remote", "home office", "homeoffice")),
            url=entry.get("redirect_url") or "",
            description=description.strip(),
            posted_date=_parse_date(entry.get("created")),
            raw=entry,
        )
