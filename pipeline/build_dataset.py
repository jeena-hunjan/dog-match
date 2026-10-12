"""Build the Dog Match dataset end to end: `make data` (python -m pipeline.build_dataset).

Re-runnable: downloads are cached in data/raw/ and only fetched again with --force.
Steps: download sources, map breed names across sources (data/interim/), validate the
curated country restrictions, write image split manifests (data/splits/), load breeds,
traits, sizes and restrictions into Postgres (DATABASE_URL).
The data card step is added next.

--skip-images skips the ~1.6 GB image downloads and the split manifests.
--no-db skips the Postgres load.
"""

import argparse
import csv
import json
import logging
import os
from collections.abc import Sequence
from pathlib import Path

import requests

from pipeline.breed_data import (
    BreedRecord,
    TraitRecord,
    breed_records,
    load_manual_sizes,
    size_problems,
    trait_records,
)
from pipeline.breed_mapping import Aliases, Breed, load_and_build, write_outputs
from pipeline.download import download, write_manifest
from pipeline.restrictions import Restriction, check_breeds, load_restrictions
from pipeline.sources import BREED_SOURCES, IMAGE_SOURCES
from pipeline.splits import build_splits, missing_images, write_splits

log = logging.getLogger("pipeline")

DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_INTERIM_DIR = Path("data/interim")
DEFAULT_SPLITS_DIR = Path("data/splits")


def _use_system_certificates() -> None:
    """Verify TLS against the OS certificate store instead of certifi's bundle.

    Needed on machines where antivirus or a corporate proxy re-signs HTTPS traffic with a
    root that only the OS trusts. Verification stays on either way.
    """
    try:
        import truststore
    except ImportError:  # pragma: no cover - truststore is optional
        return
    truststore.inject_into_ssl()


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - python-dotenv is optional
        return
    load_dotenv()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--interim-dir", type=Path, default=DEFAULT_INTERIM_DIR)
    parser.add_argument("--splits-dir", type=Path, default=DEFAULT_SPLITS_DIR)
    parser.add_argument("--force", action="store_true", help="re-download cached files")
    parser.add_argument("--skip-images", action="store_true", help="no image downloads or splits")
    parser.add_argument("--no-db", action="store_true", help="do not load Postgres")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    _use_system_certificates()
    _load_dotenv()

    sources = BREED_SOURCES if args.skip_images else BREED_SOURCES + IMAGE_SOURCES
    with requests.Session() as session:
        results = [
            download(source, args.raw_dir, session, os.environ, force=args.force)
            for source in sources
        ]
    for r in results:
        status = "cached" if r.cached else "downloaded"
        log.info("%-24s %-10s %9d bytes  %s", r.source.name, status, r.size_bytes, r.path)
    log.info("manifest written to %s", write_manifest(args.raw_dir, results))

    mapping = load_and_build(args.raw_dir, Aliases.load())
    breeds_csv, report = write_outputs(mapping, args.interim_dir)
    log.info(
        "%d breeds (%d with a photo class, %d with TheDogAPI sizes) -> %s; report: %s",
        len(mapping.breeds),
        len(mapping.photo_breeds),
        sum(b.dog_api_id is not None for b in mapping.breeds),
        breeds_csv,
        report,
    )

    restrictions = load_restrictions()
    check_breeds(restrictions, [b.name for b in mapping.breeds])
    countries = sorted({r.country for r in restrictions})
    log.info("%d country restrictions valid (%s)", len(restrictions), ", ".join(countries))

    if args.skip_images:
        log.info("--skip-images: image splits not rebuilt")
    else:
        _build_splits(args, mapping.breeds)

    with (args.raw_dir / "akc" / "breed_traits.csv").open(newline="", encoding="utf-8") as f:
        akc_rows = list(csv.DictReader(f))
    dog_api = json.loads((args.raw_dir / "dog_api" / "breeds.json").read_text(encoding="utf-8"))
    records = breed_records(mapping.breeds, dog_api, load_manual_sizes())
    traits, dropped = trait_records(akc_rows, mapping.breeds)
    gaps = size_problems(records)
    log.info("%d size gaps (listed in the data card), e.g. %s", len(gaps), gaps[:1])
    if dropped:
        log.warning("dropped %d trait scores outside 1-5: %s ...", len(dropped), dropped[0])

    if args.no_db:
        log.info("--no-db: Postgres not loaded")
    else:
        _load_postgres(records, traits, restrictions)


def _build_splits(args: argparse.Namespace, breeds: Sequence[Breed]) -> None:
    splits = build_splits(args.raw_dir, breeds, Aliases.load())
    missing = missing_images(args.raw_dir, splits)
    if missing:
        raise SystemExit(f"{len(missing)} images in the manifests are missing, e.g. {missing[0]}")
    write_splits(splits, args.splits_dir)
    sizes = {name: len(rows) for name, rows in splits.stanford.items()}
    oxford_in_class = sum(r.class_index is not None for r in splits.oxford)
    log.info(
        "%d classes; Stanford train/val/test %d/%d/%d; Oxford %d images (%d of our classes) -> %s",
        len(splits.classes),
        sizes["train"],
        sizes["val"],
        sizes["test"],
        len(splits.oxford),
        oxford_in_class,
        args.splits_dir,
    )


def _load_postgres(
    records: Sequence[BreedRecord],
    traits: Sequence[TraitRecord],
    restrictions: Sequence[Restriction],
) -> None:
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import Session

    from app.db.session import get_engine
    from pipeline.load_db import load

    engine = get_engine()
    with Session(engine) as session, session.begin():
        summary = load(session, records, traits, restrictions)
    log.info(
        "Postgres (%s): %d breeds, %d traits, %d restrictions loaded",
        make_url(engine.url).host,
        summary.breeds,
        summary.traits,
        summary.restrictions,
    )
    if summary.stale_breeds:
        log.warning("breeds in Postgres but not in the sources: %s", summary.stale_breeds)


if __name__ == "__main__":
    main()
