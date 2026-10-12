"""Data card rendering from small synthetic inputs."""

from datetime import date

from pipeline.breed_data import BreedRecord, TraitRecord
from pipeline.breed_mapping import Breed, BreedMapping
from pipeline.data_card import CardInputs, render
from pipeline.matching import Match
from pipeline.restrictions import CountryNote, Restriction

BREEDS = [
    Breed("Pug", "Pug", "n02110958-pug", 1, "Pug"),
    Breed("Toy Poodle", "Poodle", "n02113624-toy_poodle", 2, "Poodle (Toy)"),
    Breed("Standard Poodle", "Poodle", "n02113799-standard_poodle", 3, "Poodle"),
]
MAPPING = BreedMapping(
    breeds=BREEDS,
    dog_api_matches=[
        Match("Pug", "Pug", "exact", 100),
        Match("Toy Poodle", "Poodle (Toy)", "alias", 100),
        Match("Standard Poodle", "Poodle", "alias", 100),
    ],
    stanford_excluded=["n02115641-dingo"],
    dog_api_total=600,
)


def _inputs(
    splits: dict[str, list[dict[str, str]]], traits: list[TraitRecord] | None = None
) -> CardInputs:
    return CardInputs(
        manifest={
            "oxford_images": {
                "url": "https://example.test/images.tar.gz",
                "size_bytes": 791_918_971,
                "sha256": "a" * 64,
            },
            "dog_api_breeds": {
                "url": "https://example.test/breeds",
                "size_bytes": 685_256,
                "sha256": "b" * 64,
            },
        },
        mapping=MAPPING,
        records=[BreedRecord(b.name, b.stanford_label, 5, 9, 25, 30, None, None) for b in BREEDS],
        traits=traits or [],
        manual_sizes=["Toy Poodle"],
        size_problems=["Pug: lifespan missing"],
        restrictions=[
            Restriction("DK", "Pug", "banned", "https://x.dk", date(2026, 10, 1), ""),
            Restriction("DK", "Toy Poodle", "restricted", "https://x.dk", date(2026, 10, 12), ""),
        ],
        country_notes=[CountryNote("GB", "Type-based bans.", "https://x.uk", date(2026, 10, 5))],
        splits=splits,
    )


def _row(class_index: str, breed: str, label: str, species: str = "dog") -> dict[str, str]:
    return {
        "path": "x.jpg",
        "class_index": class_index,
        "breed": breed,
        "source_label": label,
        "species": species,
    }


def test_render_summarises_every_section() -> None:
    splits = {
        "stanford_train": [_row("0", "Pug", "p"), _row("0", "Pug", "p"), _row("1", "E", "e")],
        "oxford": [
            _row("0", "Pug", "pug"),
            _row("", "", "american_bulldog"),
            _row("", "", "Bengal", "cat"),
        ],
    }
    card = render(_inputs(splits))

    assert card.startswith("# Data card\n")
    assert "| `oxford_images` | [link](https://example.test/images.tar.gz) | 791.9 MB |" in card
    assert "| `dog_api_breeds` | [link](https://example.test/breeds) | 685.3 kB |" in card
    assert "| Breeds (Stanford Dogs photo classes) | 3 |" in card
    assert "| Wikipedia articles | 2 |" in card
    assert "1 exact, 0 fuzzy, 0 unmatched" in card
    assert "Not loaded yet." in card
    assert "manual fills for: Toy Poodle." in card
    assert "- Pug: lifespan missing" in card
    assert "| DK | 1 | 1 | no | 2026-10-12 |" in card
    assert "| GB | 0 | 0 | yes | 2026-10-05 |" in card
    assert "| train | 3 | 2 | 1-2 |" in card
    assert "| Dogs of our photo classes | 1 | 1 |" in card
    assert "Other dogs: american_bulldog." in card
    assert "Oxford-IIIT is the honest number" in card
    assert "AKC" not in card


def test_render_counts_ratings_when_loaded() -> None:
    traits = [TraitRecord("Pug", "energy", 3), TraitRecord("Pug", "barking", 2)]
    assert "2 ratings for 1 breeds." in render(_inputs({}, traits))


def test_render_without_splits_and_is_deterministic() -> None:
    card = render(_inputs({}))
    assert "Not built (the pipeline ran with `--skip-images`)." in card
    assert card == render(_inputs({}))
