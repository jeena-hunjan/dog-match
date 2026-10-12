"""Hand-curated country breed laws.

- pipeline/country_restrictions.csv: one row per (country, breed) for breeds in our list,
  with a status ('banned' or 'restricted').
- pipeline/country_notes.csv: one row per country describing the parts of the law that
  name other breeds or types (e.g. the UK's XL Bully ban), shown with the app's
  "check local law" disclaimer.

Every row needs an ISO 3166-1 alpha-2 country, an https source URL and the date the
source was last checked.
"""

import csv
import re
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TypeVar

RESTRICTIONS_PATH = Path(__file__).with_name("country_restrictions.csv")
NOTES_PATH = Path(__file__).with_name("country_notes.csv")
STATUSES = frozenset({"banned", "restricted"})
_RESTRICTION_COLUMNS = ["country", "breed", "status", "source_url", "last_checked", "notes"]
_NOTE_COLUMNS = ["country", "note", "source_url", "last_checked"]
_COUNTRY = re.compile(r"[A-Z]{2}")

T = TypeVar("T")


class RestrictionsError(ValueError):
    pass


@dataclass(frozen=True)
class Restriction:
    country: str
    breed: str
    status: str
    source_url: str
    last_checked: date
    notes: str


@dataclass(frozen=True)
class CountryNote:
    country: str
    note: str
    source_url: str
    last_checked: date


def _common_fields(row: dict[str, str], today: date) -> tuple[str, str, date]:
    """Validate country, source_url and last_checked, shared by both files."""
    if not _COUNTRY.fullmatch(row["country"]):
        raise ValueError(f"country must be ISO alpha-2 in capitals, got {row['country']!r}")
    if not row["source_url"].startswith("https://"):
        raise ValueError(f"source_url must be https, got {row['source_url']!r}")
    try:
        checked = date.fromisoformat(row["last_checked"])
    except ValueError:
        raise ValueError(f"last_checked must be YYYY-MM-DD, got {row['last_checked']!r}") from None
    if checked > today:
        raise ValueError(f"last_checked {checked} is in the future")
    return row["country"], row["source_url"], checked


def _parse_restriction(row: dict[str, str], today: date) -> Restriction:
    country, url, checked = _common_fields(row, today)
    if row["status"] not in STATUSES:
        raise ValueError(f"status must be one of {sorted(STATUSES)}, got {row['status']!r}")
    if not row["breed"].strip():
        raise ValueError("breed is empty")
    return Restriction(
        country, row["breed"].strip(), row["status"], url, checked, row["notes"].strip()
    )


def _parse_note(row: dict[str, str], today: date) -> CountryNote:
    country, url, checked = _common_fields(row, today)
    if not row["note"].strip():
        raise ValueError("note is empty")
    return CountryNote(country, row["note"].strip(), url, checked)


def _load(
    path: Path,
    columns: list[str],
    parse: Callable[[dict[str, str], date], T],
    today: date | None,
) -> list[T]:
    today = today or date.today()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != columns:
            raise RestrictionsError(f"columns must be {columns}, got {reader.fieldnames}")
        rows = []
        # Line 1 is the header, so data rows start on line 2.
        for line, row in enumerate(reader, start=2):
            try:
                rows.append(parse(row, today))
            except ValueError as e:
                raise RestrictionsError(f"{path.name} line {line}: {e}") from None
    return rows


def _check_unique(keys: Iterable[tuple[str, ...]]) -> None:
    seen: set[tuple[str, ...]] = set()
    for key in keys:
        if key in seen:
            raise RestrictionsError(f"duplicate row for {' / '.join(key)}")
        seen.add(key)


def load_restrictions(
    path: Path = RESTRICTIONS_PATH, today: date | None = None
) -> list[Restriction]:
    restrictions = _load(path, _RESTRICTION_COLUMNS, _parse_restriction, today)
    _check_unique((r.country, r.breed) for r in restrictions)
    return restrictions


def load_country_notes(path: Path = NOTES_PATH, today: date | None = None) -> list[CountryNote]:
    notes = _load(path, _NOTE_COLUMNS, _parse_note, today)
    _check_unique((n.country,) for n in notes)
    return notes


def check_breeds(restrictions: Collection[Restriction], breed_names: Collection[str]) -> None:
    """Every restricted breed must be in the breed list, or the Postgres load would fail."""
    known = set(breed_names)
    unknown = sorted({r.breed for r in restrictions} - known)
    if unknown:
        raise RestrictionsError(f"breeds not in the breed list: {unknown}")
