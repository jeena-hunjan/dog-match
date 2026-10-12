"""Schema checks on the SQLAlchemy metadata. No database needed."""

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Table, UniqueConstraint

from app.db import Base
from app.db.session import normalize_database_url


def _table(name: str) -> Table:
    return Base.metadata.tables[name]


def _check_names(table: Table) -> set[str]:
    return {str(c.name) for c in table.constraints if isinstance(c, CheckConstraint)}


def _fk(table: Table, column: str) -> ForeignKeyConstraint:
    [fk] = [
        c
        for c in table.constraints
        if isinstance(c, ForeignKeyConstraint) and c.column_keys == [column]
    ]
    return fk


def test_metadata_has_exactly_the_six_tables() -> None:
    assert set(Base.metadata.tables) == {
        "breeds",
        "breed_traits",
        "country_restrictions",
        "requests",
        "recommendations",
        "feedback",
    }


def test_breed_trait_score_is_checked_1_to_5() -> None:
    table = _table("breed_traits")
    [check] = [
        c
        for c in table.constraints
        if isinstance(c, CheckConstraint) and c.name == "ck_breed_traits_score_range"
    ]
    assert "BETWEEN 1 AND 5" in str(check.sqltext)


def test_check_constraints_exist_with_deterministic_names() -> None:
    assert "ck_country_restrictions_status_valid" in _check_names(_table("country_restrictions"))
    assert "ck_requests_confidence_range" in _check_names(_table("requests"))
    assert _check_names(_table("recommendations")) >= {
        "ck_recommendations_rank_range",
        "ck_recommendations_score_range",
    }
    assert "ck_feedback_rating_valid" in _check_names(_table("feedback"))


def test_country_restrictions_unique_on_country_and_breed() -> None:
    uniques = [
        c for c in _table("country_restrictions").constraints if isinstance(c, UniqueConstraint)
    ]
    assert [(c.name, [col.name for col in c.columns]) for c in uniques] == [
        ("uq_country_restrictions_country_breed_id", ["country", "breed_id"])
    ]


def test_child_rows_cascade_on_delete() -> None:
    assert _fk(_table("breed_traits"), "breed_id").ondelete == "CASCADE"
    assert _fk(_table("recommendations"), "request_id").ondelete == "CASCADE"
    assert _fk(_table("feedback"), "request_id").ondelete == "CASCADE"


def test_primary_keys() -> None:
    assert [c.name for c in _table("breed_traits").primary_key] == ["breed_id", "trait"]
    assert [c.name for c in _table("recommendations").primary_key] == ["request_id", "rank"]


def test_requests_created_at_is_indexed() -> None:
    assert {ix.name for ix in _table("requests").indexes} == {"ix_requests_created_at"}


def test_normalize_database_url_uses_psycopg3_and_keeps_query() -> None:
    neon = "postgresql://u:p@ep-x.neon.tech/db?sslmode=require"
    assert (
        normalize_database_url(neon) == "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require"
    )
    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    already = "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url(already) == already
