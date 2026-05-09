"""drop property_amenities table

Revision ID: b58514282ab5
Revises: 1a33edf53138
Create Date: 2026-05-09 04:49:54.351967

Removes the legacy `property_amenities` surface superseded by
`property_pois` (ADR-010). The agent-button discovery flow has migrated
to `POST /api/v1/admin/properties/{id}/enrich`. Production data in
`property_amenities` is intentionally NOT migrated to `property_pois`
— different shapes (per-category summary vs row-per-POI), and the
agent re-runs `/enrich` on demand to populate the new catalog.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b58514282ab5"
down_revision: Union[str, Sequence[str], None] = "1a33edf53138"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the table, its triggers/policies, and the enum."""
    op.execute("DROP POLICY IF EXISTS property_amenities_service_role ON property_amenities")
    op.execute("DROP TRIGGER IF EXISTS update_property_amenities_updated_at ON property_amenities")
    op.drop_index("idx_property_amenities_property_id", table_name="property_amenities")
    op.drop_table("property_amenities")
    op.execute("DROP TYPE IF EXISTS amenity_category")


def downgrade() -> None:
    """Recreate the table to match its v3 shape (post place_id + top_places columns).

    Best-effort restore of structure only — production data is gone.
    Provided so a botched deploy can roll back the schema; the rows themselves
    cannot be recovered without a backup.
    """
    amenity_category = sa.Enum(
        "hospital",
        "bank",
        "grocery",
        "school",
        "laundry",
        "coffee_shop",
        "pharmacy",
        "gym",
        "restaurant",
        name="amenity_category",
    )

    op.create_table(
        "property_amenities",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("property_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("category", amenity_category, nullable=False),
        sa.Column("nearest_name", sa.Text(), nullable=False),
        sa.Column("nearest_distance_meters", sa.Float(), nullable=False),
        sa.Column("nearest_latitude", sa.Float(), nullable=False),
        sa.Column("nearest_longitude", sa.Float(), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False),
        sa.Column("nearest_place_id", sa.Text(), nullable=True),
        sa.Column("nearest_google_maps_url", sa.Text(), nullable=True),
        sa.Column(
            "top_places",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "property_id", "category", name="uq_property_amenities_property_category"
        ),
    )
    op.create_index(
        "idx_property_amenities_property_id",
        "property_amenities",
        ["property_id"],
        unique=False,
    )
    op.execute("""
        CREATE TRIGGER update_property_amenities_updated_at
            BEFORE UPDATE ON property_amenities
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)
    op.execute("ALTER TABLE property_amenities ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY property_amenities_service_role
        ON property_amenities FOR ALL USING (auth.role() = 'service_role');
    """)
