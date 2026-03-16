"""add properties and property_owners

Revision ID: b3a1e7f2d456
Revises: 9f8f4ad7c7ea
Create Date: 2026-03-15

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b3a1e7f2d456"
down_revision: Union[str, None] = "9f8f4ad7c7ea"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Enums ----------------------------------------------------------------
    listing_type = postgresql.ENUM("sale", "rent", name="listing_type", create_type=False)
    typology = postgresql.ENUM(
        "apartment", "house", "land", "commercial", name="typology", create_type=False
    )
    property_status = postgresql.ENUM(
        "draft", "active", "sold", "rented", "withdrawn", name="property_status", create_type=False
    )
    civil_status = postgresql.ENUM(
        "single",
        "married",
        "divorced",
        "widowed",
        "civil_union",
        "separated",
        name="civil_status",
        create_type=False,
    )
    document_type = postgresql.ENUM(
        "cartao_cidadao", "passport", name="document_type", create_type=False
    )

    listing_type.create(op.get_bind(), checkfirst=True)
    typology.create(op.get_bind(), checkfirst=True)
    property_status.create(op.get_bind(), checkfirst=True)
    civil_status.create(op.get_bind(), checkfirst=True)
    document_type.create(op.get_bind(), checkfirst=True)

    # -- properties -----------------------------------------------------------
    op.create_table(
        "properties",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("listing_type", listing_type, nullable=False),
        sa.Column("typology", typology, nullable=False),
        sa.Column("status", property_status, server_default="draft", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_properties_user_id", "properties", ["user_id"])

    # -- property_owners ------------------------------------------------------
    op.create_table(
        "property_owners",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("property_id", sa.UUID(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column("civil_status", civil_status, nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("nif", sa.Text(), nullable=False),
        sa.Column("document_type", document_type, nullable=False),
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("issued_by", sa.Text(), nullable=False),
        sa.Column("issuing_district", sa.Text(), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_property_owners_property_id", "property_owners", ["property_id"])

    # -- Triggers (reuse existing update_updated_at_column function) ----------
    op.execute("""
        CREATE TRIGGER trg_properties_updated_at
            BEFORE UPDATE ON properties
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    op.execute("""
        CREATE TRIGGER trg_property_owners_updated_at
            BEFORE UPDATE ON property_owners
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # -- RLS (Supabase) -------------------------------------------------------
    op.execute("ALTER TABLE properties ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE property_owners ENABLE ROW LEVEL SECURITY;")

    op.execute("""
        CREATE POLICY "Service role can manage properties"
            ON properties FOR ALL USING (auth.role() = 'service_role');
    """)
    op.execute("""
        CREATE POLICY "Users can manage their own properties"
            ON properties FOR ALL
            USING (user_id = auth.uid())
            WITH CHECK (user_id = auth.uid());
    """)

    op.execute("""
        CREATE POLICY "Service role can manage property_owners"
            ON property_owners FOR ALL USING (auth.role() = 'service_role');
    """)
    op.execute("""
        CREATE POLICY "Users can manage property owners via their property"
            ON property_owners FOR ALL
            USING (property_id IN (SELECT id FROM properties WHERE user_id = auth.uid()))
            WITH CHECK (property_id IN (SELECT id FROM properties WHERE user_id = auth.uid()));
    """)


def downgrade() -> None:
    # -- RLS policies ---------------------------------------------------------
    op.execute(
        'DROP POLICY IF EXISTS "Users can manage property owners via their property"'
        " ON property_owners;"
    )
    op.execute(
        'DROP POLICY IF EXISTS "Service role can manage property_owners" ON property_owners;'
    )
    op.execute('DROP POLICY IF EXISTS "Users can manage their own properties" ON properties;')
    op.execute('DROP POLICY IF EXISTS "Service role can manage properties" ON properties;')

    # -- Triggers -------------------------------------------------------------
    op.execute("DROP TRIGGER IF EXISTS trg_property_owners_updated_at ON property_owners;")
    op.execute("DROP TRIGGER IF EXISTS trg_properties_updated_at ON properties;")

    # -- Tables & indexes -----------------------------------------------------
    op.drop_index("idx_property_owners_property_id", "property_owners")
    op.drop_table("property_owners")
    op.drop_index("idx_properties_user_id", "properties")
    op.drop_table("properties")

    # -- Enums ----------------------------------------------------------------
    op.execute("DROP TYPE IF EXISTS document_type;")
    op.execute("DROP TYPE IF EXISTS civil_status;")
    op.execute("DROP TYPE IF EXISTS property_status;")
    op.execute("DROP TYPE IF EXISTS typology;")
    op.execute("DROP TYPE IF EXISTS listing_type;")
