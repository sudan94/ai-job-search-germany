from __future__ import annotations

from app.llm import cosine_similarity
from app.pipeline.language import heuristic_verdict, judge
from app.pipeline.scoring import ScoreResult


def test_verhandlungssicheres_deutsch_is_german_required():
    verdict = heuristic_verdict(
        "Wir suchen einen Backend Entwickler. Verhandlungssicheres Deutsch ist erforderlich."
    )
    assert verdict is not None
    assert verdict.german_required is True
    assert verdict.confidence > 0.9
    assert "eutsch" in verdict.evidence


def test_english_posting_demanding_fluent_german_is_caught():
    verdict = heuristic_verdict(
        "You will build APIs in Python. Fluent German is required for this customer-facing role."
    )
    assert verdict is not None and verdict.german_required is True


def test_english_workplace_phrase_wins():
    verdict = heuristic_verdict(
        "Unsere Unternehmenssprache ist Englisch. Du arbeitest an unserer Plattform."
    )
    assert verdict is not None
    assert verdict.german_required is False
    assert verdict.working_language == "english"


def test_german_as_a_plus_is_not_a_requirement():
    verdict = heuristic_verdict(
        "You will work with Python and Django in a distributed team. German is a plus."
    )
    assert verdict is not None and verdict.german_required is False


def test_ambiguous_text_has_no_heuristic_verdict():
    assert heuristic_verdict("We are looking for a backend engineer to join the team.") is None


def test_judge_without_a_model_falls_back_to_detection():
    verdict = judge(
        "Wir sind ein wachsendes Unternehmen und suchen Verstärkung für unser Team "
        "in der Softwareentwicklung mit Schwerpunkt auf modernen Webanwendungen."
    )
    assert verdict.source == "fallback"
    assert verdict.confidence < 0.5, "a guess must never look confident"


def test_cosine_similarity_bounds():
    assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_score_result_clamps_and_coerces():
    result = ScoreResult.model_validate(
        {"score": "142", "matched": "Python", "missing": None, "verdict": "too generous"}
    )
    assert result.score == 100
    assert result.matched == ["Python"]
    assert result.missing == []


def test_score_result_handles_garbage_score():
    assert ScoreResult.model_validate({"score": "not a number"}).score == 0
