"""property_listings: drop postal_code

Revision ID: e6eb6e539aea
Revises: cd7dc6b929a3
Create Date: 2026-05-09 21:00:00.000000

Spec `2026-05-property-address-enrichment-fix.md` v5. The previous
migration (`cd7dc6b929a3`) added `postal_code` as a forward-scope
nullable column. We're dropping it: postal code is purely an input
signal to the LLM searcher (it helps resolve parish/municipality/
district from the postal-code prefix), not something we persist on
the row. It still rides on `PROPERTY_*` event payloads and into
`PROPERTY_LISTING_NEEDS_ADDRESS_ENRICHMENT.v1` — only the column
goes away.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6eb6e539aea"
down_revision: Union[str, Sequence[str], None] = "cd7dc6b929a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("property_listings", "postal_code")


def downgrade() -> None:
    op.add_column(
        "property_listings",
        sa.Column("postal_code", sa.Text(), nullable=True),
    )
