"""Ashby job boards - public JSON per company, no key.

One request per tracked company returns every posting with its full body in
`descriptionPlain`, so there is no second call for details.  Ashby also carries
a structured `address.postalAddress.addressCountry`, which is a far better
Germany signal than parsing the free-text location.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.sources.ats_greenhouse import geo_ok
from app.sources.base import JobSource, RawJob, SourceError

logger = logging.getLogger(__name__)

BOARD_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _country(entry: dict) -> str:
    address = entry.get("address") or {}
    postal = address.get("postalAddress") or {}
    return str(postal.get("addressCountry") or "")


class AshbySource(JobSource):
    name = "ashby"
    label = "Ashby (tracked companies)"
    requires_config = True
    #: A board only lists jobs that are still open.
    listings_are_current = True

    def is_configured(self) -> bool:
        return bool(self.config.active_ats("ashby"))

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        companies = self.config.active_ats("ashby")
        if not companies:
            raise SourceError("no active Ashby companies configured")

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
                if self.config.remote_only and not job.remote:
                    continue
                if not geo_ok(job.location, job.remote):
                    continue
                jobs.append(job)

        if errors and not jobs:
            raise SourceError("; ".join(errors[:3]))
        if errors:
            logger.warning("Ashby partial failure: %s", "; ".join(errors[:3]))

        logger.info("Ashby: %d jobs from %d boards", len(jobs), len(companies))
        return jobs

    @staticmethod
    def _to_raw_job(entry: dict, company: str) -> RawJob | None:
        title = (entry.get("title") or "").strip()
        if not title or entry.get("isListed") is False:
            return None

        # The country is authoritative when Ashby supplies it; the free-text
        # location is often just a city, which the geo filter has to guess at.
        location = (entry.get("location") or "").strip()
        country = _country(entry)
        if country and country.lower() not in location.lower():
            location = f"{location}, {country}".strip(", ")

        return RawJob(
            source="ashby",
            source_id=str(entry.get("id") or ""),
            title=title,
            company=company,
            location=location,
            remote=bool(entry.get("isRemote")),
            url=entry.get("jobUrl") or entry.get("applyUrl") or "",
            description=entry.get("descriptionPlain") or "",
            posted_date=_parse_date(entry.get("publishedAt")),
            raw={k: v for k, v in entry.items() if not k.startswith("description")},
        )
