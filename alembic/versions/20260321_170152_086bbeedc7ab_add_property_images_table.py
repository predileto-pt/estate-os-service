"""add property_images table

Revision ID: 086bbeedc7ab
Revises: dc227c647f8c
Create Date: 2026-03-21 16:45:05.636327

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "086bbeedc7ab"
down_revision: Union[str, Sequence[str], None] = "dc227c647f8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "property_images",
        sa.Column(
            "id",
            sa.UUID(as_uuid=False),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("property_id", sa.UUID(as_uuid=False), nullable=False),
        sa.Column("s3_key", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["property_id"],
            ["properties.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_property_images_property_id", "property_images", ["property_id"], unique=False
    )

    # updated_at trigger
    op.execute("""
        CREATE TRIGGER update_property_images_updated_at
            BEFORE UPDATE ON property_images
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column();
    """)

    # Row-level security
    op.execute("ALTER TABLE property_images ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY property_images_service_role
        ON property_images FOR ALL USING (auth.role() = 'service_role');
    """)
    op.execute("""
        CREATE POLICY property_images_org_isolation ON property_images
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
    op.execute("DROP POLICY IF EXISTS property_images_org_isolation ON property_images")
    op.execute("DROP POLICY IF EXISTS property_images_service_role ON property_images")
    op.execute("DROP TRIGGER IF EXISTS update_property_images_updated_at ON property_images")
    op.drop_index("idx_property_images_property_id", table_name="property_images")
    op.drop_table("property_images")
