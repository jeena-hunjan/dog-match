"""Name matching and the canonical breed mapping. No downloaded data needed."""

import csv
from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.breed_mapping import (
    Aliases,
    MappingError,
    build_mapping,
    canonical_breeds,
    write_outputs,
)
from pipeline.breed_names import akc_display_name
from pipeline.matching import match_names

# --- match_names ---------------------------------------------------------------------


def test_alias_then_exact_then_fuzzy() -> None:
    results = match_names(
        sources=["Boston_bull", "golden_retriever", "bull_mastiff", "kelpie"],
        targets=["Boston Terrier", "Golden Retriever", "Bullmastiff", "Beagle"],
        aliases={"Boston_bull": "Boston Terrier"},
    )
    assert [(m.target, m.method) for m in results] == [
        ("Boston Terrier", "alias"),
        ("Golden Retriever", "exact"),
        ("Bullmastiff", "fuzzy"),
        (None, "none"),
    ]
    assert results[2].score > 92
    assert results[3].candidate is not None


def test_similar_names_are_not_fuzzy_matched() -> None:
    [result] = match_names(["Norfolk Terrier"], ["Norwich Terrier"], aliases={})
    assert result.target is None
    assert result.candidate == "Norwich Terrier"


def test_each_target_is_used_once() -> None:
    results = match_names(["Bullmastiff", "Bull_mastiff"], ["Bullmastiff"], aliases={})
    assert [m.method for m in results] == ["exact", "none"]


def test_alias_to_unknown_target_raises() -> None:
    with pytest.raises(ValueError, match="unknown targets"):
        match_names(["chow"], ["Chow Chow"], aliases={"chow": "Chow Chows"})


def test_two_sources_claiming_one_target_raises() -> None:
    with pytest.raises(ValueError, match="both match"):
        match_names(["chow", "Chow Chow"], ["Chow Chow"], aliases={"chow": "Chow Chow"})


# --- build_mapping on a small synthetic dataset -----------------------------------------

AKC = ["Retrievers\xa0(Labrador)", "Poodles", "Kuvaszok", "Chow\xa0Chows", "Beagles"]
STANFORD = [
    "n02099712-Labrador_retriever",
    "n02113624-toy_poodle",
    "n02113799-standard_poodle",
    "n02104029-kuvasz",
    "n02112137-chow",
    "n02105412-kelpie",
    "n02115641-dingo",
]
DOG_API = [
    {"id": 1, "name": "Labrador Retriever"},
    {"id": 2, "name": "Poodle (Toy)"},
    {"id": 3, "name": "Poodle"},
    {"id": 4, "name": "Kuvasz"},
    {"id": 5, "name": "Australian Kelpie"},
    {"id": 6, "name": "Beagle"},
    {"id": 6, "name": "Beagle"},  # TheDogAPI has a few duplicate records
]
ALIASES = Aliases(
    akc_singular={"Kuvaszok": "Kuvasz"},
    singular_words=frozenset(),
    akc_varieties={"Poodle": ["Toy Poodle", "Standard Poodle"]},
    stanford_excluded=frozenset({"dingo"}),
    stanford_only={"kelpie": "Australian Kelpie"},
    stanford_to_breed={"chow": "Chow Chow"},
    breed_to_dog_api={"Toy Poodle": "Poodle (Toy)", "Standard Poodle": "Poodle"},
)


def test_canonical_breeds_split_varieties_and_add_stanford_only() -> None:
    assert canonical_breeds(AKC, ALIASES) == [
        ("Labrador Retriever", "Retrievers (Labrador)"),
        ("Toy Poodle", "Poodles"),
        ("Standard Poodle", "Poodles"),
        ("Kuvasz", "Kuvaszok"),
        ("Chow Chow", "Chow Chows"),
        ("Beagle", "Beagles"),
        ("Australian Kelpie", None),
    ]


def test_build_mapping_links_all_three_sources() -> None:
    mapping = build_mapping(AKC, STANFORD, DOG_API, ALIASES, expected_photo_breeds=6)
    by_name = {b.name: b for b in mapping.breeds}

    assert len(mapping.photo_breeds) == 6
    assert mapping.stanford_excluded == ["n02115641-dingo"]
    assert by_name["Toy Poodle"].stanford_label == "n02113624-toy_poodle"
    assert by_name["Toy Poodle"].dog_api_id == 2
    assert by_name["Standard Poodle"].dog_api_name == "Poodle"
    assert by_name["Chow Chow"].stanford_label == "n02112137-chow"
    assert by_name["Chow Chow"].dog_api_id is None  # reported for a manual size fill
    assert by_name["Australian Kelpie"].akc_name is None
    assert by_name["Beagle"].stanford_label is None
    assert mapping.dog_api_total == 6


def test_wrong_photo_breed_count_raises() -> None:
    with pytest.raises(MappingError, match="expected 117 photo breeds, got 6"):
        build_mapping(AKC, STANFORD, DOG_API, ALIASES)


def test_unmatched_stanford_label_raises() -> None:
    aliases = replace(ALIASES, stanford_to_breed={})
    with pytest.raises(MappingError, match=r"no breed.*chow"):
        build_mapping(AKC, STANFORD, DOG_API, aliases, expected_photo_breeds=6)


@pytest.mark.parametrize(
    "aliases",
    [
        replace(ALIASES, stanford_to_breed={"chow": "Chow Chow", "chow_typo": "Chow Chow"}),
        replace(ALIASES, akc_singular={"Kuvaszoks": "Kuvasz"}),
        replace(ALIASES, breed_to_dog_api={"Toy Poodles": "Poodle (Toy)"}),
    ],
)
def test_alias_entries_missing_from_data_raise(aliases: Aliases) -> None:
    with pytest.raises(MappingError, match="not found in the data"):
        build_mapping(AKC, STANFORD, DOG_API, aliases, expected_photo_breeds=6)


def test_write_outputs(tmp_path: Path) -> None:
    mapping = build_mapping(AKC, STANFORD, DOG_API, ALIASES, expected_photo_breeds=6)
    csv_path, report_path = write_outputs(mapping, tmp_path)

    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(mapping.breeds)
    assert rows[0] == {
        "name": "Labrador Retriever",
        "akc_name": "Retrievers (Labrador)",
        "stanford_label": "n02099712-Labrador_retriever",
        "dog_api_id": "1",
        "dog_api_name": "Labrador Retriever",
    }
    report = report_path.read_text(encoding="utf-8")
    assert "| Chow Chow |" in report  # listed under "no TheDogAPI match"
    assert "n02115641-dingo" in report


# --- known breeds, using the real pipeline/aliases.yaml ------------------------------


@pytest.fixture(scope="module")
def real_aliases() -> Aliases:
    return Aliases.load()


@pytest.mark.parametrize(
    ("akc_raw", "expected"),
    [
        ("Retrievers\xa0(Labrador)", "Labrador Retriever"),
        ("Belgian\xa0Malinois", "Belgian Malinois"),
        ("Bichons\xa0Frises", "Bichon Frise"),
        ("Cirnechi\xa0dell\u2019Etna", "Cirneco dell'Etna"),
        ("Keeshonden", "Keeshond"),
        ("Siberian\xa0Huskies", "Siberian Husky"),
        ("Great\xa0Pyrenees", "Great Pyrenees"),
        ("St.\xa0Bernards", "St. Bernard"),
    ],
)
def test_known_akc_names(real_aliases: Aliases, akc_raw: str, expected: str) -> None:
    name = akc_display_name(akc_raw, real_aliases.akc_singular, real_aliases.singular_words)
    assert name == expected


@pytest.mark.parametrize(
    ("stanford_key", "expected"),
    [
        ("Blenheim_spaniel", "Cavalier King Charles Spaniel"),
        ("Japanese_spaniel", "Japanese Chin"),
        ("groenendael", "Belgian Sheepdog"),
        ("malinois", "Belgian Malinois"),
        ("Mexican_hairless", "Xoloitzcuintli"),
        ("cocker_spaniel", "English Cocker Spaniel"),
        ("Saint_Bernard", "St. Bernard"),
        ("Norfolk_terrier", "Norfolk Terrier"),
        ("Norwich_terrier", "Norwich Terrier"),
        ("toy_poodle", "Toy Poodle"),
        ("Eskimo_dog", "Eskimo Dog"),
    ],
)
def test_known_stanford_labels(real_aliases: Aliases, stanford_key: str, expected: str) -> None:
    targets = [
        "Cavalier King Charles Spaniel",
        "Japanese Chin",
        "Belgian Sheepdog",
        "Belgian Malinois",
        "Xoloitzcuintli",
        "Cocker Spaniel",
        "English Cocker Spaniel",
        "St. Bernard",
        "Norfolk Terrier",
        "Norwich Terrier",
        "Toy Poodle",
        "Miniature Poodle",
        "American Eskimo Dog",
        *real_aliases.stanford_only.values(),
    ]
    aliases = {**real_aliases.stanford_to_breed, **real_aliases.stanford_only}
    [result] = match_names([stanford_key], targets, aliases)
    assert result.target == expected


def test_real_aliases_file_is_consistent(real_aliases: Aliases) -> None:
    assert real_aliases.stanford_excluded == {"dingo", "dhole", "African_hunting_dog"}
    overlap = set(real_aliases.stanford_to_breed) & set(real_aliases.stanford_only)
    assert not overlap
    assert not set(real_aliases.stanford_to_breed) & real_aliases.stanford_excluded
    assert len(set(real_aliases.breed_to_dog_api.values())) == len(real_aliases.breed_to_dog_api)
