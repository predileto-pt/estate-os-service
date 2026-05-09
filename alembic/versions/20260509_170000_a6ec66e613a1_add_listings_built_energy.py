"""add built_at + energy_rating to property_listings

Revision ID: a6ec66e613a1
Revises: fc1250e0b892
Create Date: 2026-05-09 17:00:00.000000

Spec `2026-05-listing-semantic-search`. The canonical-text composer
renders `BUILT: <year_built> · energy <energy_rating>`. Both fields
already travel in the `characteristics` dict on `PROPERTY_*.v1`
snapshots; this migration just lets the projector persist them on the
read-model so the composer doesn't need to refetch the source row.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6ec66e613a1"
down_revision: Union[str, Sequence[str], None] = "fc1250e0b892"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "property_listings",
        sa.Column("built_at", sa.Integer(), nullable=True),
    )
    op.add_column(
        "property_listings",
        sa.Column("energy_rating", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("property_listings", "energy_rating")
    op.drop_column("property_listings", "built_at")
