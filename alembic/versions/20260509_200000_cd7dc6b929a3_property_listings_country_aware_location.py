"""property_listings: drop address; add country + forward-scope columns

Revision ID: cd7dc6b929a3
Revises: 104532849546
Create Date: 2026-05-09 20:00:00.000000

Spec: `2026-05-property-address-enrichment-fix.md`.

- DROP `address` (privacy: stops leaking exact street addresses to
  anonymous visitors of the public listings page).
- ADD `country` (NOT NULL DEFAULT 'Portugal') — Postgres applies the
  default to existing rows in the same ALTER TABLE.
- ADD `city`, `state`, `postal_code`, `region` (all nullable) for
  forward-scope multi-country support. Not written by anyone in v1.
- parish/municipality/district stay nullable. The "never null"
  invariant for Portuguese listings is enforced at the searcher level
  (PortugalAddressSearcher), not the schema, because future US
  listings will leave PT-shaped fields null and fill city/state.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cd7dc6b929a3"
down_revision: Union[str, Sequence[str], None] = "104532849546"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "property_listings",
        sa.Column(
            "country",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'Portugal'"),
            index=False,
        ),
    )
    op.add_column("property_listings", sa.Column("city", sa.Text(), nullable=True))
    op.add_column("property_listings", sa.Column("state", sa.Text(), nullable=True))
    op.add_column("property_listings", sa.Column("postal_code", sa.Text(), nullable=True))
    op.add_column("property_listings", sa.Column("region", sa.Text(), nullable=True))

    op.create_index("idx_property_listings_country", "property_listings", ["country"], unique=False)

    op.drop_column("property_listings", "address")


def downgrade() -> None:
    op.add_column(
        "property_listings",
        sa.Column("address", sa.Text(), nullable=False, server_default=sa.text("''")),
    )
    op.drop_index("idx_property_listings_country", table_name="property_listings")
    op.drop_column("property_listings", "region")
    op.drop_column("property_listings", "postal_code")
    op.drop_column("property_listings", "state")
    op.drop_column("property_listings", "city")
    op.drop_column("property_listings", "country")
