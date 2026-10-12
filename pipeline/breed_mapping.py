"""The canonical breed list and how it links to each source.

The breeds are the 117 Stanford Dogs photo classes, listed with their display name and
English Wikipedia article in pipeline/breeds.yaml. TheDogAPI records (sizes) are matched
to them by name. Writes data/interim/breeds.csv and a matching report.
"""

import csv
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Self

import yaml

from pipeline.breed_names import clean, stanford_alias_key
from pipeline.matching import Match, match_names

ALIASES_PATH = Path(__file__).with_name("aliases.yaml")
BREEDS_PATH = Path(__file__).with_name("breeds.yaml")
EXPECTED_PHOTO_BREEDS = 117
BREEDS_CSV = "breeds.csv"
REPORT_MD = "name_matching_report.md"


class MappingError(RuntimeError):
    """The sources and the YAML files disagree; fix the YAML rather than the code."""


@dataclass(frozen=True)
class Aliases:
    stanford_excluded: frozenset[str]
    breed_to_dog_api: dict[str, str]
    oxford_to_breed: dict[str, str] = field(default_factory=dict)
    oxford_unmapped: frozenset[str] = frozenset()

    @classmethod
    def load(cls, path: Path = ALIASES_PATH) -> Self:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            stanford_excluded=frozenset(data.get("stanford_excluded") or ()),
            breed_to_dog_api=dict(data.get("breed_to_dog_api") or {}),
            oxford_to_breed=dict(data.get("oxford_to_breed") or {}),
            oxford_unmapped=frozenset(data.get("oxford_unmapped") or ()),
        )


@dataclass(frozen=True)
class BreedEntry:
    """One line of breeds.yaml."""

    name: str
    wikipedia_title: str


def load_breed_list(path: Path = BREEDS_PATH) -> dict[str, BreedEntry]:
    """Stanford label (without synset id) -> breed entry, in file order."""
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    entries = {}
    for key, value in data.items():
        if isinstance(value, str):
            entries[key] = BreedEntry(value, value)
        else:
            entries[key] = BreedEntry(value["name"], value.get("wikipedia", value["name"]))
    duplicates = [n for n, c in Counter(e.name for e in entries.values()).items() if c > 1]
    if duplicates:
        raise MappingError(f"breeds.yaml has duplicate names: {duplicates}")
    return entries


@dataclass(frozen=True)
class Breed:
    name: str
    wikipedia_title: str
    stanford_label: str
    dog_api_id: int | None
    dog_api_name: str | None


@dataclass(frozen=True)
class BreedMapping:
    breeds: list[Breed]
    dog_api_matches: list[Match]  # source: breed name
    stanford_excluded: list[str]
    dog_api_total: int

    @property
    def photo_breeds(self) -> list[Breed]:
        return list(self.breeds)


def _check_known(kind: str, keys: Sequence[str] | set[str], known: set[str]) -> None:
    unknown = sorted(set(keys) - known)
    if unknown:
        raise MappingError(f"{kind} has entries not found in the data: {unknown}")


def build_mapping(
    stanford_labels: Sequence[str],
    dog_api_breeds: Sequence[Mapping[str, Any]],
    breed_list: Mapping[str, BreedEntry],
    aliases: Aliases,
    expected_photo_breeds: int = EXPECTED_PHOTO_BREEDS,
) -> BreedMapping:
    by_key = {stanford_alias_key(label): label for label in stanford_labels}
    _check_known("aliases.yaml stanford_excluded", list(aliases.stanford_excluded), set(by_key))
    excluded = [by_key[k] for k in by_key if k in aliases.stanford_excluded]
    photo_keys = [k for k in by_key if k not in aliases.stanford_excluded]
    if len(photo_keys) != expected_photo_breeds:
        raise MappingError(f"expected {expected_photo_breeds} photo breeds, got {len(photo_keys)}")

    # Every photo class needs exactly one breeds.yaml entry, and vice versa.
    _check_known("breeds.yaml", list(breed_list), set(photo_keys))
    missing = sorted(set(photo_keys) - set(breed_list))
    if missing:
        raise MappingError(f"Stanford labels missing from breeds.yaml: {missing}")

    # Breed -> TheDogAPI record (for sizes). Misses are reported, not fatal.
    names = [breed_list[k].name for k in photo_keys]
    dog_api_ids: dict[str, int] = {}
    for record in dog_api_breeds:
        dog_api_ids.setdefault(clean(str(record["name"])), int(record["id"]))
    _check_known("aliases.yaml breed_to_dog_api", list(aliases.breed_to_dog_api), set(names))
    try:
        dog_api_matches = match_names(names, list(dog_api_ids), aliases.breed_to_dog_api)
    except ValueError as e:
        raise MappingError(f"TheDogAPI matching: {e}") from e
    dog_api_for = {m.source: m.target for m in dog_api_matches if m.target is not None}

    breeds = []
    for key in photo_keys:
        entry = breed_list[key]
        dog_api_name = dog_api_for.get(entry.name)
        breeds.append(
            Breed(
                name=entry.name,
                wikipedia_title=entry.wikipedia_title,
                stanford_label=by_key[key],
                dog_api_id=dog_api_ids[dog_api_name] if dog_api_name else None,
                dog_api_name=dog_api_name,
            )
        )
    return BreedMapping(breeds, dog_api_matches, excluded, len(dog_api_ids))


def load_and_build(raw_dir: Path, aliases: Aliases) -> BreedMapping:
    """Read the downloaded sources from raw_dir and build the mapping."""
    from pipeline.stanford import class_labels  # scipy is only needed when this runs

    dog_api = json.loads((raw_dir / "dog_api" / "breeds.json").read_text(encoding="utf-8"))
    return build_mapping(
        stanford_labels=class_labels(raw_dir / "stanford" / "lists"),
        dog_api_breeds=dog_api,
        breed_list=load_breed_list(),
        aliases=aliases,
    )


def _method_counts(matches: Sequence[Match]) -> str:
    counts = Counter(m.method for m in matches)
    return ", ".join(f"{method} {counts[method]}" for method in ("alias", "exact", "fuzzy", "none"))


def _report(mapping: BreedMapping) -> str:
    breeds = mapping.breeds
    fuzzy = [m for m in mapping.dog_api_matches if m.method == "fuzzy"]
    no_size = [m for m in mapping.dog_api_matches if m.target is None]
    dog_api_used = [m for m in mapping.dog_api_matches if m.target is not None]
    lines = [
        "# Breed name matching report",
        "",
        "Generated by `make data` (pipeline/breed_mapping.py). Do not edit by hand;",
        "fix `pipeline/breeds.yaml` or `pipeline/aliases.yaml` and re-run instead.",
        "",
        "## Summary",
        "",
        "| | Count |",
        "|---|---|",
        f"| Breeds (Stanford photo classes) | {len(breeds)} |",
        f"| Wikipedia articles | {len({b.wikipedia_title for b in breeds})} |",
        f"| With TheDogAPI sizes | {len(dog_api_used)} |",
        f"| Stanford labels excluded (wild canids) | {len(mapping.stanford_excluded)} |",
        f"| TheDogAPI breeds not used | {mapping.dog_api_total - len(dog_api_used)}"
        f" of {mapping.dog_api_total} |",
        "",
        f"Breed → TheDogAPI: {_method_counts(mapping.dog_api_matches)}.",
        "",
        "## Fuzzy matches to review",
        "",
    ]
    if fuzzy:
        lines += ["| Breed | TheDogAPI name | Score |", "|---|---|---|"]
        lines += [f"| {m.source} | {m.target} | {m.score:.1f} |" for m in fuzzy]
    else:
        lines.append("None.")
    lines += ["", "## Breeds with no TheDogAPI match (size needs a manual fill)", ""]
    if no_size:
        lines += ["| Breed | Closest TheDogAPI name | Score |", "|---|---|---|"]
        lines += [f"| {m.source} | {m.candidate or '-'} | {m.score:.1f} |" for m in no_size]
    else:
        lines.append("None.")
    lines += ["", "## Excluded Stanford labels", ""]
    lines += [f"- {label}" for label in mapping.stanford_excluded]
    return "\n".join(lines) + "\n"


def write_outputs(mapping: BreedMapping, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / BREEDS_CSV
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[f.name for f in fields(Breed)], lineterminator="\n")
        writer.writeheader()
        writer.writerows(asdict(b) for b in mapping.breeds)
    report_path = out_dir / REPORT_MD
    report_path.write_text(_report(mapping), encoding="utf-8", newline="\n")
    return csv_path, report_path
