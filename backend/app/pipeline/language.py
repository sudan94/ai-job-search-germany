"""Working language, not description language.

A German posting can be an English workplace and an English posting can still
demand fluent German, so detection of the JD is only a signal.  Order of work,
cheapest first:

1. regex for the unambiguous German-required phrases -> decided, no model call
2. regex for explicit English-workplace phrases + English detection -> decided
3. anything still ambiguous goes to the model for a structured judgment
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field, field_validator

from app.llm import llm, truncate

logger = logging.getLogger(__name__)

GERMAN_REQUIRED_PATTERNS = [
    r"verhandlungssicher(?:e|es|em)?\s+deutsch",
    r"deutschkenntnisse\s+(?:sind\s+)?(?:zwingend\s+)?erforderlich",
    r"(?:sehr\s+gute|fließende|fliessende|exzellente|perfekte)\s+deutschkenntnisse",
    r"deutsch\s+(?:in\s+wort\s+und\s+schrift)",
    r"muttersprach(?:e|liche[rs]?)\s+deutsch",
    r"deutsch\s*(?:\(|:|-)?\s*(?:c1|c2)\b",
    r"\b(?:c1|c2)[- ]level\s+german",
    r"fluent\s+(?:in\s+)?german",
    r"business[- ]fluent\s+german",
    r"german\s+(?:language\s+)?(?:skills\s+)?(?:is\s+|are\s+)?(?:required|mandatory|a\s+must)",
    r"native[- ]level\s+german",
    r"good\s+command\s+of\s+german",
    r"sehr\s+gute\s+deutsche?\s+sprachkenntnisse",
]

GERMAN_NICE_TO_HAVE_PATTERNS = [
    r"german\s+(?:is\s+)?(?:a\s+)?plus",
    r"german\s+(?:is\s+)?nice[- ]to[- ]have",
    r"deutschkenntnisse\s+(?:sind\s+)?von\s+vorteil",
    r"deutsch\s+w(?:ü|ue)nschenswert",
    r"grundkenntnisse\s+deutsch",
]

ENGLISH_WORKPLACE_PATTERNS = [
    r"english\s+is\s+our\s+(?:company|working|official)\s+language",
    r"(?:company|working|office|team)\s+language\s+is\s+english",
    r"we\s+work\s+(?:fully\s+)?in\s+english",
    r"english[- ]speaking\s+(?:team|environment|workplace)",
    r"no\s+german\s+(?:language\s+)?(?:skills\s+)?(?:is\s+|are\s+)?(?:required|needed|necessary)",
    r"unternehmenssprache\s+(?:ist\s+)?englisch",
    r"english\s+only\s+environment",
]

_GERMAN_REQUIRED_RE = re.compile("|".join(GERMAN_REQUIRED_PATTERNS), re.IGNORECASE)
_GERMAN_NICE_RE = re.compile("|".join(GERMAN_NICE_TO_HAVE_PATTERNS), re.IGNORECASE)
_ENGLISH_WORKPLACE_RE = re.compile("|".join(ENGLISH_WORKPLACE_PATTERNS), re.IGNORECASE)


class LanguageJudgment(BaseModel):
    """Exactly what the model is asked to return - the structured-output schema."""

    working_language: str = Field(description="english, german, both, or unknown")
    german_required: bool = Field(description="true if fluent German is a hard requirement")
    confidence: float = Field(description="0.0 to 1.0")
    evidence: str = Field(description="the phrase that decided it, max 200 characters")

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp(cls, value):
        try:
            return max(0.0, min(1.0, float(value)))
        except (TypeError, ValueError):
            return 0.5


class LanguageVerdict(BaseModel):
    """The judgment plus how we arrived at it."""

    working_language: str = Field(default="unknown", description="english | german | both | unknown")
    german_required: bool = False
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: str = ""
    detected_language: str | None = None
    source: str = "heuristic"  # heuristic | llm | fallback


SYSTEM_PROMPT = """You judge whether a job can be done by someone who does not speak German.

You are given a job description from the German market. Decide:
- working_language: the language the team actually works in ("english", "german", "both", "unknown")
- german_required: true if fluent/business German is a hard requirement for the role
- confidence: 0.0-1.0, how sure you are
- evidence: the exact phrase from the posting that decided it, max 200 characters

Rules:
- A German-language posting does not by itself mean German is required; many German companies post in German but work in English.
- An English-language posting does not mean German is not required; check for explicit German requirements.
- "Verhandlungssicheres Deutsch", "Deutschkenntnisse erforderlich", "sehr gute Deutschkenntnisse", "fluent German" mean german_required = true.
- "German is a plus", "von Vorteil", "nice to have" mean german_required = false.
- Customer-facing, support, sales and public-sector roles posted in German usually require German; state that in evidence if you rely on it.
- If nothing indicates the working language and the posting is entirely in German, answer working_language "german", german_required true, confidence at most 0.6."""


def detect_language(text: str) -> str | None:
    """langdetect is a signal, never the decision."""
    sample = (text or "").strip()
    if len(sample) < 40:
        return None
    try:
        from langdetect import DetectorFactory, detect

        DetectorFactory.seed = 0
        return detect(sample[:4000])
    except Exception:  # pragma: no cover - detector is best-effort
        return None


def heuristic_verdict(text: str) -> LanguageVerdict | None:
    """Return a verdict only when the text is unambiguous, otherwise None."""
    detected = detect_language(text)

    required = _GERMAN_REQUIRED_RE.search(text or "")
    if required:
        return LanguageVerdict(
            working_language="german",
            german_required=True,
            confidence=0.95,
            evidence=_snippet(text, required),
            detected_language=detected,
            source="heuristic",
        )

    english_workplace = _ENGLISH_WORKPLACE_RE.search(text or "")
    if english_workplace:
        return LanguageVerdict(
            working_language="english",
            german_required=False,
            confidence=0.9,
            evidence=_snippet(text, english_workplace),
            detected_language=detected,
            source="heuristic",
        )

    nice = _GERMAN_NICE_RE.search(text or "")
    if nice and detected == "en":
        return LanguageVerdict(
            working_language="english",
            german_required=False,
            confidence=0.8,
            evidence=_snippet(text, nice),
            detected_language=detected,
            source="heuristic",
        )

    return None


def judge(text: str, *, title: str = "", company: str = "") -> LanguageVerdict:
    """Full judgment: heuristics first, model only for the ambiguous middle."""
    text = text or ""
    verdict = heuristic_verdict(text)
    if verdict is not None:
        return verdict

    detected = detect_language(text)

    if not llm.available:
        # No model: fall back to the detected language, flagged as low confidence
        # so the dashboard shows this was a guess.
        return LanguageVerdict(
            working_language="german" if detected == "de" else "english",
            german_required=detected == "de",
            confidence=0.35,
            evidence="No model available; judged from detected description language only.",
            detected_language=detected,
            source="fallback",
        )

    user = (
        f"Job title: {title}\nCompany: {company}\n"
        f"Detected description language: {detected or 'unknown'}\n\n"
        f"Job description:\n{truncate(text, 8000)}"
    )
    try:
        judgment = llm.json_chat(
            SYSTEM_PROMPT, user, LanguageJudgment, temperature=0.0, max_tokens=1000
        )
        return LanguageVerdict(
            working_language=judgment.working_language,
            german_required=judgment.german_required,
            confidence=judgment.confidence,
            evidence=(judgment.evidence or "")[:300],
            detected_language=detected,
            source="llm",
        )
    except Exception as exc:
        logger.warning("Language judgment failed: %s", exc)
        return LanguageVerdict(
            working_language="german" if detected == "de" else "unknown",
            german_required=detected == "de",
            confidence=0.3,
            evidence=f"Language model call failed ({exc.__class__.__name__}); used detection only.",
            detected_language=detected,
            source="fallback",
        )


def _snippet(text: str, match: re.Match) -> str:
    start = max(0, match.start() - 60)
    end = min(len(text), match.end() + 60)
    return text[start:end].replace("\n", " ").strip()[:300]
