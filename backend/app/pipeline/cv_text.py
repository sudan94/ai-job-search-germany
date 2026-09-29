"""Shared rendering of the stored CV profile into prompt text."""

from __future__ import annotations

import json
from typing import Any

from app.models import CVProfile


def _load_list(value: str | None) -> list[Any]:
    try:
        loaded = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def cv_summary_for_prompt(profile: CVProfile) -> str:
    """The structured profile as prompt text: every section the parser found."""
    if profile is None:
        return "No CV on file."

    skills = _load_list(profile.skills)
    targets = _load_list(profile.role_targets)
    languages = _load_list(profile.languages)
    experience = _load_list(profile.experience)
    education = _load_list(profile.education)
    projects = _load_list(profile.projects)
    certifications = _load_list(profile.certifications)

    parts: list[str] = []
    if profile.summary:
        parts.append(f"Summary: {profile.summary}")
    if profile.years_experience is not None:
        parts.append(f"Years of professional experience: {profile.years_experience}")
    if targets:
        parts.append("Target roles: " + ", ".join(str(t) for t in targets))
    if skills:
        parts.append("Skills: " + ", ".join(str(s) for s in skills[:60]))
    if languages:
        parts.append("Languages: " + ", ".join(str(item) for item in languages))

    if experience:
        lines = ["Experience:"]
        for item in experience[:15]:
            if isinstance(item, dict):
                header = " | ".join(
                    str(item.get(k, "")).strip()
                    for k in ("title", "company", "period")
                    if item.get(k)
                )
                lines.append(f"- {header}")
                for highlight in (item.get("highlights") or [])[:4]:
                    lines.append(f"    * {highlight}")
            else:
                lines.append(f"- {item}")
        parts.append("\n".join(lines))

    if education:
        lines = ["Education:"]
        for item in education[:8]:
            if isinstance(item, dict):
                fields = ("degree", "institution", "period", "details")
                lines.append("- " + " | ".join(str(item[k]).strip() for k in fields if item.get(k)))
        parts.append("\n".join(lines))

    if projects:
        lines = ["Projects:"]
        for item in projects[:10]:
            if isinstance(item, dict):
                line = f"- {item.get('name', '')}: {item.get('description', '')}"
                tech = ", ".join(str(t) for t in item.get("technologies") or [])
                lines.append(f"{line} [{tech}]" if tech else line)
        parts.append("\n".join(lines))

    if certifications:
        parts.append("Certifications: " + ", ".join(str(c) for c in certifications))

    return "\n".join(parts) if parts else (profile.raw_text or "No CV on file.")[:4000]
