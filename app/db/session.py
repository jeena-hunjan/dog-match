"""Database URL handling, engine and session factory.

The URL comes from the DATABASE_URL environment variable (or `.env`, if python-dotenv
is installed). Neon and Heroku-style URLs (`postgres://`, `postgresql://`) are rewritten
to use the psycopg 3 driver; query params such as `sslmode=require` are kept as they are.
"""

import os
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is optional
    pass
else:
    load_dotenv()

_DRIVER_PREFIX = "postgresql+psycopg://"
_PLAIN_PREFIXES = ("postgresql://", "postgres://")


def normalize_database_url(url: str) -> str:
    """Point a plain Postgres URL at the psycopg 3 driver. Other URLs are returned unchanged."""
    for prefix in _PLAIN_PREFIXES:
        if url.startswith(prefix):
            return _DRIVER_PREFIX + url[len(prefix) :]
    return url


def get_database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set (see .env.example)")
    return normalize_database_url(url)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    # pool_pre_ping: Neon closes idle connections, and Cloud Run instances can sit idle.
    return create_engine(get_database_url(), pool_pre_ping=True)


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    with _session_factory()() as session:
        yield session
