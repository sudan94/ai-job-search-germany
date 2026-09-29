"""RawJob -> Job, with a stable external id.

The id is what makes re-runs cheap: if we have seen it, we do no work at all.
Prefer the source's own id; otherwise hash normalized title+company+location so
the same posting from two boards or two days collapses to one row.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from app.models import Job
from app.sources.base import RawJob

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)

#: Title noise that differs between boards for the same role.
_TITLE_NOISE = re.compile(
    r"\b(m\s*[/|]?\s*w\s*[/|]?\s*d|w\s*[/|]?\s*m\s*[/|]?\s*d|all genders|gn|f\s*[/|]?\s*m\s*[/|]?\s*d)\b",
    re.IGNORECASE,
)


def canonical(text: str) -> str:
    text = _TITLE_NOISE.sub(" ", text or "")
    text = _PUNCT.sub(" ", text.lower())
    return _WS.sub(" ", text).strip()


def make_external_id(raw: RawJob) -> str:
    if raw.source_id:
        return f"{raw.source}:{raw.source_id}"
    fingerprint = "|".join(canonical(p) for p in (raw.title, raw.company, raw.location))
    digest = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
    return f"hash:{digest}"


def content_fingerprint(raw: RawJob) -> str:
    """Source-independent key, used to catch the same job arriving from two boards."""
    fingerprint = "|".join(canonical(p) for p in (raw.title, raw.company))
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_job(raw: RawJob) -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        external_id=make_external_id(raw),
        source=raw.source,
        title=raw.title.strip()[:500],
        company=(raw.company or "").strip()[:250],
        location=(raw.location or "").strip()[:250],
        remote=bool(raw.remote),
        url=(raw.url or "")[:1000],
        description=(raw.description or "").strip(),
        posted_date=_as_utc(raw.posted_date),
        first_seen=now,
        last_seen=now,
        raw_json=json.dumps(raw.raw, ensure_ascii=False, default=str)[:200_000],
    )
