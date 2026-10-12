"""Data card rendering from small synthetic inputs."""

from datetime import date

from pipeline.breed_data import BreedRecord, TraitRecord
from pipeline.breed_mapping import Breed, BreedMapping
from pipeline.data_card import CardInputs, render
from pipeline.matching import Match
from pipeline.restrictions import Restriction

BREEDS = [
    Breed("Pug", "Pugs", "n02110958-pug", 1, "Pug"),
    Breed("Plott Hound", "Plott Hounds", None, 2, "Plott"),
    Breed("Eskimo Dog", None, "n02109961-Eskimo_dog", 3, "Canadian Eskimo Dog"),
]
MAPPING = BreedMapping(
    breeds=BREEDS,
    stanford_matches=[
        Match("pug", "Pug", "exact", 100),
        Match("Eskimo_dog", "Eskimo Dog", "alias", 100),
    ],
    dog_api_matches=[Match(b.name, b.dog_api_name, "exact", 100) for b in BREEDS],
    stanford_excluded=["n02115641-dingo"],
    dog_api_total=600,
)


def _inputs(splits: dict[str, list[dict[str, str]]]) -> CardInputs:
    return CardInputs(
        manifest={
            "oxford_images": {
                "url": "https://example.test/images.tar.gz",
                "size_bytes": 791_918_971,
                "sha256": "a" * 64,
            }
        },
        mapping=MAPPING,
        records=[BreedRecord(b.name, b.stanford_label, 5, 9, 25, 30, None, None) for b in BREEDS],
        traits=[TraitRecord("Pug", "energy_level", 3)],
        dropped_traits=["Plott Hound: energy_level=0"],
        manual_sizes=["Portuguese Podengo Pequeno"],
        size_problems=["Pug: lifespan missing"],
        restrictions=[
            Restriction("DK", "Pug", "banned", "https://x.dk", date(2026, 10, 1), ""),
            Restriction("DK", "Eskimo Dog", "restricted", "https://x.dk", date(2026, 10, 12), ""),
        ],
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
    assert "| Canonical breeds | 3 |" in card
    assert "| Photo class but no AKC ratings | 1 |" in card
    assert "Breeds without trait ratings (cannot be scored): Eskimo Dog, Plott Hound." in card
    assert "1 alias, 1 exact, 0 fuzzy" in card
    assert "Dropped 1 scores outside 1-5 (source errors) for: Plott Hound." in card
    assert "manual fills for: Portuguese Podengo Pequeno." in card
    assert "- Pug: lifespan missing" in card
    assert "| DK | 1 | 1 | 2026-10-12 |" in card
    assert "| train | 3 | 2 | 1-2 |" in card
    assert "| Dogs of our photo classes | 1 | 1 |" in card
    assert "Other dogs: american_bulldog." in card
    assert "Oxford-IIIT is the honest number" in card


def test_render_without_splits_and_is_deterministic() -> None:
    card = render(_inputs({}))
    assert "Not built (the pipeline ran with `--skip-images`)." in card
    assert card == render(_inputs({}))
