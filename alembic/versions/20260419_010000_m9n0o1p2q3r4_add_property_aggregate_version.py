"""add properties.aggregate_version column

Monotonic per-Property counter, bumped inside every state-mutating use
case. The listings projector uses it as the idempotency source — events
with `source_aggregate_version` lower than the stored value are dropped.

Existing rows backfill to 0; the next state mutation on each Property
increments to 1. Future event consumers MUST handle rows starting at 1
(the original PROPERTY_CREATED under this spec is emitted at bump=1, not 0).

Revision ID: m9n0o1p2q3r4
Revises: l8m9n0o1p2q3
Create Date: 2026-04-19 01:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "m9n0o1p2q3r4"
down_revision: Union[str, Sequence[str], None] = "l8m9n0o1p2q3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column(
            "aggregate_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("properties", "aggregate_version")
