"""Lever job boards - public JSON per company, no key."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from app.sources.arbeitnow import html_to_text
from app.sources.ats_greenhouse import REMOTE_HINTS, geo_ok
from app.sources.base import JobSource, RawJob, SourceError

logger = logging.getLogger(__name__)

BOARD_URL = "https://api.lever.co/v0/postings/{slug}?mode=json"


class LeverSource(JobSource):
    name = "lever"
    label = "Lever (tracked companies)"
    requires_config = True
    #: A board only lists jobs that are still open.
    listings_are_current = True

    def is_configured(self) -> bool:
        return bool(self.config.active_ats("lever"))

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        companies = self.config.active_ats("lever")
        if not companies:
            raise SourceError("no active Lever companies configured")

        keywords = [k.lower() for k in self.config.keywords]
        jobs: list[RawJob] = []
        errors: list[str] = []

        for company in companies:
            try:
                payload = self._get_json(client, BOARD_URL.format(slug=company.slug))
            except httpx.HTTPError as exc:
                errors.append(f"{company.slug}: {exc}")
                continue
            if not isinstance(payload, list):
                continue

            for entry in payload:
                job = self._to_raw_job(entry, company.label or company.slug)
                if job is None or not self._is_relevant(job, keywords):
                    continue
                jobs.append(job)

        if errors and not jobs:
            raise SourceError("; ".join(errors[:3]))
        if errors:
            logger.warning("Lever partial failure: %s", "; ".join(errors[:3]))

        logger.info("Lever: %d jobs from %d boards", len(jobs), len(companies))
        return jobs

    def _is_relevant(self, job: RawJob, keywords: list[str]) -> bool:
        if self.config.remote_only and not job.remote:
            return False
        if not geo_ok(job.location, job.remote):
            return False
        if not keywords:
            return True
        title = job.title.lower()
        return any(kw in title for kw in keywords) or any(
            token in title for kw in keywords for token in kw.split() if len(token) > 3
        )

    @staticmethod
    def _to_raw_job(entry: dict, company: str) -> RawJob | None:
        title = (entry.get("text") or "").strip()
        if not title:
            return None
        categories = entry.get("categories") or {}
        location = (categories.get("location") or "").strip()
        workplace = (entry.get("workplaceType") or "").lower()

        description = entry.get("descriptionPlain") or html_to_text(entry.get("description") or "")
        for section in entry.get("lists") or []:
            heading = section.get("text") or ""
            body = html_to_text(section.get("content") or "")
            description += f"\n\n{heading}\n{body}"

        created = entry.get("createdAt")
        posted = (
            datetime.fromtimestamp(created / 1000, tz=timezone.utc)
            if isinstance(created, (int, float))
            else None
        )

        return RawJob(
            source="lever",
            source_id=str(entry.get("id") or ""),
            title=title,
            company=company,
            location=location,
            remote=workplace == "remote" or any(h in location.lower() for h in REMOTE_HINTS),
            url=entry.get("hostedUrl") or entry.get("applyUrl") or "",
            description=description.strip(),
            posted_date=posted,
            raw={k: v for k, v in entry.items() if k not in {"description", "lists"}},
        )
