from __future__ import annotations

import pytest

from app.pipeline.geo import is_germany_related


@pytest.mark.parametrize(
    "location,expected",
    [
        ("Berlin", True),
        ("München", True),
        ("Munich, Germany", True),
        ("Frankfurt am Main", True),
        ("Berlin, BERLIN", True),  # Bundesagentur formatting
        ("Remote, Germany", True),
        ("Hamburg or Berlin", True),
        ("Madrid, Spain", False),
        ("Remote, Brasil", False),
        ("Remote - EMEA", False),  # EU-wide is not Germany-specific
        ("San Francisco", False),
        ("London", False),
        ("Vienna", False),  # German-speaking, but not Germany
        ("Zurich", False),
        ("Graz", False),  # Austrian, and Austrian companies are GmbHs too
    ],
)
def test_location_decides_when_it_names_a_place(location, expected):
    assert is_germany_related(location=location) is expected


@pytest.mark.parametrize("text", ["challenges", "Copenhagen", "essential skills", "culminate"])
def test_words_that_merely_contain_a_city_name_are_not_a_german_signal(text):
    """"cha(llen)ges" contains Halle, "Copen(hagen)" contains Hagen."""
    assert is_germany_related(location="", company=text, description=text) is False


def test_bare_remote_needs_a_german_employer():
    assert is_germany_related(location="Remote") is False
    assert is_germany_related(location="Remote", company="Acme GmbH") is True
    assert is_germany_related(location="Remote", description="Join our Berlin-based team.") is True


def test_small_german_towns_are_kept_via_the_employer():
    """Gilching is too small to list, but Quantum-Systems GmbH is clearly German."""
    assert is_germany_related(location="Gilching", company="Quantum-Systems GmbH") is True
    assert is_germany_related(location="Gilching") is False


def test_arbeitsagentur_is_always_the_german_market():
    assert is_germany_related(location="", source="arbeitsagentur") is True


def test_a_named_foreign_country_beats_a_german_employer_signal():
    assert (
        is_germany_related(
            location="Remote, Brasil", company="Acme GmbH", description="Berlin HQ"
        )
        is False
    )


def test_a_global_office_footer_does_not_make_a_spanish_role_german():
    description = "Work from Madrid. " + ("filler. " * 600) + "Offices: Berlin, Paris, Madrid."
    assert is_germany_related(location="Madrid", description=description) is False


def test_unknown_location_with_no_employer_signal_is_dropped():
    assert is_germany_related(location="Atlantis") is False
