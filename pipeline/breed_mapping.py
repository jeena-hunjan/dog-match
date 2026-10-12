"""Map breed names from AKC, Stanford Dogs and TheDogAPI onto one canonical breed list.

Canonical breeds are the AKC breeds (singular names, Poodles split by size) plus the
Stanford breeds AKC does not recognise. Each canonical breed gets at most one Stanford
label and one TheDogAPI record. Writes data/interim/breeds.csv and a matching report.
"""

import csv
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Self

import pandas as pd
import yaml

from pipeline.breed_names import akc_display_name, clean, stanford_alias_key
from pipeline.matching import Match, match_names

ALIASES_PATH = Path(__file__).with_name("aliases.yaml")
EXPECTED_PHOTO_BREEDS = 117
BREEDS_CSV = "breeds.csv"
REPORT_MD = "name_matching_report.md"


class MappingError(RuntimeError):
    """The sources and aliases.yaml disagree; fix aliases.yaml rather than the code."""


@dataclass(frozen=True)
class Aliases:
    akc_singular: dict[str, str]
    singular_words: frozenset[str]
    akc_varieties: dict[str, list[str]]
    stanford_excluded: frozenset[str]
    stanford_only: dict[str, str]
    stanford_to_breed: dict[str, str]
    breed_to_dog_api: dict[str, str]
    oxford_to_breed: dict[str, str] = field(default_factory=dict)
    oxford_unmapped: frozenset[str] = frozenset()

    @classmethod
    def load(cls, path: Path = ALIASES_PATH) -> Self:
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        return cls(
            akc_singular=dict(data.get("akc_singular") or {}),
            singular_words=frozenset(data.get("singular_words_ending_in_s") or ()),
            akc_varieties={k: list(v) for k, v in (data.get("akc_varieties") or {}).items()},
            stanford_excluded=frozenset(data.get("stanford_excluded") or ()),
            stanford_only=dict(data.get("stanford_only") or {}),
            stanford_to_breed=dict(data.get("stanford_to_breed") or {}),
            breed_to_dog_api=dict(data.get("breed_to_dog_api") or {}),
            oxford_to_breed=dict(data.get("oxford_to_breed") or {}),
            oxford_unmapped=frozenset(data.get("oxford_unmapped") or ()),
        )


@dataclass(frozen=True)
class Breed:
    name: str
    akc_name: str | None
    stanford_label: str | None
    dog_api_id: int | None
    dog_api_name: str | None


@dataclass(frozen=True)
class BreedMapping:
    breeds: list[Breed]
    stanford_matches: list[Match]  # source: Stanford label without synset id
    dog_api_matches: list[Match]  # source: canonical breed name
    stanford_excluded: list[str]
    dog_api_total: int

    @property
    def photo_breeds(self) -> list[Breed]:
        return [b for b in self.breeds if b.stanford_label is not None]


def _check_known(kind: str, keys: Sequence[str] | set[str], known: set[str]) -> None:
    unknown = sorted(set(keys) - known)
    if unknown:
        raise MappingError(f"aliases.yaml {kind} has entries not found in the data: {unknown}")


def canonical_breeds(akc_names: Sequence[str], aliases: Aliases) -> list[tuple[str, str | None]]:
    """(canonical name, cleaned AKC name or None) for every breed, in AKC order."""
    _check_known("akc_singular", list(aliases.akc_singular), {clean(n) for n in akc_names})
    rows: list[tuple[str, str | None]] = []
    for raw in akc_names:
        display = akc_display_name(raw, aliases.akc_singular, aliases.singular_words)
        rows += [(name, clean(raw)) for name in aliases.akc_varieties.get(display, [display])]
    rows += [(name, None) for name in aliases.stanford_only.values()]

    duplicates = [n for n, c in Counter(n for n, _ in rows).items() if c > 1]
    if duplicates:
        raise MappingError(f"duplicate canonical breed names: {duplicates}")
    return rows


def build_mapping(
    akc_names: Sequence[str],
    stanford_labels: Sequence[str],
    dog_api_breeds: Sequence[dict[str, Any]],
    aliases: Aliases,
    expected_photo_breeds: int = EXPECTED_PHOTO_BREEDS,
) -> BreedMapping:
    canonical = canonical_breeds(akc_names, aliases)
    names = [name for name, _ in canonical]

    # Stanford label -> canonical breed. Every photo label must match.
    by_key = {stanford_alias_key(label): label for label in stanford_labels}
    _check_known(
        "Stanford entries",
        [*aliases.stanford_excluded, *aliases.stanford_only, *aliases.stanford_to_breed],
        set(by_key),
    )
    excluded = [by_key[k] for k in by_key if k in aliases.stanford_excluded]
    photo_keys = [k for k in by_key if k not in aliases.stanford_excluded]
    if len(photo_keys) != expected_photo_breeds:
        raise MappingError(f"expected {expected_photo_breeds} photo breeds, got {len(photo_keys)}")

    try:
        stanford_matches = match_names(
            photo_keys, names, {**aliases.stanford_to_breed, **aliases.stanford_only}
        )
    except ValueError as e:
        raise MappingError(f"Stanford matching: {e}") from e
    unmatched = [m.source for m in stanford_matches if m.target is None]
    if unmatched:
        raise MappingError(f"Stanford labels with no breed (add to aliases.yaml): {unmatched}")
    label_for = {m.target: by_key[m.source] for m in stanford_matches}

    # Canonical breed -> TheDogAPI record (for sizes). Misses are reported, not fatal.
    dog_api_ids: dict[str, int] = {}
    for record in dog_api_breeds:
        dog_api_ids.setdefault(clean(record["name"]), int(record["id"]))
    _check_known("breed_to_dog_api keys", list(aliases.breed_to_dog_api), set(names))
    try:
        dog_api_matches = match_names(names, list(dog_api_ids), aliases.breed_to_dog_api)
    except ValueError as e:
        raise MappingError(f"TheDogAPI matching: {e}") from e
    dog_api_for = {m.source: m.target for m in dog_api_matches if m.target is not None}

    breeds = [
        Breed(
            name=name,
            akc_name=akc_name,
            stanford_label=label_for.get(name),
            dog_api_id=dog_api_ids[dog_api_for[name]] if name in dog_api_for else None,
            dog_api_name=dog_api_for.get(name),
        )
        for name, akc_name in canonical
    ]
    return BreedMapping(breeds, stanford_matches, dog_api_matches, excluded, len(dog_api_ids))


def load_and_build(raw_dir: Path, aliases: Aliases) -> BreedMapping:
    """Read the downloaded sources from raw_dir and build the mapping."""
    from pipeline.stanford import class_labels  # scipy is only needed when this runs

    akc = pd.read_csv(raw_dir / "akc" / "breed_traits.csv", encoding="utf-8")
    dog_api = json.loads((raw_dir / "dog_api" / "breeds.json").read_text(encoding="utf-8"))
    return build_mapping(
        akc_names=akc["Breed"].tolist(),
        stanford_labels=class_labels(raw_dir / "stanford" / "lists"),
        dog_api_breeds=dog_api,
        aliases=aliases,
    )


def _method_counts(matches: Sequence[Match]) -> str:
    counts = Counter(m.method for m in matches)
    return ", ".join(f"{method} {counts[method]}" for method in ("alias", "exact", "fuzzy", "none"))


def _report(mapping: BreedMapping) -> str:
    breeds = mapping.breeds
    akc = [b for b in breeds if b.akc_name is not None]
    fuzzy_stanford = [m for m in mapping.stanford_matches if m.method == "fuzzy"]
    fuzzy_dog_api = [m for m in mapping.dog_api_matches if m.method == "fuzzy"]
    no_size = [m for m in mapping.dog_api_matches if m.target is None]
    dog_api_used = [m for m in mapping.dog_api_matches if m.target is not None]
    lines = [
        "# Breed name matching report",
        "",
        "Generated by `make data` (pipeline/breed_mapping.py). Do not edit by hand;",
        "fix `pipeline/aliases.yaml` and re-run instead.",
        "",
        "## Summary",
        "",
        "| | Count |",
        "|---|---|",
        f"| Canonical breeds | {len(breeds)} |",
        f"| ...with AKC traits | {len(akc)} ({len({b.akc_name for b in akc})} AKC entries) |",
        f"| ...with a Stanford photo class | {len(mapping.photo_breeds)} |",
        f"| ...photo class but no AKC traits | {sum(b.akc_name is None for b in breeds)} |",
        f"| ...with TheDogAPI sizes | {sum(b.dog_api_id is not None for b in breeds)} |",
        f"| Stanford labels excluded (wild canids) | {len(mapping.stanford_excluded)} |",
        f"| TheDogAPI breeds not used | {mapping.dog_api_total - len(dog_api_used)}"
        f" of {mapping.dog_api_total} |",
        "",
        f"Stanford → breed: {_method_counts(mapping.stanford_matches)}.",
        f"Breed → TheDogAPI: {_method_counts(mapping.dog_api_matches)}.",
        "",
        "## Fuzzy matches to review",
        "",
    ]
    if fuzzy_stanford or fuzzy_dog_api:
        lines += ["| Source | Matched to | Score |", "|---|---|---|"]
        lines += [f"| {m.source} | {m.target} | {m.score:.1f} |" for m in fuzzy_stanford]
        lines += [f"| {m.source} | {m.target} (TheDogAPI) | {m.score:.1f} |" for m in fuzzy_dog_api]
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
        writer = csv.DictWriter(f, fieldnames=[field.name for field in fields(Breed)])
        writer.writeheader()
        writer.writerows(asdict(b) for b in mapping.breeds)
    report_path = out_dir / REPORT_MD
    report_path.write_text(_report(mapping), encoding="utf-8")
    return csv_path, report_path
