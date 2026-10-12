"""Country restrictions CSV: the real file is valid, and bad rows are rejected."""

from datetime import date
from pathlib import Path

import pytest

from pipeline.restrictions import (
    RestrictionsError,
    check_breeds,
    load_restrictions,
)

HEADER = "country,breed,status,source_url,last_checked,notes\n"
GOOD = "DK,Boerboel,banned,https://example.gov/law,2026-10-01,note\n"
TODAY = date(2026, 10, 12)


def _write(tmp_path: Path, *rows: str, header: str = HEADER) -> Path:
    path = tmp_path / "restrictions.csv"
    path.write_text(header + "".join(rows), encoding="utf-8")
    return path


def test_real_file_is_valid() -> None:
    restrictions = load_restrictions()
    assert {r.country for r in restrictions} == {"GB", "IE", "DE", "FR", "DK"}
    assert all(r.notes for r in restrictions)


def test_parses_good_row(tmp_path: Path) -> None:
    [r] = load_restrictions(_write(tmp_path, GOOD), today=TODAY)
    assert (r.country, r.breed, r.status, r.last_checked) == (
        "DK",
        "Boerboel",
        "banned",
        date(2026, 10, 1),
    )


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("dk,Boerboel,banned,https://x.gov,2026-10-01,n\n", "country"),
        ("DNK,Boerboel,banned,https://x.gov,2026-10-01,n\n", "country"),
        ("DK,Boerboel,illegal,https://x.gov,2026-10-01,n\n", "status"),
        ("DK,Boerboel,banned,http://x.gov,2026-10-01,n\n", "https"),
        ("DK, ,banned,https://x.gov,2026-10-01,n\n", "breed is empty"),
        ("DK,Boerboel,banned,https://x.gov,01/10/2026,n\n", "YYYY-MM-DD"),
        ("DK,Boerboel,banned,https://x.gov,2026-12-01,n\n", "future"),
    ],
)
def test_bad_rows_are_rejected_with_line_number(tmp_path: Path, row: str, message: str) -> None:
    with pytest.raises(RestrictionsError, match=f"line 3: .*{message}"):
        load_restrictions(_write(tmp_path, GOOD, row), today=TODAY)


def test_duplicate_country_breed_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(RestrictionsError, match="duplicate"):
        load_restrictions(_write(tmp_path, GOOD, GOOD), today=TODAY)


def test_wrong_columns_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(RestrictionsError, match="columns"):
        load_restrictions(_write(tmp_path, GOOD, header="country,breed,status\n"), today=TODAY)


def test_check_breeds_rejects_unknown_names(tmp_path: Path) -> None:
    restrictions = load_restrictions(_write(tmp_path, GOOD), today=TODAY)
    check_breeds(restrictions, ["Boerboel", "Beagle"])
    with pytest.raises(RestrictionsError, match="Boerboel"):
        check_breeds(restrictions, ["Beagle"])
