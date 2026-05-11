"""add sessions table

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-05-11 00:00:01

Spec: 2026-05-portal-session-backend §4. Portal-DB only.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "sessions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=False),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=False), nullable=True),
        sa.Column(
            "favorites",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "prefs",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.CheckConstraint(
            "kind IN ('ANONYMOUS', 'AUTHENTICATED')",
            name="ck_sessions_kind",
        ),
    )
    op.create_index(
        "ix_sessions_user_id",
        "sessions",
        ["user_id"],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "ix_sessions_last_seen_at",
        "sessions",
        ["last_seen_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_last_seen_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
