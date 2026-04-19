"""identity split: drop users.organization_id, drop portal_users table

The admin/portal boundary is now derived from memberships at request
time (see IdentityMiddleware + RegisterAdminAccount). The
`users.organization_id` column is vestigial — memberships is the single
source of truth for which orgs a user belongs to. The `portal_users`
table is gone entirely (collapsed into `users`).

Pre-production migration: no data preservation. Dev DBs get nuked and
rebuilt. See spec: identity-context-split-and-membership-auth.md §Q4.

Revision ID: l8m9n0o1p2q3
Revises: k7l8m9n0o1p2
Create Date: 2026-04-19 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "l8m9n0o1p2q3"
down_revision: Union[str, Sequence[str], None] = "k7l8m9n0o1p2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Drop users.organization_id + its FK ──────────────────────────────
    # The FK constraint name follows Alembic/PostgreSQL's default naming —
    # `users_organization_id_fkey` — inspect with
    # `SELECT conname FROM pg_constraint WHERE conrelid = 'users'::regclass`
    # if this fails on the target DB.
    op.drop_constraint("users_organization_id_fkey", "users", type_="foreignkey")
    op.drop_column("users", "organization_id")

    # ── Drop portal_users table ──────────────────────────────────────────
    op.drop_table("portal_users")


def downgrade() -> None:
    # Dev-only downgrade — reverses the upgrade for local dev. Not
    # exercised in prod (per §Rollout: dev DBs are nuked and rebuilt).

    # ── Recreate portal_users ────────────────────────────────────────────
    op.create_table(
        "portal_users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("supabase_user_id", sa.Text, nullable=False, unique=True),
        sa.Column("email", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("phone_country_code", sa.Text),
        sa.Column("phone_number", sa.Text),
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
        sa.UniqueConstraint("supabase_user_id", name="uq_portal_users_supabase_user_id"),
        sa.UniqueConstraint("email", name="uq_portal_users_email"),
    )

    # ── Re-add users.organization_id column ──────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=False),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "users_organization_id_fkey",
        "users",
        "organizations",
        ["organization_id"],
        ["id"],
    )
