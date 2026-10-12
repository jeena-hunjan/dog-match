"""Build the Dog Match dataset end to end: `make data` (python -m pipeline.build_dataset).

Re-runnable: downloads are cached in data/raw/ and only fetched again with --force.
Later steps (name mapping, splits, Postgres load, data card) are added here in order.
"""

import argparse
import logging
import os
from pathlib import Path

import requests

from pipeline.download import download, write_manifest
from pipeline.sources import BREED_SOURCES

log = logging.getLogger("pipeline")

DEFAULT_RAW_DIR = Path("data/raw")


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


if __name__ == "__main__":
    main()
