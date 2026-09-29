"""Greenhouse job boards - public JSON per company, no key.

`?content=true` returns the full posting body in one call, so a tracked company
costs exactly one request per run.
"""

from __future__ import annotations

import html
import logging
from datetime import datetime

import httpx

from app.sources.arbeitnow import html_to_text
from app.sources.base import JobSource, RawJob, SourceError

logger = logging.getLogger(__name__)

BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"

REMOTE_HINTS = ("remote", "anywhere", "home office", "homeoffice", "worldwide")
EU_HINTS = (
    "german", "deutschland", "berlin", "münchen", "munich", "hamburg", "köln",
    "cologne", "frankfurt", "stuttgart", "düsseldorf", "leipzig", "europe", "emea",
    "eu", "netherlands", "amsterdam", "austria", "vienna", "spain", "madrid",
    "barcelona", "portugal", "lisbon", "ireland", "dublin", "poland", "warsaw",
    "france", "paris", "italy", "milan", "sweden", "stockholm", "denmark",
    "copenhagen", "belgium", "brussels", "czech", "prague",
)


def geo_ok(location: str, remote: bool) -> bool:
    """Keep Germany and remote-EU; drop postings anchored to another continent.

    A remote job still names a country most of the time ("Remote, Brasil"), and
    those are not applicable from Germany, so remote alone is not a free pass.
    """
    place = (location or "").strip().lower()
    if not place:
        return True
    if any(hint in place for hint in EU_HINTS):
        return True
    stripped = place.replace("-", " ").replace(",", " ").replace("/", " ")
    words = {w for w in stripped.split() if w}
    if remote and words <= set(REMOTE_HINTS) | {"global", "flexible", "office", "home"}:
        return True  # "Remote" with no country attached
    return False


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GreenhouseSource(JobSource):
    name = "greenhouse"
    label = "Greenhouse (tracked companies)"
    requires_config = True
    #: A board only lists jobs that are still open.
    listings_are_current = True

    def is_configured(self) -> bool:
        return bool(self.config.active_ats("greenhouse"))

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        companies = self.config.active_ats("greenhouse")
        if not companies:
            raise SourceError("no active Greenhouse companies configured")

        keywords = [k.lower() for k in self.config.keywords]
        jobs: list[RawJob] = []
        errors: list[str] = []

        for company in companies:
            try:
                payload = self._get_json(client, BOARD_URL.format(slug=company.slug))
            except httpx.HTTPError as exc:
                errors.append(f"{company.slug}: {exc}")
                continue

            for entry in (payload or {}).get("jobs", []) or []:
                job = self._to_raw_job(entry, company.label or company.slug)
                if job is None:
                    continue
                if not self._is_relevant(job, keywords):
                    continue
                jobs.append(job)

        if errors and not jobs:
            raise SourceError("; ".join(errors[:3]))
        if errors:
            logger.warning("Greenhouse partial failure: %s", "; ".join(errors[:3]))

        logger.info("Greenhouse: %d jobs from %d boards", len(jobs), len(companies))
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
            token in title
            for kw in keywords
            for token in kw.split()
            if len(token) > 3
        )

    @staticmethod
    def _to_raw_job(entry: dict, company: str) -> RawJob | None:
        title = (entry.get("title") or "").strip()
        if not title:
            return None
        location = ((entry.get("location") or {}).get("name") or "").strip()
        content = html_to_text(html.unescape(entry.get("content") or ""))
        return RawJob(
            source="greenhouse",
            source_id=str(entry.get("id") or ""),
            title=title,
            company=company,
            location=location,
            remote=any(h in location.lower() for h in REMOTE_HINTS),
            url=entry.get("absolute_url") or "",
            description=content,
            posted_date=_parse_date(entry.get("updated_at") or entry.get("first_published")),
            raw={k: v for k, v in entry.items() if k != "content"},
        )
