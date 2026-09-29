"""User settings: validated by Pydantic, stored as one JSON row, edited in the UI."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting
from app.pipeline.relevance import (
    DEFAULT_EXCLUDE_TITLE_TERMS,
    DEFAULT_INCLUDE_TITLE_TERMS,
    RelevanceRules,
    build_rules,
)

#: Junior Python, AI, and junior-to-mid PHP.  English titles carry the
#: international boards; the German ones are what the Bundesagentur index
#: actually contains.  Order matters a little: the Bundesagentur adapter walks
#: keywords until it has enough results, so the most wanted titles come first.
DEFAULT_KEYWORDS = [
    "junior python developer",
    "python developer",
    "junior ai engineer",
    "ai engineer",
    "machine learning engineer",
    "junior php developer",
    "php developer",
    "laravel developer",
    "junior python entwickler",
    "python entwickler",
    "php entwickler",
    "junior softwareentwickler",
]

DEFAULT_LOCATIONS = ["Berlin", "München", "Hamburg", "Köln", "Frankfurt am Main"]

#: Boards verified to respond; add your own, the slug is the ATS board name in
#: the careers URL (boards.greenhouse.io/<slug>, jobs.lever.co/<slug>,
#: jobs.ashbyhq.com/<slug>).
DEFAULT_ATS_COMPANIES: list[dict[str, str]] = [
    {"ats": "greenhouse", "slug": "n26", "label": "N26"},
    {"ats": "greenhouse", "slug": "hellofresh", "label": "HelloFresh"},
    {"ats": "greenhouse", "slug": "celonis", "label": "Celonis"},
    {"ats": "greenhouse", "slug": "sumup", "label": "SumUp"},
    {"ats": "greenhouse", "slug": "getyourguide", "label": "GetYourGuide"},
    {"ats": "greenhouse", "slug": "gitlab", "label": "GitLab"},
    {"ats": "greenhouse", "slug": "elastic", "label": "Elastic"},
    {"ats": "greenhouse", "slug": "contentful", "label": "Contentful"},
    {"ats": "lever", "slug": "spotify", "label": "Spotify"},
    {"ats": "lever", "slug": "swile", "label": "Swile"},
    # German companies on Ashby, all verified to return postings.
    {"ats": "ashby", "slug": "deepl", "label": "DeepL"},
    {"ats": "ashby", "slug": "enpal", "label": "Enpal"},
    {"ats": "ashby", "slug": "tacto", "label": "Tacto"},
    {"ats": "ashby", "slug": "langfuse", "label": "Langfuse"},
    {"ats": "ashby", "slug": "flip", "label": "Flip"},
    {"ats": "ashby", "slug": "cargo-one", "label": "cargo.one"},
]


class ATSCompany(BaseModel):
    ats: str = Field(description="greenhouse | lever")
    slug: str = Field(description="board identifier used in the ATS URL")
    label: str = ""
    active: bool = True


class UserSettings(BaseModel):
    """Everything editable from the dashboard."""

    # Filtering
    english_only: bool = True
    #: Keep Germany-based roles, plus remote roles at German employers.
    germany_only: bool = True
    #: The pass mark.  A scored job at or above it is a match.
    min_score: int = Field(default=65, ge=0, le=100)
    #: With this on, a job scored under `min_score` is marked system_rejected.
    #: Off, it stays `new` and is only hidden by the Jobs page's matches filter.
    auto_reject_below_min_score: bool = True
    #: Whether the Jobs page opens filtered to matches (score >= min_score).
    jobs_matches_only_default: bool = True
    #: Optional hard floor on cosine similarity. Off by default because the
    #: meaningful range differs per embedding backend (OpenAI vs the built-in
    #: lexical one); the real prefilter is the title filter and top-N ranking.
    similarity_floor: float = Field(default=0.0, ge=0.0, le=1.0)

    #: Title filter: drop postings that are the wrong seniority, discipline or
    #: stack before anything is billed. This is what keeps hardware and senior
    #: Java roles out of the list.
    relevance_filter: bool = True
    include_title_terms: list[str] = Field(
        default_factory=lambda: list(DEFAULT_INCLUDE_TITLE_TERMS)
    )
    exclude_title_terms: list[str] = Field(
        default_factory=lambda: list(DEFAULT_EXCLUDE_TITLE_TERMS)
    )

    #: How many jobs above the threshold a run aims for. It scores best-match
    #: first and stops once it has this many, so a good day costs less than a
    #: thin one. 0 means "no target: keep going until the ceiling".
    target_matches_per_run: int = Field(default=20, ge=0, le=200)
    #: Hard ceiling on scoring calls, whether or not the target was reached.
    max_llm_scores_per_run: int = Field(default=60, ge=0, le=1000)

    # Search
    keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_KEYWORDS))
    locations: list[str] = Field(default_factory=lambda: list(DEFAULT_LOCATIONS))
    remote_only: bool = False
    radius_km: int = Field(default=30, ge=0, le=200)
    max_age_days: int = Field(default=7, ge=1, le=100)
    results_per_source: int = Field(default=100, ge=1, le=500)

    # Sources
    sources: dict[str, bool] = Field(
        default_factory=lambda: {
            "arbeitnow": True,
            "arbeitsagentur": True,
            "adzuna": False,
            "greenhouse": True,
            "lever": True,
            "ashby": True,
            "jsearch": False,
        }
    )
    ats_companies: list[ATSCompany] = Field(
        default_factory=lambda: [ATSCompany(**c) for c in DEFAULT_ATS_COMPANIES]
    )

    #: JSearch reads Google for Jobs, which lists Indeed and StepStone postings.
    #: Keep only these publishers (case-insensitive substring); empty keeps all.
    jsearch_publishers: list[str] = Field(
        default_factory=lambda: ["Indeed", "StepStone", "LinkedIn", "Xing", "Glassdoor"]
    )
    #: The free tier is 200 requests a month, so a daily run spends at most this many.
    jsearch_max_requests: int = Field(default=5, ge=1, le=50)

    # Scheduling
    daily_run_time: str = Field(default="09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    scheduler_enabled: bool = True

    @field_validator(
        "keywords",
        "locations",
        "include_title_terms",
        "exclude_title_terms",
        "jsearch_publishers",
        mode="before",
    )
    @classmethod
    def _clean_list(cls, value):
        if isinstance(value, str):
            value = [part for part in value.split(",")]
        if isinstance(value, list):
            return [str(v).strip() for v in value if str(v).strip()]
        return value

    @property
    def run_hour_minute(self) -> tuple[int, int]:
        hour, minute = self.daily_run_time.split(":")
        return int(hour), int(minute)

    def active_ats(self, ats: str) -> list[ATSCompany]:
        return [c for c in self.ats_companies if c.active and c.ats == ats]

    def relevance_rules(self) -> RelevanceRules:
        return build_rules(self.include_title_terms, self.exclude_title_terms)


def _row(db: Session) -> AppSetting | None:
    return db.execute(select(AppSetting).limit(1)).scalar_one_or_none()


def get_settings(db: Session) -> UserSettings:
    row = _row(db)
    if row is None:
        return UserSettings()
    try:
        return UserSettings.model_validate(json.loads(row.data or "{}"))
    except Exception:
        # A malformed blob should never brick the app; fall back to defaults.
        return UserSettings()


def save_settings(db: Session, values: UserSettings) -> UserSettings:
    row = _row(db)
    payload = values.model_dump_json()
    if row is None:
        row = AppSetting(data=payload)
        db.add(row)
    else:
        row.data = payload
    db.commit()
    return values


def update_settings(db: Session, patch: dict) -> UserSettings:
    current = get_settings(db).model_dump()
    current.update({k: v for k, v in patch.items() if v is not None})
    return save_settings(db, UserSettings.model_validate(current))


def ensure_settings(db: Session) -> UserSettings:
    if _row(db) is None:
        return save_settings(db, UserSettings())
    return get_settings(db)
