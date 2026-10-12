"""Name normalisation helpers."""

import pytest

from pipeline.breed_names import (
    akc_display_name,
    clean,
    match_key,
    stanford_alias_key,
    stanford_name,
)


def test_clean_handles_nbsp_curly_quotes_and_spacing() -> None:
    assert clean("Cirnechi\xa0dell\u2019Etna ") == "Cirnechi dell'Etna"
    assert clean("  Great   Dane\n") == "Great Dane"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("St. Bernard", "Saint_Bernard"),
        ("Shih Tzu", "Shih-Tzu"),
        ("Bichon Frisé", "Bichon Frise"),
        ("Black and Tan Coonhound", "black-and-tan_coonhound"),
        ("Cirneco dell\u2019Etna", "Cirneco dell'Etna"),
        ("Soft Coated Wheaten Terrier", "soft-coated_wheaten_terrier"),
    ],
)
def test_match_key_equates_spelling_variants(a: str, b: str) -> None:
    assert match_key(a) == match_key(b)


def test_match_key_keeps_different_breeds_apart() -> None:
    assert match_key("Norfolk Terrier") != match_key("Norwich Terrier")


def test_stanford_label_helpers() -> None:
    label = "n02085782-Japanese_spaniel"
    assert stanford_name(label) == "Japanese spaniel"
    assert stanford_alias_key(label) == "Japanese_spaniel"
    assert stanford_alias_key("Japanese_spaniel") == "Japanese_spaniel"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Retrievers\xa0(Labrador)", "Labrador Retriever"),
        ("Fox Terriers (Wire)", "Wire Fox Terrier"),
        ("Setters (Irish Red and White)", "Irish Red and White Setter"),
        ("French Bulldogs", "French Bulldog"),
        ("Brittanys", "Brittany"),
        ("Collies", "Collie"),
        ("Shih Tzu", "Shih Tzu"),
        ("Chinese Crested", "Chinese Crested"),
        ("Great Pyrenees", "Great Pyrenees"),
        ("Maltese", "Maltese"),
        ("Kuvaszok", "Kuvasz"),
    ],
)
def test_akc_display_name(raw: str, expected: str) -> None:
    overrides = {"Kuvaszok": "Kuvasz"}
    keep = {"Maltese", "Pyrenees"}
    assert akc_display_name(raw, overrides, keep) == expected
