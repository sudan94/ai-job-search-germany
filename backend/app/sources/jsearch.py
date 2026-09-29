"""JSearch - Google for Jobs results, which is where Indeed and StepStone postings
can be reached without scraping either site.

Indeed retired its Publisher API in 2023 and StepStone never had a public one;
both block scrapers.  Google for Jobs indexes their postings, and JSearch
(RapidAPI, free tier of 200 requests a month) exposes that index.  Each result
names its `job_publisher`, so the run can keep only the boards you want.

The response is read defensively: every field is optional.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.sources.base import JobSource, RawJob, SourceError

logger = logging.getLogger(__name__)

DELAY_SECONDS = 0.5

#: JSearch's own buckets; the closest one at or above `max_age_days` is used.
_DATE_BUCKETS = ((1, "today"), (3, "3days"), (7, "week"), (31, "month"))


def _date_posted(max_age_days: int) -> str:
    for days, bucket in _DATE_BUCKETS:
        if max_age_days <= days:
            return bucket
    return "all"


def _parse_date(entry: dict) -> datetime | None:
    value = entry.get("job_posted_at_datetime_utc")
    if value:
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            pass
    timestamp = entry.get("job_posted_at_timestamp")
    if isinstance(timestamp, (int, float)) and timestamp > 0:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    return None


def _publisher_link(entry: dict, publisher: str) -> str:
    """The apply link on the publisher's own site, when JSearch lists it."""
    for option in entry.get("apply_options") or entry.get("job_apply_options") or []:
        if not isinstance(option, dict):
            continue
        if publisher and publisher.lower() in str(option.get("publisher", "")).lower():
            return option.get("apply_link") or ""
    return ""


def _endpoint() -> tuple[str, dict[str, str]]:
    """JSearch is sold two ways, with the same results behind different doors:
    directly by OpenWeb Ninja, and through RapidAPI."""
    host = settings.jsearch_api_host.strip().rstrip("/")
    key = settings.jsearch_api_key or ""
    if "rapidapi" in host:
        return f"https://{host}/search", {"X-RapidAPI-Key": key, "X-RapidAPI-Host": host}
    return f"https://{host}/jsearch/search", {"X-API-Key": key}


def _results(payload) -> list:
    """`/search` puts the jobs in `data`; `/search-v2` in `data.jobs`."""
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        data = data.get("jobs")
    return data if isinstance(data, list) else []


class JSearchSource(JobSource):
    name = "jsearch"
    label = "Indeed, StepStone & more (Google Jobs via JSearch)"
    requires_config = True

    def is_configured(self) -> bool:
        return settings.jsearch_configured

    def _queries(self) -> list[str]:
        keywords = self.config.keywords or ["software developer"]
        if self.config.remote_only or not self.config.locations:
            return [f"{keyword} in Germany" for keyword in keywords]
        # Pair keywords with locations round-robin so a small request budget
        # still covers more than one city.
        locations = self.config.locations
        return [
            f"{keyword} in {locations[index % len(locations)]}, Germany"
            for index, keyword in enumerate(keywords)
        ]

    def _wanted_publisher(self, publisher: str) -> bool:
        wanted = [p.lower() for p in self.config.jsearch_publishers]
        if not wanted:
            return True
        publisher = publisher.lower()
        return any(name in publisher for name in wanted)

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        if not self.is_configured():
            raise SourceError("JSEARCH_API_KEY is not set")

        url, headers = _endpoint()
        wanted = self.config.results_per_source
        seen: dict[str, RawJob] = {}
        errors: list[str] = []
        skipped_publishers: dict[str, int] = {}

        for query in self._queries()[: self.config.jsearch_max_requests]:
            if len(seen) >= wanted:
                break
            params = {
                "query": query,
                "page": 1,
                "num_pages": 1,
                "country": "de",
                "date_posted": _date_posted(self.config.max_age_days),
            }
            if self.config.remote_only:
                params["work_from_home"] = "true"
            try:
                payload = self._get_json(client, url, params=params, headers=headers)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status in (401, 403):
                    raise SourceError(f"JSearch rejected the API key (HTTP {status})") from exc
                if status == 429:
                    errors.append("monthly or rate limit reached (HTTP 429)")
                    break
                errors.append(f"'{query}': HTTP {status}")
                continue
            except httpx.HTTPError as exc:
                errors.append(f"'{query}': {exc}")
                continue
            finally:
                time.sleep(DELAY_SECONDS)

            for entry in _results(payload):
                if not isinstance(entry, dict):
                    continue
                publisher = str(entry.get("job_publisher") or "")
                if not self._wanted_publisher(publisher):
                    skipped_publishers[publisher] = skipped_publishers.get(publisher, 0) + 1
                    continue
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
        if skipped_publishers:
            logger.info("JSearch: skipped publishers %s", skipped_publishers)
        logger.info("JSearch: %d jobs", len(seen))
        return list(seen.values())

    @staticmethod
    def _to_raw_job(entry: dict) -> RawJob | None:
        title = str(entry.get("job_title") or "").strip()
        job_id = str(entry.get("job_id") or "").strip()
        if not title or not job_id:
            return None
        publisher = str(entry.get("job_publisher") or "").strip()
        city = str(entry.get("job_city") or "").strip()
        state = str(entry.get("job_state") or "").strip()
        country = str(entry.get("job_country") or "").strip()
        location = str(entry.get("job_location") or "").strip() or ", ".join(
            part for part in (city, state, "Germany" if country.upper() == "DE" else country) if part
        )
        remote = bool(entry.get("job_is_remote"))
        raw = dict(entry)
        raw["publisher"] = publisher
        return RawJob(
            source="jsearch",
            source_id=job_id,
            title=title,
            company=str(entry.get("employer_name") or "").strip(),
            location=location,
            remote=remote,
            url=_publisher_link(entry, publisher) or entry.get("job_apply_link") or "",
            description=str(entry.get("job_description") or "").strip(),
            posted_date=_parse_date(entry),
            raw=raw,
        )
