"""Parse the CV once into a structured profile plus an embedding.

Re-parsing only happens on upload, so scoring always compares against structure
(skills, years, targets) rather than raw text.
"""

from __future__ import annotations

import io
import json
import logging
import re
from typing import NamedTuple

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.llm import embedder, llm, truncate
from app.models import CVProfile

logger = logging.getLogger(__name__)


class ExperienceItem(BaseModel):
    title: str = Field(default="", description="job title")
    company: str = Field(default="", description="employer, or the course/project context")
    period: str = Field(default="", description="e.g. 2021-2024")
    highlights: list[str] = Field(
        default_factory=list, description="concrete results or projects, not adjectives"
    )


class EducationItem(BaseModel):
    degree: str = Field(default="", description="degree or qualification")
    institution: str = Field(default="", description="university, school or provider")
    period: str = Field(default="", description="e.g. 2019-2023")
    details: str = Field(default="", description="focus, thesis, grade; empty if not stated")


class ProjectItem(BaseModel):
    name: str = ""
    description: str = Field(default="", description="what it does, one or two sentences")
    technologies: list[str] = Field(default_factory=list)


class ParsedCV(BaseModel):
    summary: str = Field(
        default="", description="3-4 factual sentences: current role, main stack, direction"
    )
    skills: list[str] = Field(
        default_factory=list, description="concrete technologies, frameworks and tools"
    )
    role_targets: list[str] = Field(
        default_factory=list, description="job titles this person realistically fits"
    )
    years_experience: float | None = Field(
        default=None, description="years of professional experience, null if not derivable"
    )
    experience: list[ExperienceItem] = Field(
        default_factory=list, description="every position in the CV, newest first"
    )
    education: list[EducationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    languages: list[str] = Field(
        default_factory=list, description='e.g. ["English (C1)", "German (B1)"]'
    )


SYSTEM_PROMPT = """You extract a structured profile from a CV. Report only what the CV states; never invent or upgrade anything.

Rules:
- Read the whole CV, every page, to the end. Include every position, degree, project and certification it lists; do not stop after the first section or summarise several entries into one.
- Mark experience that is academic, from studies or from personal projects as such inside the highlight text. Do not present it as professional experience.
- skills: maximum 40, most relevant first, no soft skills.
- years_experience excludes studies and internships where they are separable. Use null if it is not derivable.
- summary is factual: current role, main stack, direction of travel. No adjectives about the person."""


class ExtractedText(NamedTuple):
    text: str
    #: PDF page count; None for text files.
    pages: int | None


def _pdf_text_pymupdf(content: bytes) -> tuple[list[str], int]:
    """PyMuPDF keeps reading order in multi-column and designed CVs, where
    pypdf often returns only one column or skips text boxes entirely."""
    import fitz  # PyMuPDF

    with fitz.open(stream=content, filetype="pdf") as document:
        pages = [page.get_text("text", sort=True) or "" for page in document]
        return pages, document.page_count


def _pdf_text_pypdf(content: bytes) -> tuple[list[str], int]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if len(text.strip()) < 40:
            # Plain mode misses text in some generated PDFs; layout mode reads it.
            try:
                text = page.extract_text(extraction_mode="layout") or text
            except Exception:  # pragma: no cover - depends on the file
                pass
        pages.append(text)
    return pages, len(reader.pages)


def _pdf_text(content: bytes) -> tuple[str, int]:
    """Try every extractor and keep the one that read the most.

    Neither library is right for every PDF, and reading too little is the
    failure that matters: half a CV silently becomes half a profile.
    """
    best_text, best_pages, errors = "", 0, []
    for extractor in (_pdf_text_pymupdf, _pdf_text_pypdf):
        try:
            pages, count = extractor(content)
        except ImportError:
            continue
        except Exception as exc:  # pragma: no cover - depends on the file
            errors.append(f"{extractor.__name__}: {exc}")
            continue
        text = "\n\n".join(page.strip() for page in pages if page.strip())
        if len(text) > len(best_text):
            best_text, best_pages = text, count
    if not best_text and errors:
        raise ValueError("Could not read the PDF: " + "; ".join(errors))
    return best_text, best_pages


def extract_text(filename: str, content: bytes) -> ExtractedText:
    """PDF, plain text or markdown in; text out."""
    name = (filename or "").lower()
    pages: int | None = None
    if name.endswith(".pdf"):
        text, pages = _pdf_text(content)
    elif name.endswith(".docx"):
        raise ValueError("DOCX is not supported. Export the CV as PDF, TXT or Markdown.")
    else:
        text = content.decode("utf-8", errors="replace")

    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) < 100:
        raise ValueError(
            "The extracted CV text is too short to be useful. If the PDF is a scan or an "
            "image, export it with selectable text, or paste the text instead."
        )
    return ExtractedText(text, pages)


def _heuristic_parse(text: str) -> ParsedCV:
    """Used when no model is configured, so an upload still produces something."""
    known = [
        "python", "php", "laravel", "symfony", "fastapi", "django", "flask", "javascript",
        "typescript", "react", "vue", "node", "sql", "mysql", "postgresql", "sqlite", "redis",
        "docker", "kubernetes", "aws", "azure", "gcp", "git", "linux", "rest", "graphql",
        "pandas", "numpy", "pytorch", "tensorflow", "scikit-learn", "llm", "nlp", "celery",
        "rabbitmq", "elasticsearch", "terraform", "ci/cd", "pytest", "phpunit",
    ]
    lowered = text.lower()
    skills = [s for s in known if s in lowered]
    years = None
    match = re.search(r"(\d+)\+?\s*(?:years|jahre)", lowered)
    if match:
        years = float(match.group(1))
    return ParsedCV(
        summary=text[:400],
        skills=skills,
        role_targets=["Backend Developer", "Full Stack Developer", "Python Developer"],
        years_experience=years,
    )


class ParseOutcome(NamedTuple):
    """The profile plus anything the caller should tell the user about.

    Parsing degrades rather than failing, so without the warnings an upload that
    silently fell back to keyword matching looks identical to a good one.
    """

    profile: ParsedCV
    warnings: list[str]


def parse_cv(text: str) -> ParseOutcome:
    if not llm.available:
        logger.warning("No model configured; falling back to heuristic CV parsing.")
        return ParseOutcome(
            _heuristic_parse(text),
            ["OPENAI_API_KEY is not set, so the CV was read by keyword matching, not by a model."],
        )
    try:
        # Parsed once per upload, and everything downstream depends on it.
        parsed = llm.json_chat(
            SYSTEM_PROMPT, truncate(text, 40_000), ParsedCV, temperature=0.0, max_tokens=12_000
        )
        return ParseOutcome(parsed, [])
    except Exception as exc:
        logger.warning("CV parsing via model failed (%s); using heuristics.", exc)
        return ParseOutcome(
            _heuristic_parse(text),
            [f"The model could not read the CV ({exc}); keyword matching was used instead."],
        )


def get_active_profile(db: Session) -> CVProfile | None:
    return db.execute(
        select(CVProfile).where(CVProfile.is_active.is_(True)).order_by(CVProfile.id.desc()).limit(1)
    ).scalar_one_or_none()


class SaveResult(NamedTuple):
    profile: CVProfile
    warnings: list[str]


def save_profile(
    db: Session, *, filename: str, text: str, page_count: int | None = None
) -> SaveResult:
    """Parse, embed and store, deactivating any previous CV."""
    parsed, warnings = parse_cv(text)

    # The embedding backend works with or without a key: OpenAI when configured,
    # otherwise the built-in lexical one. Both are recorded as
    # "<backend>:<model>" so a run can tell whether the stored CV vector is
    # comparable with the vectors it is about to produce for jobs.
    embedding_json = None
    embedding_model = None
    try:
        embedding_source = "\n".join(
            filter(
                None,
                [
                    parsed.summary,
                    "Skills: " + ", ".join(parsed.skills),
                    "Target roles: " + ", ".join(parsed.role_targets),
                    text[:20_000],
                ],
            )
        )
        embedding_json = json.dumps(embedder.embed_query(embedding_source))
        embedding_model = embedder.model_tag
    except Exception as exc:
        logger.warning("CV embedding failed: %s", exc)
        warnings.append(
            f"Embedding the CV failed ({exc}), so jobs cannot be ranked against it. "
            "Upload the CV again once the cause is fixed."
        )

    for old in db.execute(select(CVProfile).where(CVProfile.is_active.is_(True))).scalars():
        old.is_active = False

    profile = CVProfile(
        filename=filename,
        raw_text=text,
        summary=parsed.summary,
        skills=json.dumps(parsed.skills, ensure_ascii=False),
        role_targets=json.dumps(parsed.role_targets, ensure_ascii=False),
        years_experience=parsed.years_experience,
        experience=json.dumps(
            [item.model_dump() for item in parsed.experience], ensure_ascii=False
        ),
        languages=json.dumps(parsed.languages, ensure_ascii=False),
        education=json.dumps([item.model_dump() for item in parsed.education], ensure_ascii=False),
        projects=json.dumps([item.model_dump() for item in parsed.projects], ensure_ascii=False),
        certifications=json.dumps(parsed.certifications, ensure_ascii=False),
        page_count=page_count,
        embedding=embedding_json,
        embedding_model=embedding_model,
        is_active=True,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return SaveResult(profile, warnings)
