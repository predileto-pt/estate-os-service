"""create property_listings read-model table

Populated by the listings projector from carried-state PROPERTY_*
events (see `src/listings/adapters/workers/`). Distinct from the
legacy `ReadPropertyModel` view over `properties` — this is a
separate physical table with denormalised columns for cheap filtering
and a compound pagination index.

Revision ID: n0o1p2q3r4s5
Revises: m9n0o1p2q3r4
Create Date: 2026-04-19 02:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "n0o1p2q3r4s5"
down_revision: Union[str, Sequence[str], None] = "m9n0o1p2q3r4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "property_listings",
        sa.Column("id", postgresql.UUID(as_uuid=False), primary_key=True),
        sa.Column("organization_id", postgresql.UUID(as_uuid=False), nullable=False),
        # Enums are pre-existing (created in the initial properties migration);
        # we reuse them via create_type=False on the ORM side. Alembic here
        # references the existing type by name so we don't try to re-create.
        sa.Column(
            "status",
            postgresql.ENUM(
                "draft",
                "active",
                "sold",
                "rented",
                "withdrawn",
                name="property_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "listing_type",
            postgresql.ENUM(
                "sale", "purchase", name="listing_type", create_type=False
            ),
            nullable=False,
        ),
        sa.Column(
            "typology",
            postgresql.ENUM(
                "house", "apartment", "land", "ruin", name="typology", create_type=False
            ),
            nullable=False,
        ),
        sa.Column("address", sa.Text, nullable=False),
        sa.Column("parish", sa.Text, nullable=True),
        sa.Column("municipality", sa.Text, nullable=True),
        sa.Column("district", sa.Text, nullable=True),
        sa.Column("location_enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "location_enrichment_attempts",
            sa.Integer,
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("num_of_bedrooms", sa.Integer, nullable=True),
        sa.Column("num_of_bathrooms", sa.Integer, nullable=True),
        sa.Column("area_in_m2", sa.Integer, nullable=True),
        sa.Column("has_pool", sa.Boolean, nullable=True),
        sa.Column("has_garden", sa.Boolean, nullable=True),
        sa.Column("has_elevator", sa.Boolean, nullable=True),
        sa.Column("min_price", sa.Numeric(12, 2), nullable=True),
        sa.Column("first_image_s3_key", sa.Text, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
        sa.Column("source_aggregate_version", sa.Integer, nullable=False),
        sa.Column(
            "source_occurred_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # Indexed columns for filter predicates.
    for col in (
        "organization_id",
        "status",
        "listing_type",
        "typology",
        "parish",
        "municipality",
        "district",
        "num_of_bedrooms",
        "num_of_bathrooms",
        "area_in_m2",
        "has_pool",
        "has_garden",
        "has_elevator",
        "min_price",
    ):
        op.create_index(
            f"idx_property_listings_{col}", "property_listings", [col]
        )

    # Compound index for cursor pagination (ORDER BY created_at DESC, id DESC
    # within a status filter). Supports the follow-on
    # `listings-cursor-pagination-and-filters` spec.
    op.create_index(
        "idx_property_listings_pagination",
        "property_listings",
        ["status", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("idx_property_listings_pagination", table_name="property_listings")
    for col in (
        "organization_id",
        "status",
        "listing_type",
        "typology",
        "parish",
        "municipality",
        "district",
        "num_of_bedrooms",
        "num_of_bathrooms",
        "area_in_m2",
        "has_pool",
        "has_garden",
        "has_elevator",
        "min_price",
    ):
        op.drop_index(f"idx_property_listings_{col}", table_name="property_listings")
    op.drop_table("property_listings")
