"""clear legacy property_images rows pointing at deleted bucket

Revision ID: e1f8c5a2b6d7
Revises: d6f7b2a4c8e1
Create Date: 2026-05-15 12:00:00

One-shot cleanup tied to spec `property-images-bucket-cdn`. Pre-Coolify
test data has `property_images.url` values pointing at the deleted
`estate-os-service-prod-property-documents` S3 bucket. The S3 bytes
were destroyed with the bucket; rewriting URLs would only yield a new
flavor of 404. Drop the rows so the new upload flow (private images
bucket + CloudFront CDN) repopulates from a clean state.

Safe in all data scenarios:
  - Empty table → no-op (idempotent).
  - Test rows from earlier dev → bytes are gone anyway.
  - Real production rows → confirmed not to exist yet (the Coolify
    deploy hasn't actually served traffic).

The DELETE is intentionally unconditional rather than a narrower
`WHERE url LIKE '%...-property-documents%'`. With no live data in the
table, narrowing buys nothing and complicates the migration.

Downgrade is a no-op — the original URLs pointed at a deleted bucket,
so there's nothing to restore. The migration is logically irreversible.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e1f8c5a2b6d7"
down_revision: Union[str, Sequence[str], None] = "d6f7b2a4c8e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM property_images")


def downgrade() -> None:
    # Intentionally a no-op. The pre-existing rows pointed at a deleted
    # S3 bucket; nothing to restore. If downgrade ever runs, the
    # property_images table simply stays empty.
    pass
