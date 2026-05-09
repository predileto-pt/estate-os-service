"""add property_pois table

Revision ID: 1a33edf53138
Revises: p2q3r4s5t6u7
Create Date: 2026-05-08 05:26:23.382247

ADR-010 §6.1. New table separate from property_amenities — different
shape (one row per POI vs one row per category-summary).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "1a33edf53138"
down_revision: Union[str, Sequence[str], None] = "p2q3r4s5t6u7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    poi_category = sa.Enum(
        "hospital",
        "bank",
        "grocery",
        "school",
        "pharmacy",
        "gym",
        "restaurant",
        "coffee_shop",
        "laundry",
        "gas_station",
        "public_transit",
        "kindergarten",
        "park",
        "post_office",
        "library",
        "shopping_mall",
        "bakery",
        "police_station",
        name="poi_category",
    )

    op.create_table(
        "property_pois",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("property_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("category", poi_category, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("distance_meters", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("place_type", sa.Text(), nullable=True),
        sa.Column("place_id", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            sa.dialects.postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "manually_edited",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "idx_property_pois_property_id",
        "property_pois",
        ["property_id"],
        unique=False,
    )
    op.create_index(
        "idx_property_pois_property_category",
        "property_pois",
        ["property_id", "category"],
        unique=False,
    )

    # Re-uses the existing trigger function defined in earlier migrations
    # (e.g. property_amenities migration).
    op.execute("""
        CREATE TRIGGER update_property_pois_updated_at
            BEFORE UPDATE ON property_pois
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)

    op.execute("ALTER TABLE property_pois ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY property_pois_service_role
        ON property_pois FOR ALL USING (auth.role() = 'service_role');
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS property_pois_service_role ON property_pois")
    op.execute("DROP TRIGGER IF EXISTS update_property_pois_updated_at ON property_pois")
    op.drop_index("idx_property_pois_property_category", table_name="property_pois")
    op.drop_index("idx_property_pois_property_id", table_name="property_pois")
    op.drop_table("property_pois")
    op.execute("DROP TYPE IF EXISTS poi_category")
