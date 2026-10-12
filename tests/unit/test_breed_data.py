"""Size parsing, manual fills and trait rows. No database needed."""

from pathlib import Path

import pytest

from pipeline.breed_data import (
    TRAIT_COLUMNS,
    BreedRecord,
    Range,
    breed_records,
    load_manual_sizes,
    parse_range,
    size_problems,
    trait_records,
)
from pipeline.breed_mapping import Breed


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("3.2-4.5", Range(3.2, 4.5)),
        ("Male: 23-25; Female: 18-23", Range(18, 25)),
        ("10 - 12 years", Range(10, 12)),
        ("23", Range(23, 23)),
        ("up to 9", Range(None, 9)),
        ("unknown", Range(None, None)),
        ("", Range(None, None)),
        (None, Range(None, None)),
    ],
)
def test_parse_range(text: str | None, expected: Range) -> None:
    assert parse_range(text) == expected


BREEDS = [
    Breed("Toy Poodle", "Poodles", "n02113624-toy_poodle", 197, "Poodle (Toy)"),
    Breed("Standard Poodle", "Poodles", "n02113799-standard_poodle", 195, "Poodle"),
    Breed("Plott Hound", "Plott Hounds", None, 7, "Plott"),
    Breed("Podengo", "Podengos", None, None, None),
    Breed("Eskimo Dog", None, "n02109961-Eskimo_dog", None, None),
]
DOG_API = [
    {
        "id": 197,
        "weight": {"metric": "1.8-2.7"},
        "height": {"metric": "20-25"},
        "life_span": "10-18",
    },
    {"id": 195, "weight": {"metric": "Male: 20-32; Female: 18-27"}, "height": {"metric": "45-61"}},
    {"id": 7, "weight": {"metric": "20-25"}, "height": {"metric": "51-64"}, "life_span": "12-14"},
]


def test_breed_records_use_dog_api_then_manual_fills() -> None:
    manual = {"Podengo": dict.fromkeys(["weight_min_kg", "weight_max_kg"], None)}
    manual["Podengo"] |= {"weight_min_kg": 4.0, "weight_max_kg": 6.0}
    records = {r.name: r for r in breed_records(BREEDS, DOG_API, manual)}

    assert records["Toy Poodle"] == BreedRecord(
        "Toy Poodle", "n02113624-toy_poodle", 1.8, 2.7, 20.0, 25.0, 10.0, 18.0
    )
    assert records["Standard Poodle"].weight_min_kg == 18.0
    assert records["Standard Poodle"].lifespan_min_years is None  # TheDogAPI null
    assert (records["Podengo"].weight_min_kg, records["Podengo"].height_min_cm) == (4.0, None)
    assert records["Eskimo Dog"].stanford_label == "n02109961-Eskimo_dog"


def test_manual_sizes_for_unknown_breed_raise() -> None:
    with pytest.raises(ValueError, match="unknown breeds"):
        breed_records(BREEDS, DOG_API, {"Labradoodle": {}})


def test_real_manual_sizes_file_loads() -> None:
    manual = load_manual_sizes()
    assert manual["Portuguese Podengo Pequeno"]["weight_max_kg"] == 6.0
    assert manual["Portuguese Podengo Pequeno"]["lifespan_min_years"] is None


def test_manual_sizes_need_https_source(tmp_path: Path) -> None:
    path = tmp_path / "m.csv"
    path.write_text(
        "breed,weight_min_kg,weight_max_kg,height_min_cm,height_max_cm,"
        "lifespan_min_years,lifespan_max_years,source_url,notes\n"
        "Podengo,4,6,,,,,http://x,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="https"):
        load_manual_sizes(path)


def test_size_problems_flag_missing_and_implausible() -> None:
    ok = BreedRecord("A", None, 5, 10, 30, 40, 10, 12)
    missing = BreedRecord("B", None, 5, 10, 30, 40, None, None)
    reversed_ = BreedRecord("C", None, 10, 5, 30, 40, 10, 12)
    huge = BreedRecord("D", None, 5, 500, 30, 40, 10, 12)
    assert size_problems([ok, missing, reversed_, huge]) == [
        "B: lifespan missing",
        "C: weight 10-5 out of range",
        "D: weight 5-500 out of range",
    ]


def _akc_row(name: str, score: int) -> dict[str, object]:
    return {"Breed": name} | dict.fromkeys(TRAIT_COLUMNS, score)


def test_trait_records_share_variety_scores_and_drop_invalid() -> None:
    rows = [_akc_row("Poodles", 4), _akc_row("Plott\xa0Hounds", 0)]
    records, dropped = trait_records(rows, BREEDS)

    assert len(records) == 2 * len(TRAIT_COLUMNS)  # Toy and Standard Poodle
    assert {r.breed for r in records} == {"Toy Poodle", "Standard Poodle"}
    assert {r.score for r in records} == {4}
    assert len(dropped) == len(TRAIT_COLUMNS)
    assert dropped[0] == "Plott Hound: affectionate_with_family=0"
