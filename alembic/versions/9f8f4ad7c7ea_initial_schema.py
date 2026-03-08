"""initial schema

Revision ID: 9f8f4ad7c7ea
Revises:
Create Date: 2026-03-06

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9f8f4ad7c7ea"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- Enums ----------------------------------------------------------------
    subscription_plan = postgresql.ENUM(
        "freemium", "pro", "enterprise", name="subscription_plan", create_type=False
    )
    subscription_type = postgresql.ENUM(
        "stripe", "manual", "deposit", name="subscription_type", create_type=False
    )
    subscription_status = postgresql.ENUM(
        "active", "cancelled", "past_due", "trialing", "inactive",
        name="subscription_status", create_type=False,
    )
    notification_status = postgresql.ENUM(
        "unread", "read", name="notification_status", create_type=False
    )

    subscription_plan.create(op.get_bind(), checkfirst=True)
    subscription_type.create(op.get_bind(), checkfirst=True)
    subscription_status.create(op.get_bind(), checkfirst=True)
    notification_status.create(op.get_bind(), checkfirst=True)

    # -- companies ------------------------------------------------------------
    op.create_table(
        "companies",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("nif", sa.Text(), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    # -- users ----------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("supabase_user_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("phone_country_code", sa.Text(), nullable=True),
        sa.Column("phone_number", sa.Text(), nullable=True),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("google_metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supabase_user_id"),
        sa.UniqueConstraint("email"),
    )

    # -- subscriptions --------------------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("company_id", sa.UUID(), sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("plan", subscription_plan, server_default="freemium", nullable=False),
        sa.Column("type", subscription_type, nullable=False),
        sa.Column("status", subscription_status, server_default="active", nullable=False),
        sa.Column("stripe_subscription_id", sa.Text(), nullable=True),
        sa.Column("stripe_price_id", sa.Text(), nullable=True),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    # -- notifications --------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", notification_status, server_default="unread", nullable=False),
        sa.Column("channel", sa.Text(), server_default="in_app", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_notifications_user_status", "notifications", ["user_id", "status"])

    # -- Triggers (not modeled by SQLAlchemy) ---------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_companies_updated_at
            BEFORE UPDATE ON companies
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    op.execute("""
        CREATE TRIGGER trg_users_updated_at
            BEFORE UPDATE ON users
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    op.execute("""
        CREATE TRIGGER trg_subscriptions_updated_at
            BEFORE UPDATE ON subscriptions
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)

    # -- RLS (Supabase) -------------------------------------------------------
    op.execute("ALTER TABLE companies ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;")

    op.execute("""
        CREATE POLICY "Service role can manage companies"
            ON companies FOR ALL USING (auth.role() = 'service_role');
    """)
    op.execute("""
        CREATE POLICY "Users can manage their own company"
            ON companies FOR ALL
            USING (auth.uid() = user_id)
            WITH CHECK (auth.uid() = user_id);
    """)

    op.execute("""
        CREATE POLICY "Users can view own record"
            ON users FOR SELECT USING (supabase_user_id = auth.uid()::text);
    """)
    op.execute("""
        CREATE POLICY "Users can update own record"
            ON users FOR UPDATE USING (supabase_user_id = auth.uid()::text);
    """)
    op.execute("""
        CREATE POLICY "Service role can manage users"
            ON users FOR ALL USING (auth.role() = 'service_role');
    """)

    op.execute("""
        CREATE POLICY "Service role can manage subscriptions"
            ON subscriptions FOR ALL USING (auth.role() = 'service_role');
    """)

    op.execute("""
        CREATE POLICY "Users can view own notifications"
            ON notifications FOR SELECT
            USING (user_id IN (SELECT id FROM users WHERE supabase_user_id = auth.uid()::text));
    """)
    op.execute("""
        CREATE POLICY "Service role can manage notifications"
            ON notifications FOR ALL USING (auth.role() = 'service_role');
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS \"Service role can manage notifications\" ON notifications;")
    op.execute("DROP POLICY IF EXISTS \"Users can view own notifications\" ON notifications;")
    op.execute("DROP POLICY IF EXISTS \"Service role can manage subscriptions\" ON subscriptions;")
    op.execute("DROP POLICY IF EXISTS \"Service role can manage users\" ON users;")
    op.execute("DROP POLICY IF EXISTS \"Users can update own record\" ON users;")
    op.execute("DROP POLICY IF EXISTS \"Users can view own record\" ON users;")
    op.execute("DROP POLICY IF EXISTS \"Users can manage their own company\" ON companies;")
    op.execute("DROP POLICY IF EXISTS \"Service role can manage companies\" ON companies;")

    op.execute("DROP TRIGGER IF EXISTS trg_subscriptions_updated_at ON subscriptions;")
    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON users;")
    op.execute("DROP TRIGGER IF EXISTS trg_companies_updated_at ON companies;")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column();")

    op.drop_index("idx_notifications_user_status", "notifications")
    op.drop_table("notifications")
    op.drop_table("subscriptions")
    op.drop_table("users")
    op.drop_table("companies")

    op.execute("DROP TYPE IF EXISTS notification_status;")
    op.execute("DROP TYPE IF EXISTS subscription_status;")
    op.execute("DROP TYPE IF EXISTS subscription_type;")
    op.execute("DROP TYPE IF EXISTS subscription_plan;")
