"""Split manifests: class indices, stratified validation split, Oxford mapping. No images."""

import csv
from collections import Counter
from pathlib import Path

import numpy as np
import pytest
from scipy.io import savemat

from pipeline.breed_mapping import Aliases, Breed, MappingError
from pipeline.splits import (
    OXFORD_IMAGE_DIR,
    STANFORD_IMAGE_DIR,
    STANFORD_LISTS_DIR,
    Splits,
    missing_images,
    oxford_breed,
    oxford_rows,
    photo_classes,
    stanford_splits,
    stratified_split,
    write_splits,
)

BREEDS = [
    Breed("Pug", "Pug", "n02110958-pug", 1, "Pug"),
    Breed("Beagle", "Beagle", "n02088364-beagle", 2, "Beagle"),
    Breed("German Shorthaired Pointer", "German Shorthaired Pointer", "n02100236-x", 4, None),
]
ALIASES = Aliases(
    stanford_excluded=frozenset(),
    breed_to_dog_api={},
    oxford_to_breed={"german_shorthaired": "German Shorthaired Pointer"},
    oxford_unmapped=frozenset({"american_bulldog", "havanese"}),
)


def _label(path: str) -> str:
    return path.split("/")[0]


def test_photo_classes_are_ordered_by_stanford_label() -> None:
    classes = photo_classes(BREEDS)
    assert [(c.index, c.stanford_label, c.breed) for c in classes] == [
        (0, "n02088364-beagle", "Beagle"),
        (1, "n02100236-x", "German Shorthaired Pointer"),
        (2, "n02110958-pug", "Pug"),
    ]


def test_stratified_split_holds_out_15_percent_of_each_label() -> None:
    items = [f"{label}/{i:03d}.jpg" for label in ("a", "b", "c") for i in range(100)]
    train, val = stratified_split(items, _label, fraction=0.15, seed=42)

    assert Counter(map(_label, val)) == {"a": 15, "b": 15, "c": 15}
    assert Counter(map(_label, train)) == {"a": 85, "b": 85, "c": 85}
    assert not set(train) & set(val)
    assert sorted(train + val) == sorted(items)


def test_stratified_split_is_deterministic_and_seeded() -> None:
    items = [f"a/{i:03d}.jpg" for i in range(100)]
    shuffled = list(reversed(items))  # input order must not matter
    assert stratified_split(items, _label, 0.15, 42) == stratified_split(shuffled, _label, 0.15, 42)
    assert stratified_split(items, _label, 0.15, 42) != stratified_split(items, _label, 0.15, 7)


def _write_mat(path: Path, files: list[str]) -> None:
    cells = np.empty((len(files), 1), dtype=object)
    for i, f in enumerate(files):
        cells[i, 0] = np.array([f])
    path.parent.mkdir(parents=True, exist_ok=True)
    savemat(path, {"file_list": cells})


def test_stanford_splits_from_official_lists(tmp_path: Path) -> None:
    lists = tmp_path / STANFORD_LISTS_DIR
    train = [f"n02110958-pug/p{i}.jpg" for i in range(20)]
    train += [f"n02088364-beagle/b{i}.jpg" for i in range(20)]
    train += ["n02115641-dingo/d0.jpg"]  # excluded class: not in photo_classes
    _write_mat(lists / "train_list.mat", train)
    _write_mat(lists / "test_list.mat", ["n02110958-pug/t0.jpg", "n02115641-dingo/t1.jpg"])

    splits = stanford_splits(tmp_path, photo_classes(BREEDS))

    assert {k: len(v) for k, v in splits.items()} == {"train": 34, "val": 6, "test": 1}
    [test_row] = splits["test"]
    assert (test_row.path, test_row.class_index, test_row.breed) == (
        "n02110958-pug/t0.jpg",
        2,
        "Pug",
    )
    assert all(r.species == "dog" for rows in splits.values() for r in rows)


def test_oxford_breed_prefix() -> None:
    assert oxford_breed("german_shorthaired_12") == "german_shorthaired"
    assert oxford_breed("British_Shorthair_7") == "British_Shorthair"


def _oxford_list(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "list.txt"
    header = "#Image CLASS-ID SPECIES BREED ID\n#SPECIES: 1:Cat 2:Dog\n"
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_oxford_rows_map_dogs_and_keep_cats(tmp_path: Path) -> None:
    path = _oxford_list(
        tmp_path,
        "pug_1 30 2 20",
        "german_shorthaired_3 17 2 9",
        "havanese_2 19 2 11",
        "american_bulldog_5 2 2 1",
        "Bengal_4 6 1 2",
    )
    rows = oxford_rows(path, BREEDS, photo_classes(BREEDS), ALIASES)
    got = [(r.path, r.class_index, r.breed, r.species) for r in rows]
    assert got == [
        ("pug_1.jpg", 2, "Pug", "dog"),
        ("german_shorthaired_3.jpg", 1, "German Shorthaired Pointer", "dog"),
        ("havanese_2.jpg", None, None, "dog"),  # listed in oxford_unmapped
        ("american_bulldog_5.jpg", None, None, "dog"),
        ("Bengal_4.jpg", None, None, "cat"),
    ]


def test_unknown_oxford_dog_breed_raises(tmp_path: Path) -> None:
    path = _oxford_list(tmp_path, "shiba_inu_1 24 2 15")
    with pytest.raises(MappingError, match="shiba_inu"):
        oxford_rows(path, BREEDS, photo_classes(BREEDS), ALIASES)


def test_write_splits_and_missing_images(tmp_path: Path) -> None:
    classes = photo_classes(BREEDS)
    rows = oxford_rows(_oxford_list(tmp_path, "pug_1 30 2 20"), BREEDS, classes, ALIASES)
    splits = Splits(classes=classes, stanford={"train": [], "val": [], "test": []}, oxford=rows)

    written = write_splits(splits, tmp_path / "splits")
    assert [p.name for p in written] == [
        "classes.csv",
        "stanford_train.csv",
        "stanford_val.csv",
        "stanford_test.csv",
        "oxford.csv",
    ]
    with (tmp_path / "splits" / "oxford.csv").open(encoding="utf-8") as f:
        assert list(csv.DictReader(f)) == [
            {
                "path": "pug_1.jpg",
                "class_index": "2",
                "breed": "Pug",
                "source_label": "pug",
                "species": "dog",
            }
        ]

    assert missing_images(tmp_path, splits) == [tmp_path / OXFORD_IMAGE_DIR / "pug_1.jpg"]
    (tmp_path / OXFORD_IMAGE_DIR).mkdir(parents=True)
    (tmp_path / OXFORD_IMAGE_DIR / "pug_1.jpg").write_bytes(b"")
    assert missing_images(tmp_path, splits) == []
    assert STANFORD_IMAGE_DIR.parts[0] == "stanford"
