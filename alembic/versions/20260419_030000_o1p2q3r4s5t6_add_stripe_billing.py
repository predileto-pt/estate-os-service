"""add Stripe billing columns and webhook idempotency table

- adds `stripe_customer_id` to `subscriptions` (nullable) with a partial
  index used to reverse-look-up the org from a Stripe webhook payload.
- creates `stripe_webhook_events` (event_id PK) so webhook replays are
  idempotent — handler inserts first, applies side effects once.

Revision ID: o1p2q3r4s5t6
Revises: n0o1p2q3r4s5
Create Date: 2026-04-19 03:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "o1p2q3r4s5t6"
down_revision: Union[str, Sequence[str], None] = "n0o1p2q3r4s5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("stripe_customer_id", sa.Text(), nullable=True),
    )
    op.create_index(
        "idx_subscriptions_stripe_customer_id",
        "subscriptions",
        ["stripe_customer_id"],
        postgresql_where=sa.text("stripe_customer_id IS NOT NULL"),
    )

    op.create_table(
        "stripe_webhook_events",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("stripe_webhook_events")
    op.drop_index("idx_subscriptions_stripe_customer_id", table_name="subscriptions")
    op.drop_column("subscriptions", "stripe_customer_id")
