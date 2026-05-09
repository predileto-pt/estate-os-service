"""add embedding + pois columns to property_listings

Revision ID: fc1250e0b892
Revises: ecdb36cf8489
Create Date: 2026-05-09 16:00:00.000000

Spec `2026-05-listing-semantic-search` (ADR-013 phase 1). Adds:
  - `embedding_text_hash` (text, nullable) — SHA-256 of canonical text
  - `canonical_text_version` (text, nullable) — schema version (e.g. `v1`)
  - `embedding_model_version` (text, nullable) — embedding model id
  - `embedded_at` (timestamptz, nullable) — last successful upsert
  - `embedding_status` (text, NOT NULL default `'PENDING'`) — PENDING / INDEXED / FAILED
  - `pois` (jsonb, NOT NULL default `'[]'::jsonb`) — list of `{category, name, distance_meters}`

Plus a partial b-tree index supporting the ops dashboard query
`WHERE embedding_status != 'INDEXED'`.

Embedding columns are owned by the embedding handler, never the
projector — see the SET-clause exclusions in
`SqlAlchemyPropertyListingRepository.upsert_from_event`.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fc1250e0b892"
down_revision: Union[str, Sequence[str], None] = "ecdb36cf8489"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "property_listings",
        sa.Column("embedding_text_hash", sa.Text(), nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column("canonical_text_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column("embedding_model_version", sa.Text(), nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column("embedded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column(
            "embedding_status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
    )
    op.create_check_constraint(
        "ck_property_listings_embedding_status",
        "property_listings",
        "embedding_status IN ('PENDING', 'INDEXED', 'FAILED')",
    )
    op.add_column(
        "property_listings",
        sa.Column(
            "pois",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.create_index(
        "idx_property_listings_embedding_status_pending",
        "property_listings",
        ["embedding_status"],
        postgresql_where=sa.text("embedding_status != 'INDEXED'"),
    )


def downgrade() -> None:
    op.drop_index(
        "idx_property_listings_embedding_status_pending",
        table_name="property_listings",
    )
    op.drop_column("property_listings", "pois")
    op.drop_constraint(
        "ck_property_listings_embedding_status",
        "property_listings",
        type_="check",
    )
    op.drop_column("property_listings", "embedding_status")
    op.drop_column("property_listings", "embedded_at")
    op.drop_column("property_listings", "embedding_model_version")
    op.drop_column("property_listings", "canonical_text_version")
    op.drop_column("property_listings", "embedding_text_hash")
