"""Bundesagentur für Arbeit Jobsuche API - the biggest German job database.

Free and keyless in practice: the public app key `jobboerse-jobsuche` goes in
the `X-API-Key` header.

Endpoint note: search lives at `pc/v6/jobs` (the older `pc/v4/app/jobs` from the
brief now 404s and v6 renamed most result fields), while job details are still
served by `pc/v4/jobdetails/{base64(referenznummer)}`.  Both shapes are read
defensively below so an older or newer response still parses.
"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone

import httpx

from app.sources.arbeitnow import html_to_text
from app.sources.base import JobSource, RawJob, SourceError

logger = logging.getLogger(__name__)

BASE = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc"
SEARCH_URL = f"{BASE}/v6/jobs"
DETAIL_URL = f"{BASE}/v4/jobdetails"
API_KEY = "jobboerse-jobsuche"
PAGE_SIZE = 50
MAX_PAGES = 4


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _first(entry: dict, *names: str, default=None):
    for name in names:
        value = entry.get(name)
        if value not in (None, ""):
            return value
    return default


class ArbeitsagenturSource(JobSource):
    name = "arbeitsagentur"
    label = "Bundesagentur für Arbeit"

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        headers = {"X-API-Key": API_KEY}
        wanted = self.config.results_per_source
        seen: dict[str, RawJob] = {}
        errors: list[str] = []

        # No location means "anywhere in Germany"; remote-only ignores the radius.
        locations: list[str | None] = (
            [None]
            if (self.config.remote_only or not self.config.locations)
            else list(self.config.locations)
        )

        for keyword in self.config.keywords or [""]:
            for location in locations:
                if len(seen) >= wanted:
                    break
                errors.extend(self._search(client, headers, keyword, location, seen, wanted))

        jobs = list(seen.values())

        # Second pass: the search result carries no body text, so pull details.
        for job in jobs:
            try:
                self._enrich(client, job, headers)
            except httpx.HTTPError as exc:
                logger.debug("Detail fetch failed for %s: %s", job.source_id, exc)

        if errors and not jobs:
            raise SourceError("; ".join(errors[:3]))
        if errors:
            logger.warning("Arbeitsagentur partial failure: %s", "; ".join(errors[:3]))

        logger.info("Arbeitsagentur: %d jobs", len(jobs))
        return jobs

    def _search(
        self,
        client: httpx.Client,
        headers: dict,
        keyword: str,
        location: str | None,
        seen: dict[str, RawJob],
        wanted: int,
    ) -> list[str]:
        errors: list[str] = []
        for page in range(1, MAX_PAGES + 1):
            if len(seen) >= wanted:
                break
            params: dict[str, object] = {
                "was": keyword,
                "page": page,
                "size": PAGE_SIZE,
                "veroeffentlichtseit": self.config.max_age_days,
                "angebotsart": 1,  # ARBEIT: regular employment, not training
            }
            if location:
                params["wo"] = location
                params["umkreis"] = self.config.radius_km
            if self.config.remote_only:
                params["arbeitszeit"] = "ho"

            try:
                payload = self._get_json(client, SEARCH_URL, params=params, headers=headers)
            except httpx.HTTPError as exc:
                errors.append(f"search '{keyword}' @ {location or 'DE'}: {exc}")
                break

            if not isinstance(payload, dict):
                break
            entries = payload.get("ergebnisliste") or payload.get("stellenangebote") or []
            if not entries:
                break

            for entry in entries:
                refnr = _first(entry, "referenznummer", "refnr")
                if not refnr or refnr in seen:
                    continue
                seen[refnr] = self._to_raw_job(entry, refnr)
                if len(seen) >= wanted:
                    break

            if len(entries) < PAGE_SIZE:
                break
        return errors

    @staticmethod
    def _to_raw_job(entry: dict, refnr: str) -> RawJob:
        locations = entry.get("stellenlokationen") or []
        address = (locations[0].get("adresse") if locations else None) or entry.get("arbeitsort") or {}
        location = ", ".join(
            part for part in (address.get("ort"), address.get("region")) if part
        )
        return RawJob(
            source="arbeitsagentur",
            source_id=refnr,
            title=str(_first(entry, "stellenangebotsTitel", "titel", "beruf", default="")).strip(),
            company=str(_first(entry, "firma", "arbeitgeber", default="")).strip(),
            location=location,
            remote=bool(entry.get("homeofficemoeglich")),
            url=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{refnr}",
            description="",
            posted_date=_parse_date(
                _first(entry, "datumErsteVeroeffentlichung", "aktuelleVeroeffentlichungsdatum")
            ),
            raw=entry,
        )

    def _enrich(self, client: httpx.Client, job: RawJob, headers: dict) -> None:
        encoded = base64.b64encode((job.source_id or "").encode()).decode()
        detail = self._get_json(client, f"{DETAIL_URL}/{encoded}", headers=headers)
        if not isinstance(detail, dict):
            return

        body = str(
            _first(detail, "stellenangebotsBeschreibung", "stellenbeschreibung", default="")
        )
        employer = str(detail.get("arbeitgeberdarstellung") or "")
        text = "\n\n".join(part for part in (body, employer) if part)
        job.description = html_to_text(text) if "<" in text else text.strip()

        job.raw = {**job.raw, "detail": detail}
        if not job.company:
            job.company = str(_first(detail, "firma", "arbeitgeber", default="")).strip()
        if detail.get("homeofficemoeglich"):
            job.remote = True
        external = detail.get("allianzpartnerUrl") or detail.get("externeUrl")
        if external:
            job.raw["external_url"] = external
