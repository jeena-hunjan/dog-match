"""initial schema

Revision ID: 3f9c2a7d1e04
Revises:
Create Date: 2026-10-12 17:00:00

Hand-written to match app/db/models.py. Constraint names follow the naming convention
in app/db/base.py; they are spelled out with op.f() because op.create_table does not
apply the models' MetaData naming convention.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3f9c2a7d1e04"  # pragma: allowlist secret
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "breeds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("stanford_label", sa.Text(), nullable=True),
        sa.Column("weight_min_kg", sa.Float(), nullable=True),
        sa.Column("weight_max_kg", sa.Float(), nullable=True),
        sa.Column("height_min_cm", sa.Float(), nullable=True),
        sa.Column("height_max_cm", sa.Float(), nullable=True),
        sa.Column("lifespan_min_years", sa.Float(), nullable=True),
        sa.Column("lifespan_max_years", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_breeds")),
        sa.UniqueConstraint("name", name=op.f("uq_breeds_name")),
        sa.UniqueConstraint("stanford_label", name=op.f("uq_breeds_stanford_label")),
    )

    op.create_table(
        "breed_traits",
        sa.Column("breed_id", sa.Integer(), nullable=False),
        sa.Column("trait", sa.Text(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("score BETWEEN 1 AND 5", name=op.f("ck_breed_traits_score_range")),
        sa.ForeignKeyConstraint(
            ["breed_id"],
            ["breeds.id"],
            name=op.f("fk_breed_traits_breed_id_breeds"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("breed_id", "trait", name=op.f("pk_breed_traits")),
    )

    op.create_table(
        "country_restrictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("country", sa.CHAR(length=2), nullable=False),
        sa.Column("breed_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("last_checked", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "status IN ('banned', 'restricted')",
            name=op.f("ck_country_restrictions_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["breed_id"], ["breeds.id"], name=op.f("fk_country_restrictions_breed_id_breeds")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_country_restrictions")),
        sa.UniqueConstraint(
            "country", "breed_id", name=op.f("uq_country_restrictions_country_breed_id")
        ),
    )

    op.create_table(
        "requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("has_photo", sa.Boolean(), nullable=False),
        sa.Column("predicted_breed_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("abstained", sa.Boolean(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=True),
        sa.CheckConstraint("confidence BETWEEN 0 AND 1", name=op.f("ck_requests_confidence_range")),
        sa.ForeignKeyConstraint(
            ["predicted_breed_id"],
            ["breeds.id"],
            name=op.f("fk_requests_predicted_breed_id_breeds"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_requests")),
    )
    op.create_index(op.f("ix_requests_created_at"), "requests", ["created_at"], unique=False)

    op.create_table(
        "recommendations",
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("breed_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.CheckConstraint("rank BETWEEN 1 AND 5", name=op.f("ck_recommendations_rank_range")),
        sa.CheckConstraint("score BETWEEN 0 AND 100", name=op.f("ck_recommendations_score_range")),
        sa.ForeignKeyConstraint(
            ["breed_id"], ["breeds.id"], name=op.f("fk_recommendations_breed_id_breeds")
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_recommendations_request_id_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("request_id", "rank", name=op.f("pk_recommendations")),
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.SmallInteger(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rating IN (-1, 1)", name=op.f("ck_feedback_rating_valid")),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name=op.f("fk_feedback_request_id_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("feedback")
    op.drop_table("recommendations")
    op.drop_index(op.f("ix_requests_created_at"), table_name="requests")
    op.drop_table("requests")
    op.drop_table("country_restrictions")
    op.drop_table("breed_traits")
    op.drop_table("breeds")
