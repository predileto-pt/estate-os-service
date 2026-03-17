"""replace user_id with organization_id on properties, add organization_id to extraction_jobs

Revision ID: a1b2c3d4e5f6
Revises: f7b2c9d3e890
Create Date: 2026-03-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "f7b2c9d3e890"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- properties: rename user_id → organization_id, change FK --
    op.drop_index("idx_properties_user_id", table_name="properties")
    op.drop_constraint("properties_user_id_fkey", table_name="properties", type_="foreignkey")
    op.alter_column("properties", "user_id", new_column_name="organization_id")
    op.create_foreign_key(
        "properties_organization_id_fkey",
        "properties",
        "organizations",
        ["organization_id"],
        ["id"],
    )
    op.create_index("idx_properties_organization_id", "properties", ["organization_id"])

    # -- extraction_jobs: add organization_id column --
    op.add_column(
        "extraction_jobs",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=False),
            sa.ForeignKey("organizations.id"),
            nullable=True,
        ),
    )
    # Backfill: copy user_id into organization_id as a temporary measure
    # (in production, a data migration script should set correct org IDs)
    op.execute("UPDATE extraction_jobs SET organization_id = user_id WHERE organization_id IS NULL")
    op.alter_column("extraction_jobs", "organization_id", nullable=False)
    op.create_index("idx_extraction_jobs_organization_id", "extraction_jobs", ["organization_id"])


def downgrade() -> None:
    # -- extraction_jobs: drop organization_id --
    op.drop_index("idx_extraction_jobs_organization_id", table_name="extraction_jobs")
    op.drop_constraint(
        "extraction_jobs_organization_id_fkey", table_name="extraction_jobs", type_="foreignkey"
    )
    op.drop_column("extraction_jobs", "organization_id")

    # -- properties: rename organization_id → user_id, restore FK --
    op.drop_index("idx_properties_organization_id", table_name="properties")
    op.drop_constraint(
        "properties_organization_id_fkey", table_name="properties", type_="foreignkey"
    )
    op.alter_column("properties", "organization_id", new_column_name="user_id")
    op.create_foreign_key(
        "properties_user_id_fkey",
        "properties",
        "users",
        ["user_id"],
        ["id"],
    )
    op.create_index("idx_properties_user_id", "properties", ["user_id"])
