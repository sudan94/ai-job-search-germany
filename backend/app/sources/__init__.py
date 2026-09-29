"""Source registry - the pipeline's only view of where jobs come from."""

from __future__ import annotations

from app.settings_store import UserSettings
from app.sources.adzuna import AdzunaSource
from app.sources.arbeitnow import ArbeitnowSource
from app.sources.arbeitsagentur import ArbeitsagenturSource
from app.sources.ats_ashby import AshbySource
from app.sources.ats_greenhouse import GreenhouseSource
from app.sources.ats_lever import LeverSource
from app.sources.base import JobSource, RawJob, SourceError
from app.sources.jsearch import JSearchSource

SOURCE_CLASSES: tuple[type[JobSource], ...] = (
    ArbeitnowSource,
    ArbeitsagenturSource,
    AdzunaSource,
    GreenhouseSource,
    LeverSource,
    AshbySource,
    JSearchSource,
)

SOURCES_BY_NAME: dict[str, type[JobSource]] = {cls.name: cls for cls in SOURCE_CLASSES}


def build_sources(config: UserSettings) -> list[JobSource]:
    """Instantiate every source the user has switched on and that can actually run."""
    active: list[JobSource] = []
    for cls in SOURCE_CLASSES:
        if not config.sources.get(cls.name, False):
            continue
        source = cls(config)
        if source.requires_config and not source.is_configured():
            continue
        active.append(source)
    return active


def describe_sources(config: UserSettings) -> list[dict]:
    """Metadata for the settings page: what exists, what is on, what is missing keys."""
    return [
        {
            "name": cls.name,
            "label": cls.label,
            "enabled": bool(config.sources.get(cls.name, False)),
            "configured": cls(config).is_configured(),
            "requires_config": cls.requires_config,
        }
        for cls in SOURCE_CLASSES
    ]


__all__ = [
    "JobSource",
    "RawJob",
    "SourceError",
    "SOURCES_BY_NAME",
    "build_sources",
    "describe_sources",
]
