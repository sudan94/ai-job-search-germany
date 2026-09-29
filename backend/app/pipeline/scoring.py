"""Two-stage score: a cheap similarity prefilter, then a real rubric.

Stage one ranks every new posting against the CV by cosine similarity. Stage
two sends only the top candidates to the chat model for a rubric score, which is what
keeps a daily run affordable: the expensive model never sees the long tail.
"""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel, Field, field_validator

from app.llm import cosine_similarity, embedder, llm, truncate
from app.models import CVProfile
from app.pipeline.cv_text import cv_summary_for_prompt

logger = logging.getLogger(__name__)

#: The embeddings endpoint accepts batches; the lexical backend does not care.
EMBED_BATCH = 32


class ScoreResult(BaseModel):
    score: int = Field(ge=0, le=100)
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    verdict: str = ""

    @field_validator("matched", "missing", mode="before")
    @classmethod
    def _coerce(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        return [str(v) for v in value][:12]

    @field_validator("score", mode="before")
    @classmethod
    def _clamp(cls, value):
        try:
            return max(0, min(100, int(round(float(value)))))
        except (TypeError, ValueError):
            return 0


SYSTEM_PROMPT = """You score how well one candidate fits one job. Be honest, not generous: a score that flatters the candidate wastes their time.

Rubric (0-100):
- Must-have technical requirements dominate the score. Overlap with the candidate's actual stack is worth the most.
- Penalise hard requirements the candidate does not meet: years of experience they do not have, a required degree or certification, mandatory German, a required technology with no evidence in the CV.
- Treat academic and personal-project experience as real but weaker than production experience. Do not credit production experience the CV does not show.
- Seniority mismatch is a hard penalty in both directions: a senior/lead role for a mid-level candidate, or a role far below their level.
- Adjacent-but-learnable technologies are a small penalty, not a disqualifier.

Bands: 85-100 strong fit, apply now. 70-84 good fit with a gap or two. 55-69 plausible but a real stretch. Below 55 not worth the application.

matched and missing must name concrete requirements from the posting, not vague adjectives. Maximum 6 items each. verdict is one line, at most 160 characters."""


def embedding_of(profile: CVProfile) -> list[float] | None:
    if not profile or not profile.embedding:
        return None
    try:
        return json.loads(profile.embedding)
    except json.JSONDecodeError:
        return None


def embedding_backend_of(profile: CVProfile) -> str | None:
    """Which backend produced the stored CV vector.

    Similarities are only meaningful within one backend, so a run compares this
    against the active backend and skips the prefilter rather than ranking on
    numbers that mean nothing.
    """
    if not profile or not profile.embedding_model:
        return None
    return profile.embedding_model.split(":", 1)[0]


def job_embedding_text(title: str, company: str, location: str, description: str) -> str:
    return f"{title}\n{company} - {location}\n\n{description}"


def embed_job_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of postings with the active backend."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        vectors.extend(embedder.embed_documents(texts[start : start + EMBED_BATCH]))
    return vectors


def embed_job_text(title: str, company: str, location: str, description: str) -> list[float]:
    return embed_job_texts([job_embedding_text(title, company, location, description)])[0]


def similarity_against_cv(job_embedding: list[float], cv_embedding: list[float]) -> float:
    return round(cosine_similarity(job_embedding, cv_embedding), 4)


def score_job(
    *,
    profile: CVProfile,
    title: str,
    company: str,
    location: str,
    description: str,
    remote: bool = False,
) -> ScoreResult:
    """Rubric score from the chat model.  Raises if the model is unavailable."""
    user = (
        f"CANDIDATE PROFILE\n{cv_summary_for_prompt(profile)}\n\n"
        f"JOB POSTING\n"
        f"Title: {title}\n"
        f"Company: {company}\n"
        f"Location: {location}{' (remote)' if remote else ''}\n\n"
        f"Description:\n{truncate(description)}"
    )
    # Deterministic: the same posting should not score differently run to run.
    return llm.json_chat(SYSTEM_PROMPT, user, ScoreResult, temperature=0.0, max_tokens=2000)
