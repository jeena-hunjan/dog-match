"""Build the Dog Match dataset end to end: `make data` (python -m pipeline.build_dataset).

Re-runnable: downloads are cached in data/raw/ and only fetched again with --force.
Steps so far: download sources, map breed names across sources (data/interim/),
validate the curated country restrictions.
Later steps (splits, Postgres load, data card) are added here in order.
"""

import argparse
import logging
import os
from pathlib import Path

import requests

from pipeline.breed_mapping import Aliases, load_and_build, write_outputs
from pipeline.download import download, write_manifest
from pipeline.restrictions import check_breeds, load_restrictions
from pipeline.sources import BREED_SOURCES

log = logging.getLogger("pipeline")

DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_INTERIM_DIR = Path("data/interim")


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
    parser.add_argument("--force", action="store_true", help="re-download cached files")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    _use_system_certificates()
    _load_dotenv()

    with requests.Session() as session:
        results = [
            download(source, args.raw_dir, session, os.environ, force=args.force)
            for source in BREED_SOURCES
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


if __name__ == "__main__":
    main()
