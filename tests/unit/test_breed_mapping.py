"""Name matching, the breed list and its mapping to TheDogAPI. No downloaded data needed."""

import csv
from dataclasses import replace
from pathlib import Path

import pytest

from pipeline.breed_mapping import (
    Aliases,
    BreedEntry,
    MappingError,
    build_mapping,
    load_breed_list,
    write_outputs,
)
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


# --- breed list ----------------------------------------------------------------------


def test_load_breed_list_short_and_long_forms(tmp_path: Path) -> None:
    path = tmp_path / "breeds.yaml"
    path.write_text(
        "pug: Pug\nboxer: {name: Boxer, wikipedia: Boxer (dog breed)}\n", encoding="utf-8"
    )
    assert load_breed_list(path) == {
        "pug": BreedEntry("Pug", "Pug"),
        "boxer": BreedEntry("Boxer", "Boxer (dog breed)"),
    }


def test_load_breed_list_rejects_duplicate_names(tmp_path: Path) -> None:
    path = tmp_path / "breeds.yaml"
    path.write_text("pug: Pug\nPug_dog: Pug\n", encoding="utf-8")
    with pytest.raises(MappingError, match="duplicate names"):
        load_breed_list(path)


# --- build_mapping on a small synthetic dataset ---------------------------------------

STANFORD = [
    "n02110958-pug",
    "n02107142-Doberman",
    "n02113624-toy_poodle",
    "n02113799-standard_poodle",
    "n02105412-kelpie",
    "n02115641-dingo",
]
BREED_LIST = {
    "pug": BreedEntry("Pug", "Pug"),
    "Doberman": BreedEntry("Dobermann", "Dobermann"),
    "toy_poodle": BreedEntry("Toy Poodle", "Poodle"),
    "standard_poodle": BreedEntry("Standard Poodle", "Poodle"),
    "kelpie": BreedEntry("Australian Kelpie", "Australian Kelpie"),
}
DOG_API = [
    {"id": 1, "name": "Pug"},
    {"id": 2, "name": "Doberman Pinscher"},
    {"id": 3, "name": "Poodle (Toy)"},
    {"id": 4, "name": "Poodle"},
    {"id": 5, "name": "Beagle"},
    {"id": 5, "name": "Beagle"},  # TheDogAPI has a few duplicate records
]
ALIASES = Aliases(
    stanford_excluded=frozenset({"dingo"}),
    breed_to_dog_api={
        "Dobermann": "Doberman Pinscher",
        "Toy Poodle": "Poodle (Toy)",
        "Standard Poodle": "Poodle",
    },
)


def test_build_mapping_links_stanford_wikipedia_and_dog_api() -> None:
    mapping = build_mapping(STANFORD, DOG_API, BREED_LIST, ALIASES, expected_photo_breeds=5)
    by_name = {b.name: b for b in mapping.breeds}

    assert [b.name for b in mapping.breeds] == [
        "Pug",
        "Dobermann",
        "Toy Poodle",
        "Standard Poodle",
        "Australian Kelpie",
    ]
    assert mapping.stanford_excluded == ["n02115641-dingo"]
    assert by_name["Dobermann"].stanford_label == "n02107142-Doberman"
    assert by_name["Dobermann"].dog_api_id == 2
    assert by_name["Toy Poodle"].wikipedia_title == "Poodle"
    assert by_name["Standard Poodle"].dog_api_name == "Poodle"
    assert by_name["Australian Kelpie"].dog_api_id is None  # reported for a manual size fill
    assert mapping.dog_api_total == 5  # the duplicate Beagle record counts once


def test_wrong_photo_breed_count_raises() -> None:
    with pytest.raises(MappingError, match="expected 117 photo breeds, got 5"):
        build_mapping(STANFORD, DOG_API, BREED_LIST, ALIASES)


def test_stanford_label_missing_from_breed_list_raises() -> None:
    breed_list = {k: v for k, v in BREED_LIST.items() if k != "kelpie"}
    with pytest.raises(MappingError, match=r"missing from breeds.yaml: \['kelpie'\]"):
        build_mapping(STANFORD, DOG_API, breed_list, ALIASES, expected_photo_breeds=5)


def test_breed_list_entry_without_stanford_class_raises() -> None:
    breed_list = {**BREED_LIST, "shiba_inu": BreedEntry("Shiba Inu", "Shiba Inu")}
    with pytest.raises(MappingError, match=r"breeds\.yaml has entries not found"):
        build_mapping(STANFORD, DOG_API, breed_list, ALIASES, expected_photo_breeds=5)


@pytest.mark.parametrize(
    "aliases",
    [
        replace(ALIASES, stanford_excluded=frozenset({"dingo", "dhole_typo"})),
        replace(ALIASES, breed_to_dog_api={"Doberman": "Doberman Pinscher"}),
    ],
)
def test_alias_entries_missing_from_data_raise(aliases: Aliases) -> None:
    with pytest.raises(MappingError, match="not found in the data"):
        build_mapping(STANFORD, DOG_API, BREED_LIST, aliases, expected_photo_breeds=5)


def test_write_outputs(tmp_path: Path) -> None:
    mapping = build_mapping(STANFORD, DOG_API, BREED_LIST, ALIASES, expected_photo_breeds=5)
    csv_path, report_path = write_outputs(mapping, tmp_path)

    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(mapping.breeds)
    assert rows[1] == {
        "name": "Dobermann",
        "wikipedia_title": "Dobermann",
        "stanford_label": "n02107142-Doberman",
        "dog_api_id": "2",
        "dog_api_name": "Doberman Pinscher",
    }
    report = report_path.read_text(encoding="utf-8")
    assert "| Australian Kelpie |" in report  # listed under "no TheDogAPI match"
    assert "n02115641-dingo" in report


# --- the real breeds.yaml and aliases.yaml -------------------------------------------


def test_real_breed_list_has_117_unique_breeds() -> None:
    breeds = load_breed_list()
    assert len(breeds) == 117
    assert len({b.name for b in breeds.values()}) == 117
    shared = {"Poodle": 3, "Belgian Shepherd": 2}
    titles = [b.wikipedia_title for b in breeds.values()]
    assert {t: titles.count(t) for t in shared} == shared
    assert len(set(titles)) == 117 - 2 - 1


@pytest.mark.parametrize(
    ("stanford_key", "name", "wikipedia"),
    [
        ("Blenheim_spaniel", "Cavalier King Charles Spaniel", "Cavalier King Charles Spaniel"),
        ("Doberman", "Dobermann", "Dobermann"),
        ("cocker_spaniel", "English Cocker Spaniel", "English Cocker Spaniel"),
        ("boxer", "Boxer", "Boxer (dog breed)"),
        ("malinois", "Belgian Malinois", "Belgian Shepherd"),
        ("Great_Pyrenees", "Pyrenean Mountain Dog", "Pyrenean Mountain Dog"),
        ("Eskimo_dog", "Canadian Eskimo Dog", "Canadian Eskimo Dog"),
        ("toy_poodle", "Toy Poodle", "Poodle"),
    ],
)
def test_known_breeds(stanford_key: str, name: str, wikipedia: str) -> None:
    assert load_breed_list()[stanford_key] == BreedEntry(name, wikipedia)


def test_real_aliases_file_is_consistent() -> None:
    aliases = Aliases.load()
    names = {b.name for b in load_breed_list().values()}
    assert aliases.stanford_excluded == {"dingo", "dhole", "African_hunting_dog"}
    assert set(aliases.breed_to_dog_api) <= names
    assert set(aliases.oxford_to_breed.values()) <= names
    assert not set(aliases.oxford_to_breed) & aliases.oxford_unmapped
