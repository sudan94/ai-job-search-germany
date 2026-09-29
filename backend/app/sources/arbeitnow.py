"""Arbeitnow job board API - free, no key, English-friendly tech jobs in DE/EU."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx

from app.sources.base import JobSource, RawJob, SourceError

logger = logging.getLogger(__name__)

API_URL = "https://www.arbeitnow.com/api/job-board-api"
MAX_PAGES = 5

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n{3,}")


def html_to_text(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html or "", flags=re.I)
    text = re.sub(r"</(p|div|li|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    text = (
        text.replace("&amp;", "&")
        .replace("&nbsp;", " ")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#039;", "'")
    )
    return _WS_RE.sub("\n\n", text).strip()


class ArbeitnowSource(JobSource):
    name = "arbeitnow"
    label = "Arbeitnow"

    def fetch(self, client: httpx.Client) -> list[RawJob]:
        wanted = self.config.results_per_source
        keywords = [k.lower() for k in self.config.keywords]
        jobs: list[RawJob] = []
        page = 1

        while page <= MAX_PAGES and len(jobs) < wanted:
            try:
                payload = self._get_json(client, API_URL, params={"page": page})
            except httpx.HTTPError as exc:
                raise SourceError(f"Arbeitnow page {page} failed: {exc}") from exc

            if not isinstance(payload, dict):
                raise SourceError("Arbeitnow returned an unexpected payload")

            entries = payload.get("data") or []
            if not entries:
                break

            for entry in entries:
                job = self._to_raw_job(entry)
                if job is None:
                    continue
                if keywords and not self._matches_keywords(job, keywords):
                    continue
                if self.config.remote_only and not job.remote:
                    continue
                jobs.append(job)
                if len(jobs) >= wanted:
                    break

            if not (payload.get("links") or {}).get("next"):
                break
            page += 1

        logger.info("Arbeitnow: %d jobs after filtering", len(jobs))
        return jobs

    @staticmethod
    def _matches_keywords(job: RawJob, keywords: list[str]) -> bool:
        haystack = f"{job.title} {job.description[:1500]}".lower()
        return any(kw in haystack for kw in keywords) or any(
            token in haystack
            for kw in keywords
            for token in kw.split()
            if len(token) > 4 and token not in {"developer", "engineer"}
        )

    @staticmethod
    def _to_raw_job(entry: dict) -> RawJob | None:
        slug = entry.get("slug")
        title = (entry.get("title") or "").strip()
        if not title:
            return None

        created = entry.get("created_at")
        posted = None
        if isinstance(created, (int, float)):
            posted = datetime.fromtimestamp(created, tz=timezone.utc)

        return RawJob(
            source="arbeitnow",
            source_id=slug,
            title=title,
            company=(entry.get("company_name") or "").strip(),
            location=(entry.get("location") or "").strip(),
            remote=bool(entry.get("remote")),
            url=entry.get("url") or "",
            description=html_to_text(entry.get("description") or ""),
            posted_date=posted,
            raw=entry,
        )
