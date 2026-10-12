"""SQLAlchemy models. Keep in sync with the Alembic migrations in `migrations/versions/`."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Breed(Base):
    __tablename__ = "breeds"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True)
    stanford_label: Mapped[str | None] = mapped_column(Text, unique=True)
    # TheDogAPI gives ranges, so size and lifespan are stored as min/max pairs.
    weight_min_kg: Mapped[float | None] = mapped_column(Float)
    weight_max_kg: Mapped[float | None] = mapped_column(Float)
    height_min_cm: Mapped[float | None] = mapped_column(Float)
    height_max_cm: Mapped[float | None] = mapped_column(Float)
    lifespan_min_years: Mapped[float | None] = mapped_column(Float)
    lifespan_max_years: Mapped[float | None] = mapped_column(Float)


class BreedTrait(Base):
    __tablename__ = "breed_traits"
    __table_args__ = (CheckConstraint("score BETWEEN 1 AND 5", name="score_range"),)

    breed_id: Mapped[int] = mapped_column(
        ForeignKey("breeds.id", ondelete="CASCADE"), primary_key=True
    )
    trait: Mapped[str] = mapped_column(Text, primary_key=True)
    score: Mapped[int] = mapped_column(SmallInteger)


class CountryRestriction(Base):
    __tablename__ = "country_restrictions"
    __table_args__ = (
        UniqueConstraint("country", "breed_id"),
        CheckConstraint("status IN ('banned', 'restricted')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    country: Mapped[str] = mapped_column(CHAR(2))  # ISO 3166-1 alpha-2
    breed_id: Mapped[int] = mapped_column(ForeignKey("breeds.id"))
    status: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    last_checked: Mapped[date] = mapped_column(Date)


class Request(Base):
    __tablename__ = "requests"
    __table_args__ = (CheckConstraint("confidence BETWEEN 0 AND 1", name="confidence_range"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    profile: Mapped[dict[str, Any]] = mapped_column(JSONB)
    has_photo: Mapped[bool]
    predicted_breed_id: Mapped[int | None] = mapped_column(ForeignKey("breeds.id"))
    confidence: Mapped[float | None] = mapped_column(Float)
    abstained: Mapped[bool | None]
    latency_ms: Mapped[int]
    model_version: Mapped[str | None] = mapped_column(Text)


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint("rank BETWEEN 1 AND 5", name="rank_range"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score_range"),
    )

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("requests.id", ondelete="CASCADE"), primary_key=True
    )
    rank: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    breed_id: Mapped[int] = mapped_column(ForeignKey("breeds.id"))
    score: Mapped[float] = mapped_column(Float)


class Feedback(Base):
    __tablename__ = "feedback"
    __table_args__ = (CheckConstraint("rating IN (-1, 1)", name="rating_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"))
    rating: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
