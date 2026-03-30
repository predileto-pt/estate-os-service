"""add property_amenities table

Revision ID: e1f2a3b4c5d6
Revises: 086bbeedc7ab
Create Date: 2026-03-23 12:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "086bbeedc7ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "property_id", "category", name="uq_property_amenities_property_category"
        ),
    )
    op.create_index(
        "idx_property_amenities_property_id", "property_amenities", ["property_id"], unique=False
    )

    # updated_at trigger
    op.execute("""
        CREATE TRIGGER update_property_amenities_updated_at
            BEFORE UPDATE ON property_amenities
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)

    # Row-level security
    op.execute("ALTER TABLE property_amenities ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY property_amenities_service_role
        ON property_amenities FOR ALL USING (auth.role() = 'service_role');
    """)
    op.execute("""
        CREATE POLICY property_amenities_org_isolation ON property_amenities
        FOR ALL
        USING (
            property_id IN (
                SELECT id FROM properties WHERE organization_id IN (
                    SELECT organization_id FROM memberships WHERE user_id = auth.uid()
                )
            )
        );
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS property_amenities_org_isolation ON property_amenities")
    op.execute("DROP POLICY IF EXISTS property_amenities_service_role ON property_amenities")
    op.execute("DROP TRIGGER IF EXISTS update_property_amenities_updated_at ON property_amenities")
    op.drop_index("idx_property_amenities_property_id", table_name="property_amenities")
    op.drop_table("property_amenities")
    op.execute("DROP TYPE IF EXISTS amenity_category")
