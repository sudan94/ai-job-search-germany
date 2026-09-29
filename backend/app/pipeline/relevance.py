"""Drop postings whose title is not the kind of job I am looking for.

This runs on the title alone, and deliberately so.  Descriptions mention
everything - a PHP job lists "Java" under nice-to-haves, a backend job names the
hardware team it supports - so matching on body text keeps almost everything.
The title is the one field that states what the job actually is.

Two gates, cheapest first, both free:

* an **exclude** list wins outright: seniority above a junior/mid profile
  (senior, staff, head of) and disciplines or stacks that are not mine
  (hardware, sales, Java, Salesforce),
* an **include** list then requires the title to name a role I target.

Order matters.  "Senior Software Engineer" passes the include gate on
"engineer", so exclusion has to be checked first or seniority never bites.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Roles worth scoring: junior Python, AI, and junior-to-mid PHP, plus the
#: general software titles those jobs are advertised under in both languages.
DEFAULT_INCLUDE_TITLE_TERMS = [
    "python", "django", "flask", "fastapi",
    "php", "laravel", "symfony",
    "ai", "ki", "machine learning", "deep learning", "data science", "llm", "nlp",
    "backend", "back end", "back-end", "fullstack", "full stack", "full-stack",
    # German stems, not whole words: "entwickl" has to reach "Entwickler",
    # "Entwicklung" and "Softwareentwicklung" alike.
    "software", "developer", "entwickl", "programmer", "programmier",
    "engineer", "engineering", "web", "informatik", "devops", "api",
    "javascript", "typescript", "react", "node",
]

#: Checked first and wins.  Three groups: too senior, wrong discipline, wrong
#: stack.  Word-boundary matching keeps "java" from firing on "JavaScript".
DEFAULT_EXCLUDE_TITLE_TERMS = [
    # Seniority above a junior/mid profile
    "senior", "sr", "lead", "leiter", "leitung", "principal", "staff",
    "head", "director", "chief", "vp", "manager", "architect", "architekt",
    # Not software
    "hardware", "embedded", "firmware", "mechanical", "mechanik", "mechatronik",
    "electrical", "elektro", "elektronik", "electronics", "chemical", "civil",
    "sales", "vertrieb", "marketing", "recruiter", "recruiting",
    # "finance" is deliberately absent: it would drop "Backend Engineer,
    # Finance Platform", and "Finance Manager" is already caught by "manager".
    "accountant", "buchhalter", "controller", "designer", "design",
    "pflege", "nurse", "fahrer", "driver", "logistik", "lager",
    "consultant", "berater",
    # Stacks that are not mine
    "java", "kotlin", "swift", "ios", "android", "golang", "ruby", "rust",
    "scala", "salesforce", "sap", "abap", "sharepoint", "unity", "unreal",
    ".net", "c#", "c++",
]

#: `\b` is useless around these, so they are matched as plain substrings.
_NEEDS_SUBSTRING = re.compile(r"[#+.]")

#: German glues words together - "Softwareentwicklung", "Fachinformatiker",
#: "Elektroniker" - so a word-boundary match on "software" or "elektronik"
#: finds nothing.  Terms this long or longer are matched as substrings, which
#: compounds survive.  Shorter ones keep both boundaries, because that is what
#: stops "java" from firing on "JavaScript" and "ai" on "Maintainer".
_COMPOUND_MIN_LENGTH = 5


def _split_terms(terms: list[str]) -> tuple[list[str], list[str]]:
    """Into (word terms, substring terms) by the rule above."""
    words: list[str] = []
    substrings: list[str] = []
    for term in terms:
        cleaned = term.strip().lower()
        if not cleaned:
            continue
        needs_substring = (
            _NEEDS_SUBSTRING.search(cleaned) is not None
            or len(cleaned.replace(" ", "")) >= _COMPOUND_MIN_LENGTH
        )
        (substrings if needs_substring else words).append(cleaned)
    return words, substrings


def _pattern(words: list[str]) -> re.Pattern[str] | None:
    if not words:
        return None
    # Longest first so the reported match is the specific term, not a prefix.
    ordered = sorted(set(words), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in ordered) + r")\b")


@dataclass(frozen=True)
class RelevanceRules:
    include: re.Pattern[str] | None
    include_substrings: tuple[str, ...]
    exclude: re.Pattern[str] | None
    exclude_substrings: tuple[str, ...]


def build_rules(
    include_terms: list[str] | None = None,
    exclude_terms: list[str] | None = None,
) -> RelevanceRules:
    include_words, include_substrings = _split_terms(
        DEFAULT_INCLUDE_TITLE_TERMS if include_terms is None else include_terms
    )
    exclude_words, exclude_substrings = _split_terms(
        DEFAULT_EXCLUDE_TITLE_TERMS if exclude_terms is None else exclude_terms
    )
    return RelevanceRules(
        include=_pattern(include_words),
        include_substrings=tuple(include_substrings),
        exclude=_pattern(exclude_words),
        exclude_substrings=tuple(exclude_substrings),
    )


def _first_match(text: str, pattern: re.Pattern[str] | None, substrings: tuple[str, ...]) -> str | None:
    if pattern is not None:
        found = pattern.search(text)
        if found:
            return found.group(0)
    # Earliest in the title wins, so the reason names the word a reader would
    # blame first: "Senior Java Developer" is reported as senior, not java.
    hits = [(text.index(term), term) for term in substrings if term in text]
    return min(hits)[1] if hits else None


def title_rejection(title: str, rules: RelevanceRules) -> str | None:
    """Why this title was dropped, or None to keep it.

    The reason is a phrase, not a boolean, so a run can say *which* word cost a
    posting its place and the list stays tunable from the dashboard.
    """
    lowered = (title or "").strip().lower()
    if not lowered:
        return "no title"

    banned = _first_match(lowered, rules.exclude, rules.exclude_substrings)
    if banned:
        return f"title contains '{banned}'"

    if rules.include is None and not rules.include_substrings:
        return None  # no include list configured: keep everything not excluded
    if _first_match(lowered, rules.include, rules.include_substrings) is None:
        return "title names no targeted role"
    return None


def is_relevant(title: str, rules: RelevanceRules) -> bool:
    return title_rejection(title, rules) is None
