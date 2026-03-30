"""rename companies to organizations, add memberships and invitations

Revision ID: c1a2b3c4d5e6
Revises: b9d4e5f6a012
Create Date: 2026-03-17

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "c1a2b3c4d5e6"
down_revision: Union[str, None] = "b9d4e5f6a012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Drop existing RLS policies referencing companies ──────────────────
    op.execute("DROP POLICY IF EXISTS companies_select_policy ON companies")
    op.execute("DROP POLICY IF EXISTS companies_insert_policy ON companies")
    op.execute("DROP POLICY IF EXISTS companies_update_policy ON companies")
    op.execute("DROP POLICY IF EXISTS subscriptions_select_policy ON subscriptions")
    op.execute("DROP POLICY IF EXISTS subscriptions_insert_policy ON subscriptions")

    # ── 2. Rename table companies → organizations ────────────────────────────
    op.rename_table("companies", "organizations")

    # ── 3. Rename columns ────────────────────────────────────────────────────
    # organizations.user_id → organizations.created_by
    op.alter_column("organizations", "user_id", new_column_name="created_by")

    # users.company_id → users.organization_id (make nullable)
    # First drop the FK constraint
    op.drop_constraint("users_company_id_fkey", "users", type_="foreignkey")
    op.alter_column("users", "company_id", new_column_name="organization_id", nullable=True)
    op.create_foreign_key(
        "users_organization_id_fkey", "users", "organizations", ["organization_id"], ["id"]
    )

    # subscriptions.company_id → subscriptions.organization_id
    op.drop_constraint("subscriptions_company_id_fkey", "subscriptions", type_="foreignkey")
    op.alter_column("subscriptions", "company_id", new_column_name="organization_id")
    op.create_foreign_key(
        "subscriptions_organization_id_fkey",
        "subscriptions",
        "organizations",
        ["organization_id"],
        ["id"],
    )

    # ── 4. Create membership_role enum ───────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE membership_role AS ENUM ('owner', 'admin', 'member');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    # ── 5. Create invitation_status enum ─────────────────────────────────────
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE invitation_status AS ENUM ('pending', 'accepted', 'expired', 'revoked');
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )

    # ── 6. Create memberships table ──────────────────────────────────────────
    op.create_table(
        "memberships",
        sa.Column(
            "id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("user_id", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "organization_id",
            UUID(as_uuid=False),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column(
            "role",
            sa.Enum("owner", "admin", "member", name="membership_role", _create_events=False),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("user_id", "organization_id", name="uq_memberships_user_org"),
    )
    op.create_index("idx_memberships_organization_id", "memberships", ["organization_id"])

    # ── 7. Create invitations table ──────────────────────────────────────────
    op.create_table(
        "invitations",
        sa.Column(
            "id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "organization_id",
            UUID(as_uuid=False),
            sa.ForeignKey("organizations.id"),
            nullable=False,
        ),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column(
            "role",
            sa.Enum("owner", "admin", "member", name="membership_role", _create_events=False),
            nullable=False,
        ),
        sa.Column("invited_by", UUID(as_uuid=False), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token", sa.Text, nullable=False, unique=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "accepted",
                "expired",
                "revoked",
                name="invitation_status",
                _create_events=False,
            ),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("idx_invitations_email_status", "invitations", ["email", "status"])

    # ── 8. Data migration: create owner memberships for existing users ───────
    op.execute(
        """
        INSERT INTO memberships (id, user_id, organization_id, role, created_at, updated_at)
        SELECT gen_random_uuid(), u.id, u.organization_id, 'owner', now(), now()
        FROM users u
        WHERE u.organization_id IS NOT NULL
        """
    )

    # ── 9. updated_at trigger on memberships ─────────────────────────────────
    op.execute(
        """
        CREATE TRIGGER set_updated_at_memberships
            BEFORE UPDATE ON memberships
            FOR EACH ROW
            EXECUTE FUNCTION update_updated_at_column()
        """
    )

    # ── 10. RLS policies for renamed organizations table ─────────────────────
    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY organizations_select_policy ON organizations
            FOR SELECT USING (
                auth.role() = 'service_role'
                OR created_by = auth.uid()
                OR id IN (SELECT organization_id FROM memberships WHERE user_id IN (SELECT id FROM users WHERE supabase_user_id = auth.uid()::text))
            )
        """
    )
    op.execute(
        """
        CREATE POLICY organizations_insert_policy ON organizations
            FOR INSERT WITH CHECK (auth.role() = 'service_role' OR created_by = auth.uid())
        """
    )
    op.execute(
        """
        CREATE POLICY organizations_update_policy ON organizations
            FOR UPDATE USING (
                auth.role() = 'service_role'
                OR created_by = auth.uid()
                OR id IN (SELECT organization_id FROM memberships WHERE user_id IN (SELECT id FROM users WHERE supabase_user_id = auth.uid()::text))
            )
        """
    )

    # ── 11. Update subscriptions RLS policies ────────────────────────────────
    op.execute(
        """
        CREATE POLICY subscriptions_select_policy ON subscriptions
            FOR SELECT USING (
                auth.role() = 'service_role'
                OR organization_id IN (SELECT organization_id FROM memberships WHERE user_id IN (SELECT id FROM users WHERE supabase_user_id = auth.uid()::text))
            )
        """
    )
    op.execute(
        """
        CREATE POLICY subscriptions_insert_policy ON subscriptions
            FOR INSERT WITH CHECK (
                auth.role() = 'service_role'
                OR organization_id IN (SELECT organization_id FROM memberships WHERE user_id IN (SELECT id FROM users WHERE supabase_user_id = auth.uid()::text))
            )
        """
    )

    # ── 12. RLS policies for memberships ─────────────────────────────────────
    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY memberships_select_policy ON memberships
            FOR SELECT USING (
                auth.role() = 'service_role'
                OR organization_id IN (SELECT organization_id FROM memberships m2 WHERE m2.user_id IN (SELECT id FROM users WHERE supabase_user_id = auth.uid()::text))
            )
        """
    )
    op.execute(
        """
        CREATE POLICY memberships_all_policy ON memberships
            FOR ALL USING (auth.role() = 'service_role')
        """
    )

    # ── 13. RLS policies for invitations ─────────────────────────────────────
    op.execute("ALTER TABLE invitations ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY invitations_select_policy ON invitations
            FOR SELECT USING (
                auth.role() = 'service_role'
                OR organization_id IN (SELECT organization_id FROM memberships WHERE user_id IN (SELECT id FROM users WHERE supabase_user_id = auth.uid()::text))
            )
        """
    )
    op.execute(
        """
        CREATE POLICY invitations_all_policy ON invitations
            FOR ALL USING (auth.role() = 'service_role')
        """
    )


def downgrade() -> None:
    # Drop new tables
    op.drop_table("invitations")
    op.drop_table("memberships")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS invitation_status")
    op.execute("DROP TYPE IF EXISTS membership_role")

    # Reverse column renames
    op.drop_constraint("subscriptions_organization_id_fkey", "subscriptions", type_="foreignkey")
    op.alter_column("subscriptions", "organization_id", new_column_name="company_id")
    op.create_foreign_key(
        "subscriptions_company_id_fkey", "subscriptions", "organizations", ["company_id"], ["id"]
    )

    op.drop_constraint("users_organization_id_fkey", "users", type_="foreignkey")
    op.alter_column("users", "organization_id", new_column_name="company_id", nullable=False)
    op.create_foreign_key("users_company_id_fkey", "users", "organizations", ["company_id"], ["id"])

    op.alter_column("organizations", "created_by", new_column_name="user_id")

    # Rename table back
    op.rename_table("organizations", "companies")
