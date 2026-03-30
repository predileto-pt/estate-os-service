"""add property_prices table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    listing_type = postgresql.ENUM("sale", "purchase", name="listing_type", create_type=False)

    op.create_table(
        "property_prices",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("property_id", sa.UUID(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("listing_type", listing_type, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_property_prices_property_id", "property_prices", ["property_id"])

    op.execute("""
        CREATE TRIGGER trg_property_prices_updated_at
            BEFORE UPDATE ON property_prices
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    op.execute("ALTER TABLE property_prices ENABLE ROW LEVEL SECURITY;")

    op.execute("""
        CREATE POLICY "Service role can manage property_prices"
            ON property_prices FOR ALL USING (auth.role() = 'service_role');
    """)
    op.execute("""
        CREATE POLICY "Users can manage property prices via their property"
            ON property_prices FOR ALL
            USING (property_id IN (SELECT id FROM properties WHERE organization_id IN (SELECT id FROM organizations)))
            WITH CHECK (property_id IN (SELECT id FROM properties WHERE organization_id IN (SELECT id FROM organizations)));
    """)


def downgrade() -> None:
    op.execute(
        'DROP POLICY IF EXISTS "Users can manage property prices via their property"'
        " ON property_prices;"
    )
    op.execute(
        'DROP POLICY IF EXISTS "Service role can manage property_prices" ON property_prices;'
    )
    op.execute("DROP TRIGGER IF EXISTS trg_property_prices_updated_at ON property_prices;")
    op.drop_index("idx_property_prices_property_id", "property_prices")
    op.drop_table("property_prices")
