"""store the raw Stripe event payload on stripe_webhook_events

Audit trail / debug aid. The idempotency row already recorded that an
event was processed; now it also carries the decoded Stripe event
envelope so we can inspect what actually arrived.

`payload` is JSONB NOT NULL with a `'{}'` default so existing rows
(if any; the table was only added in migration o1p2q3r4s5t6 and the
production repo was in-memory until now) satisfy the constraint on
upgrade. The default is dropped immediately afterwards so future
inserts must supply a payload.

Revision ID: p2q3r4s5t6u7
Revises: o1p2q3r4s5t6
Create Date: 2026-04-22 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "p2q3r4s5t6u7"
down_revision: Union[str, Sequence[str], None] = "o1p2q3r4s5t6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stripe_webhook_events",
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.alter_column("stripe_webhook_events", "payload", server_default=None)


def downgrade() -> None:
    op.drop_column("stripe_webhook_events", "payload")
