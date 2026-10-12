"""Breed ratings: quote verification, unknowns, caching, variants, CSV. Fake LLM only."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.llm.llm_client import LLMError, Usage
from pipeline.ratings import (
    TRAITS,
    BreedToRate,
    check_quote,
    normalise_for_match,
    rate_breed,
    rate_breeds,
    read_ratings,
    response_schema,
    summarise,
    trait_order,
    user_prompt,
    write_ratings,
)
from pipeline.wikipedia import Article

ARTICLE = Article(
    title="Pug",
    page_id=1,
    revision_id=99,
    revision_timestamp="2026-09-01T00:00:00Z",
    text=(
        "The Pug is a breed of dog.\n"
        "Pugs are known for being sociable and gentle companion dogs.\n"
        "They shed a lot \u2013 especially in summer \u2013 and need little exercise."
    ),
)
PUG = BreedToRate("Pug", ARTICLE)


def _answer(**overrides: dict[str, str]) -> dict[str, Any]:
    answer = {trait: {"score": "unknown", "quote": ""} for trait in TRAITS}
    answer.update(overrides)
    return answer


class FakeLLM:
    model = "fake-model"

    def __init__(self, answer: dict[str, Any] | None = None, fail: bool = False) -> None:
        self.answer = answer or _answer()
        self.fail = fail
        self.usage = Usage()
        self.calls: list[dict[str, Any]] = []

    def complete_json(
        self, *, system: str, user: str, schema: dict[str, Any], max_tokens: int = 4096
    ) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if self.fail:
            raise LLMError("model refused")
        return self.answer


# --- quote checking ------------------------------------------------------------------


def test_normalise_forgives_typography_only() -> None:
    assert normalise_for_match("They shed  a lot - Especially") == normalise_for_match(
        "they shed a lot \u2013 especially"
    )
    assert normalise_for_match("\u201cquoted\u201d") == '"quoted"'


@pytest.mark.parametrize(
    ("quote", "status"),
    [
        ("Pugs are known for being sociable and gentle companion dogs.", "rated"),
        ("They shed a lot - especially in summer", "rated"),  # dash type and case differ
        ('"Pugs are known for being sociable and gentle companion dogs."', "rated"),
        ("Pugs are known for being friendly and gentle companion dogs.", "quote_not_found"),
        ("Pugs are", "quote_too_short"),
        ("", "quote_too_short"),
        ("x" * 500, "quote_not_found"),
    ],
)
def test_check_quote(quote: str, status: str) -> None:
    assert check_quote(quote, ARTICLE.text) == status


# --- prompt and schema ---------------------------------------------------------------


def test_variant_b_reverses_trait_order_in_prompt_and_schema() -> None:
    assert trait_order("b") == list(reversed(trait_order("a")))
    assert list(response_schema("b")["properties"]) == trait_order("b")
    prompt_a, prompt_b = user_prompt(PUG, "a"), user_prompt(PUG, "b")
    assert prompt_a.index("- energy:") < prompt_a.index("- grooming:")
    assert prompt_b.index("- grooming:") < prompt_b.index("- energy:")


def test_schema_is_strict_and_allows_unknown() -> None:
    schema = response_schema("a")
    assert schema["additionalProperties"] is False
    assert schema["required"] == list(TRAITS)
    trait = schema["properties"]["energy"]
    assert trait["properties"]["score"]["enum"] == ["1", "2", "3", "4", "5", "unknown"]
    assert trait["additionalProperties"] is False


def test_prompt_contains_breed_and_article() -> None:
    prompt = user_prompt(PUG, "a")
    assert prompt.startswith("Breed to rate: Pug")
    assert ARTICLE.text in prompt
    assert '<article title="Pug">' in prompt


# --- rating --------------------------------------------------------------------------


def test_scores_need_a_verified_quote(tmp_path: Path) -> None:
    llm = FakeLLM(
        _answer(
            good_with_other_dogs={
                "score": "5",
                "quote": "Pugs are known for being sociable and gentle companion dogs.",
            },
            shedding={"score": "5", "quote": "They shed a lot - especially in summer"},
            energy={"score": "1", "quote": "Pugs need almost no exercise at all, ever."},
            barking={"score": "unknown", "quote": "ignored"},
        )
    )
    ratings = {r.trait: r for r in rate_breed(llm, PUG, "a", tmp_path)}

    assert list(ratings) == list(TRAITS)  # canonical order
    assert (ratings["good_with_other_dogs"].score, ratings["good_with_other_dogs"].status) == (
        5,
        "rated",
    )
    assert ratings["shedding"].score == 5
    assert (ratings["energy"].score, ratings["energy"].status) == (None, "quote_not_found")
    assert ratings["energy"].evidence == ""  # an unverified quote is never published
    assert (ratings["barking"].score, ratings["barking"].evidence) == (None, "")
    assert ratings["shedding"].wikipedia_revision_id == 99
    assert ratings["shedding"].prompt_version == "v1a"


def test_responses_are_cached_per_revision_and_model(tmp_path: Path) -> None:
    llm = FakeLLM()
    rate_breed(llm, PUG, "a", tmp_path)
    rate_breed(llm, PUG, "a", tmp_path)
    assert len(llm.calls) == 1

    rate_breed(llm, PUG, "b", tmp_path)  # another variant is another cache entry
    assert len(llm.calls) == 2

    new_revision = BreedToRate("Pug", Article("Pug", 1, 100, "t", ARTICLE.text))
    rate_breed(llm, new_revision, "a", tmp_path)  # article changed: rate again
    assert len(llm.calls) == 3

    cached = json.loads((tmp_path / "v1a" / "Pug.json").read_text(encoding="utf-8"))
    assert cached["revision_id"] == 100


def test_failures_are_collected_not_fatal(tmp_path: Path) -> None:
    errors: list[str] = []
    ratings = rate_breeds(
        FakeLLM(fail=True), [PUG], "a", tmp_path, on_error=lambda n, e: errors.append(n)
    )
    assert ratings == []
    assert errors == ["Pug"]
    with pytest.raises(LLMError):
        rate_breeds(FakeLLM(fail=True), [PUG], "a", tmp_path)


def test_csv_round_trip_and_summary(tmp_path: Path) -> None:
    llm = FakeLLM(
        _answer(
            shedding={"score": "5", "quote": "They shed a lot - especially in summer"},
        )
    )
    ratings = rate_breeds(llm, [PUG], "a", tmp_path / "cache")
    path = tmp_path / "ratings.csv"
    write_ratings(ratings, path)

    assert read_ratings(path) == ratings
    summary = summarise(ratings)
    assert "8 ratings for 1 breeds" in summary
    assert "shedding 1/1" in summary
