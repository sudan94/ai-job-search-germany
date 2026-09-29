"""The title filter: what it keeps, what it drops, and why.

The dropped cases are real titles that reached the jobs table before this
filter existed.
"""

from __future__ import annotations

import pytest

from app.pipeline.relevance import build_rules, is_relevant, title_rejection

RULES = build_rules()


@pytest.mark.parametrize(
    "title",
    [
        "Junior Python Developer (m/w/d)",
        "Python Entwickler",
        "PHP Developer (Laravel)",
        "Werkstudent Softwareentwicklung",
        "Software Engineer – AI Workflows (m/f/d)",
        "Backend Engineer",
        "Fullstack Developer",
        "Product Engineer — Working Student",
        "Engineering Intern",
        "Frontend Engineer (Intern)",
        "Machine Learning Engineer",
        "Working Student - Data Science",
        # German compounds: no word boundary before "entwickl" or after "software"
        "Softwareentwickler (m/w/d)",
        "Werkstudent Softwareentwicklung",
        "Fachinformatiker Anwendungsentwicklung",
        "Webentwickler PHP",
        "KI-Entwickler",
    ],
)
def test_targeted_roles_are_kept(title):
    assert is_relevant(title, RULES), title_rejection(title, RULES)


@pytest.mark.parametrize(
    ("title", "expected_term"),
    [
        # Too senior for a junior/mid profile
        ("Senior Software Engineer, GraphQL - API Platform", "senior"),
        ("Staff Software Engineer - Context Model Core Team", "staff"),
        ("Head of Product Design", "head"),
        ("Engineering Manager - EU", "manager"),
        ("Principal Backend Developer", "principal"),
        ("Lead Python Developer", "lead"),
        ("Software Architect", "architect"),
        # Not software at all
        ("Hardware Engineer", "hardware"),
        ("Embedded Software Engineer", "embedded"),
        ("Sales Engineer", "sales"),
        ("Learning Excellence Manager", "manager"),
        ("Elektroniker (m/w/d)", "elektro"),
        # A stack that is not mine
        ("Java Developer", "java"),
        ("Salesforce Developer", "sales"),
        ("C# Developer", "c#"),
        (".NET Backend Developer", ".net"),
        ("iOS Engineer", "ios"),
    ],
)
def test_off_target_titles_are_dropped_with_a_reason(title, expected_term):
    reason = title_rejection(title, RULES)
    assert reason is not None, f"{title!r} should have been dropped"
    assert expected_term in reason


def test_javascript_is_not_java():
    """Word boundaries, not substrings: `java` must not fire on `JavaScript`."""
    assert is_relevant("JavaScript Developer", RULES)
    assert not is_relevant("Java Developer", RULES)


def test_a_title_naming_no_role_at_all_is_dropped():
    reason = title_rejection("Customer Success Associate", RULES)
    assert reason == "title names no targeted role"


def test_an_empty_include_list_keeps_everything_not_excluded():
    rules = build_rules(include_terms=[], exclude_terms=["senior"])
    assert is_relevant("Customer Success Associate", rules)
    assert not is_relevant("Senior Anything", rules)


def test_the_lists_are_editable():
    """The dashboard owns these lists, so custom terms have to win."""
    rules = build_rules(include_terms=["python"], exclude_terms=["werkstudent"])
    assert is_relevant("Python Developer", rules)
    assert not is_relevant("Werkstudent Python", rules)
    assert not is_relevant("PHP Developer", rules), "not in the custom include list"
