"""Hand-curated country breed restrictions (pipeline/country_restrictions.csv).

Every row needs an ISO 3166-1 alpha-2 country, a canonical breed name, a status
('banned' or 'restricted'), an https source URL and the date the source was last checked.
Rows only cover breeds in the canonical list; laws that name non-AKC types (e.g. the UK's
XL Bully) are described in the notes, and the app always says "check local law".
"""

import csv
import re
from collections.abc import Collection
from dataclasses import dataclass
from datetime import date
from pathlib import Path

RESTRICTIONS_PATH = Path(__file__).with_name("country_restrictions.csv")
STATUSES = frozenset({"banned", "restricted"})
_COLUMNS = ["country", "breed", "status", "source_url", "last_checked", "notes"]
_COUNTRY = re.compile(r"[A-Z]{2}")


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


def _parse_row(line: int, row: dict[str, str], today: date) -> Restriction:
    def fail(message: str) -> RestrictionsError:
        return RestrictionsError(f"line {line}: {message}")

    if not _COUNTRY.fullmatch(row["country"]):
        raise fail(f"country must be ISO alpha-2 in capitals, got {row['country']!r}")
    if row["status"] not in STATUSES:
        raise fail(f"status must be one of {sorted(STATUSES)}, got {row['status']!r}")
    if not row["source_url"].startswith("https://"):
        raise fail(f"source_url must be https, got {row['source_url']!r}")
    if not row["breed"].strip():
        raise fail("breed is empty")
    try:
        checked = date.fromisoformat(row["last_checked"])
    except ValueError:
        raise fail(f"last_checked must be YYYY-MM-DD, got {row['last_checked']!r}") from None
    if checked > today:
        raise fail(f"last_checked {checked} is in the future")
    return Restriction(
        country=row["country"],
        breed=row["breed"].strip(),
        status=row["status"],
        source_url=row["source_url"],
        last_checked=checked,
        notes=row["notes"].strip(),
    )


def load_restrictions(
    path: Path = RESTRICTIONS_PATH, today: date | None = None
) -> list[Restriction]:
    today = today or date.today()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != _COLUMNS:
            raise RestrictionsError(f"columns must be {_COLUMNS}, got {reader.fieldnames}")
        # Line 1 is the header, so data rows start on line 2.
        restrictions = [_parse_row(i, row, today) for i, row in enumerate(reader, start=2)]

    seen: set[tuple[str, str]] = set()
    for r in restrictions:
        if (r.country, r.breed) in seen:
            raise RestrictionsError(f"duplicate row for {r.country} / {r.breed}")
        seen.add((r.country, r.breed))
    return restrictions


def check_breeds(restrictions: Collection[Restriction], breed_names: Collection[str]) -> None:
    """Every restricted breed must be a canonical breed, or the Postgres load would drop it."""
    known = set(breed_names)
    unknown = sorted({r.breed for r in restrictions} - known)
    if unknown:
        raise RestrictionsError(f"breeds not in the canonical list: {unknown}")
