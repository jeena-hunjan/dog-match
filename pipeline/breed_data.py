"""Turn the mapped sources into rows for the breeds and breed_traits tables. Pure, no I/O.

- Sizes come from TheDogAPI's metric strings ("3.2-4.5", "Male: 23-25; Female: 18-23"),
  overridden by pipeline/manual_sizes.csv where TheDogAPI is missing or wrong.
- Traits are the 14 numeric AKC ratings (1-5). A score outside 1-5 is a source error
  (the TidyTuesday Plott Hound row is all zeros) and is dropped, not loaded.
"""

import csv
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline.breed_mapping import Breed
from pipeline.breed_names import clean

MANUAL_SIZES_PATH = Path(__file__).with_name("manual_sizes.csv")

# AKC column -> trait key stored in breed_traits.trait.
TRAIT_COLUMNS: dict[str, str] = {
    "Affectionate With Family": "affectionate_with_family",
    "Good With Young Children": "good_with_young_children",
    "Good With Other Dogs": "good_with_other_dogs",
    "Shedding Level": "shedding_level",
    "Coat Grooming Frequency": "coat_grooming_frequency",
    "Drooling Level": "drooling_level",
    "Openness To Strangers": "openness_to_strangers",
    "Playfulness Level": "playfulness_level",
    "Watchdog/Protective Nature": "watchdog_protective_nature",
    "Adaptability Level": "adaptability_level",
    "Trainability Level": "trainability_level",
    "Energy Level": "energy_level",
    "Barking Level": "barking_level",
    "Mental Stimulation Needs": "mental_stimulation_needs",
}

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_SIZE_FIELDS = (
    "weight_min_kg",
    "weight_max_kg",
    "height_min_cm",
    "height_max_cm",
    "lifespan_min_years",
    "lifespan_max_years",
)


@dataclass(frozen=True)
class Range:
    min: float | None
    max: float | None


@dataclass(frozen=True)
class BreedRecord:
    """One row of the breeds table (the database assigns the id)."""

    name: str
    stanford_label: str | None
    weight_min_kg: float | None
    weight_max_kg: float | None
    height_min_cm: float | None
    height_max_cm: float | None
    lifespan_min_years: float | None
    lifespan_max_years: float | None


@dataclass(frozen=True)
class TraitRecord:
    breed: str
    trait: str
    score: int


def parse_range(text: str | None) -> Range:
    """Overall min and max of every number in a TheDogAPI range string.

    "Male: 23-25; Female: 18-23" -> (18, 25); "up to 9" -> (None, 9); "" or "unknown" -> empty.
    """
    numbers = [float(n) for n in _NUMBER.findall(text or "")]
    if not numbers:
        return Range(None, None)
    if len(numbers) == 1 and "up to" in (text or "").lower():
        return Range(None, numbers[0])
    return Range(min(numbers), max(numbers))


def dog_api_sizes(record: Mapping[str, Any]) -> dict[str, float | None]:
    weight = parse_range((record.get("weight") or {}).get("metric"))
    height = parse_range((record.get("height") or {}).get("metric"))
    lifespan = parse_range(record.get("life_span"))
    return dict(
        zip(
            _SIZE_FIELDS,
            (weight.min, weight.max, height.min, height.max, lifespan.min, lifespan.max),
            strict=True,
        )
    )


def load_manual_sizes(path: Path = MANUAL_SIZES_PATH) -> dict[str, dict[str, float | None]]:
    """Breed name -> size fields. Empty cells mean "keep TheDogAPI's value"."""
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    manual: dict[str, dict[str, float | None]] = {}
    for row in rows:
        if not row["source_url"].startswith("https://"):
            raise ValueError(f"manual size for {row['breed']} needs an https source_url")
        manual[row["breed"]] = {k: float(row[k]) if row[k] else None for k in _SIZE_FIELDS}
    return manual


def breed_records(
    breeds: Sequence[Breed],
    dog_api: Iterable[Mapping[str, Any]],
    manual_sizes: Mapping[str, Mapping[str, float | None]],
) -> list[BreedRecord]:
    unknown = sorted(set(manual_sizes) - {b.name for b in breeds})
    if unknown:
        raise ValueError(f"manual_sizes.csv names unknown breeds: {unknown}")
    by_id = {int(r["id"]): r for r in dog_api}
    records = []
    for breed in breeds:
        sizes: dict[str, float | None] = dict.fromkeys(_SIZE_FIELDS)
        if breed.dog_api_id is not None:
            sizes |= dog_api_sizes(by_id[breed.dog_api_id])
        for key, value in manual_sizes.get(breed.name, {}).items():
            if value is not None:
                sizes[key] = value
        records.append(BreedRecord(name=breed.name, stanford_label=breed.stanford_label, **sizes))
    return records


def size_problems(records: Iterable[BreedRecord]) -> list[str]:
    """Missing or implausible sizes, for the data card. An empty list means all good."""
    limits = {"weight": (0.5, 120.0), "height": (10.0, 100.0), "lifespan": (5.0, 25.0)}
    problems = []
    for r in records:
        for prefix, (low, high) in limits.items():
            unit = {"weight": "kg", "height": "cm", "lifespan": "years"}[prefix]
            lo, hi = getattr(r, f"{prefix}_min_{unit}"), getattr(r, f"{prefix}_max_{unit}")
            if lo is None or hi is None:
                problems.append(f"{r.name}: {prefix} missing")
            elif not low <= lo <= hi <= high:
                problems.append(f"{r.name}: {prefix} {lo}-{hi} out of range")
    return problems


def trait_records(
    akc_rows: Iterable[Mapping[str, Any]], breeds: Sequence[Breed]
) -> tuple[list[TraitRecord], list[str]]:
    """Trait rows for every breed with AKC data, plus the (breed, trait) scores dropped
    because they were outside 1-5. Poodle varieties share the AKC Poodle scores."""
    by_akc: dict[str, list[str]] = {}
    for b in breeds:
        if b.akc_name is not None:
            by_akc.setdefault(b.akc_name, []).append(b.name)

    records: list[TraitRecord] = []
    dropped: list[str] = []
    for row in akc_rows:
        for name in by_akc.get(clean(str(row["Breed"])), []):
            for column, trait in TRAIT_COLUMNS.items():
                score = int(row[column])
                if 1 <= score <= 5:
                    records.append(TraitRecord(name, trait, score))
                else:
                    dropped.append(f"{name}: {trait}={score}")
    return records, dropped
