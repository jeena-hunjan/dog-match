"""Image manifests for training and evaluation.

- Stanford Dogs: the official train/test split, with a stratified 15% of train held out
  as validation (seed 42). Wild canids are dropped, leaving 117 classes.
- Oxford-IIIT Pet: an external test set. Dogs of our classes measure accuracy on images the
  backbone has not seen in ImageNet; other dogs and cats test abstention and not-a-dog.

Manifests hold file names and labels only (never images), are deterministic, and are
committed under data/splits/ so every training run uses exactly the same split.
Image paths are relative to the dataset's image folder, which differs between machines.
"""

import csv
import random
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from pipeline.breed_mapping import Aliases, Breed, MappingError
from pipeline.matching import match_names

VAL_FRACTION = 0.15
SEED = 42

# Folders inside data/raw/ after extraction.
STANFORD_IMAGE_DIR = Path("stanford/images/Images")
STANFORD_LISTS_DIR = Path("stanford/lists")
OXFORD_IMAGE_DIR = Path("oxford/images/images")
OXFORD_LIST = Path("oxford/annotations/annotations/list.txt")

_OXFORD_DOG, _OXFORD_CAT = "2", "1"


@dataclass(frozen=True)
class PhotoClass:
    index: int
    stanford_label: str
    breed: str


@dataclass(frozen=True)
class ImageRow:
    path: str  # relative to the dataset's image folder
    class_index: int | None  # None: not one of our photo classes
    breed: str | None  # canonical breed name, None for cats and unmapped dogs
    source_label: str  # Stanford folder name or Oxford breed prefix
    species: str  # "dog" or "cat"


@dataclass(frozen=True)
class Splits:
    classes: list[PhotoClass]
    stanford: dict[str, list[ImageRow]]  # train, val, test
    oxford: list[ImageRow]


def photo_classes(breeds: Iterable[Breed]) -> list[PhotoClass]:
    """Class indices 0..116, ordered by Stanford label (the synset order)."""
    labelled = sorted((b.stanford_label, b.name) for b in breeds if b.stanford_label)
    return [PhotoClass(i, label, name) for i, (label, name) in enumerate(labelled)]


def stratified_split(
    items: Sequence[str], label_of: Callable[[str], str], fraction: float, seed: int
) -> tuple[list[str], list[str]]:
    """Hold out round(fraction * n) items of every label. Deterministic for a given seed."""
    rng = random.Random(seed)
    by_label: dict[str, list[str]] = defaultdict(list)
    for item in items:
        by_label[label_of(item)].append(item)
    train: list[str] = []
    held_out: list[str] = []
    for label in sorted(by_label):
        group = sorted(by_label[label])
        rng.shuffle(group)
        n_held_out = round(len(group) * fraction)
        held_out += group[:n_held_out]
        train += group[n_held_out:]
    return sorted(train), sorted(held_out)


def _stanford_label(path: str) -> str:
    return path.split("/", 1)[0]


def stanford_splits(
    raw_dir: Path,
    classes: Sequence[PhotoClass],
    fraction: float = VAL_FRACTION,
    seed: int = SEED,
) -> dict[str, list[ImageRow]]:
    from pipeline.stanford import read_file_list  # scipy is only needed when this runs

    by_label = {c.stanford_label: c for c in classes}

    def rows(paths: Iterable[str]) -> list[ImageRow]:
        result = []
        for path in paths:
            c = by_label[_stanford_label(path)]
            result.append(ImageRow(path, c.index, c.breed, c.stanford_label, "dog"))
        return result

    lists = raw_dir / STANFORD_LISTS_DIR
    train_all = [
        p for p in read_file_list(lists / "train_list.mat") if _stanford_label(p) in by_label
    ]
    test = [p for p in read_file_list(lists / "test_list.mat") if _stanford_label(p) in by_label]
    train, val = stratified_split(train_all, _stanford_label, fraction, seed)
    return {"train": rows(train), "val": rows(val), "test": rows(sorted(test))}


def oxford_breed(image_name: str) -> str:
    """'german_shorthaired_12' -> 'german_shorthaired' (cats are capitalised: 'Bengal')."""
    return image_name.rsplit("_", 1)[0]


def oxford_rows(
    list_path: Path, breeds: Sequence[Breed], classes: Sequence[PhotoClass], aliases: Aliases
) -> list[ImageRow]:
    """Every image in Oxford's list.txt, with dogs mapped to canonical breeds."""
    entries: list[tuple[str, str]] = []  # (image name, species id)
    for line in list_path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            name, _class_id, species, _breed_id = line.split()
            entries.append((name, species))

    dog_breeds = sorted({oxford_breed(n) for n, s in entries if s == _OXFORD_DOG})
    to_match = [b for b in dog_breeds if b not in aliases.oxford_unmapped]
    try:
        matches = match_names(to_match, [b.name for b in breeds], aliases.oxford_to_breed)
    except ValueError as e:
        raise MappingError(f"Oxford matching: {e}") from e
    unmatched = [m.source for m in matches if m.target is None]
    if unmatched:
        raise MappingError(f"Oxford dog breeds with no breed (add to aliases.yaml): {unmatched}")
    breed_for = {m.source: m.target for m in matches}
    class_for = {c.breed: c.index for c in classes}

    rows = []
    for name, species in entries:
        source = oxford_breed(name)
        if species == _OXFORD_DOG:
            breed = breed_for.get(source)
            class_index = class_for.get(breed) if breed else None
            rows.append(ImageRow(f"{name}.jpg", class_index, breed, source, "dog"))
        else:
            rows.append(ImageRow(f"{name}.jpg", None, None, source, "cat"))
    return rows


def build_splits(raw_dir: Path, breeds: Sequence[Breed], aliases: Aliases) -> Splits:
    classes = photo_classes(breeds)
    return Splits(
        classes=classes,
        stanford=stanford_splits(raw_dir, classes),
        oxford=oxford_rows(raw_dir / OXFORD_LIST, breeds, classes, aliases),
    )


def missing_images(raw_dir: Path, splits: Splits) -> list[Path]:
    """Manifest entries whose image file is not on disk (should be none)."""
    paths = [
        raw_dir / STANFORD_IMAGE_DIR / r.path for rows in splits.stanford.values() for r in rows
    ]
    paths += [raw_dir / OXFORD_IMAGE_DIR / r.path for r in splits.oxford]
    return [p for p in paths if not p.is_file()]


def _write_csv(path: Path, header: Sequence[str], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(header), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_splits(splits: Splits, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [out_dir / "classes.csv"]
    _write_csv(
        written[0], [f.name for f in fields(PhotoClass)], (asdict(c) for c in splits.classes)
    )
    row_fields = [f.name for f in fields(ImageRow)]
    for name, rows in [
        *(("stanford_" + k, v) for k, v in splits.stanford.items()),
        ("oxford", splits.oxford),
    ]:
        path = out_dir / f"{name}.csv"
        _write_csv(path, row_fields, (asdict(r) for r in rows))
        written.append(path)
    return written
