"""E4 consistency metrics on hand-made rating runs."""

from dataclasses import replace

import pytest

from pipeline.rating_consistency import (
    big_disagreements,
    compare,
    render_report,
    spotcheck_rows,
    weighted_kappa,
)
from pipeline.ratings import Rating


def _r(breed: str, trait: str, score: int | None) -> Rating:
    return Rating(
        breed=breed,
        trait=trait,
        score=score,
        evidence="" if score is None else f"{breed} quote about {trait}.",
        status="rated" if score is not None else "unknown",
        wikipedia_title=breed,
        wikipedia_revision_id=7,
        model="m",
        prompt_version="v1a",
    )


A = [_r("Pug", "energy", 2), _r("Pug", "barking", None), _r("Boxer", "energy", 5)]
A += [_r("Boxer", "barking", 3)]
B = [_r("Pug", "energy", 2), _r("Pug", "barking", 4), _r("Boxer", "energy", 4)]
B += [_r("Boxer", "barking", 1)]


def test_weighted_kappa_known_values() -> None:
    assert weighted_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == pytest.approx(1.0)
    assert weighted_kappa([1, 5], [5, 1]) == pytest.approx(-1.0)
    assert weighted_kappa([], []) is None
    assert weighted_kappa([3, 3], [3, 3]) is None  # no variation: kappa is undefined


def test_compare_counts_decisions_and_agreement() -> None:
    result = compare(A, B)
    assert (result.pairs, result.both_rated, result.both_unknown) == (4, 3, 0)
    assert (result.only_a, result.only_b) == (0, 1)
    assert (result.exact, result.within_one) == (1, 2)
    assert result.same_decision == 3

    energy = compare(A, B, "energy")
    assert (energy.pairs, energy.exact, energy.within_one) == (2, 1, 2)


def test_big_disagreements() -> None:
    [(rating, other)] = big_disagreements(A, B)
    assert (rating.breed, rating.trait, rating.score, other) == ("Boxer", "barking", 3, 1)


def test_report_has_overall_and_per_trait_rows() -> None:
    report = render_report(A, B)
    assert "| Both rated | 3 |" in report
    assert "| ...within one point | 67% |" in report
    assert "| Boxer | barking | 3 | 1 |" in report
    assert "| energy | 2 | 2 | 2 | 50% | 100% |" in report


def test_spotcheck_lists_rated_traits_only_and_is_deterministic() -> None:
    rows = spotcheck_rows(A, B)
    assert rows == spotcheck_rows(A, B)
    assert {(r["breed"], r["trait"]) for r in rows} == {
        ("Pug", "energy"),
        ("Boxer", "energy"),
        ("Boxer", "barking"),
    }
    pug = next(r for r in rows if r["breed"] == "Pug")
    assert pug["score_run_b"] == "2"
    assert pug["article"].endswith("oldid=7")
    assert pug["your_verdict"] == ""


def test_spotcheck_samples_at_most_20_breeds() -> None:
    many = [_r(f"Breed {i}", "energy", 3) for i in range(30)]
    rows = spotcheck_rows(many, [replace(r) for r in many])
    assert len({r["breed"] for r in rows}) == 20
