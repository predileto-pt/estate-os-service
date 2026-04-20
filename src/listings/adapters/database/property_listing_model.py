"""SQLAlchemy model for the `property_listings` read-model table.

Populated by the projector (not by the write path). Columns include
denormalised location (parish/municipality/district), characteristic
snapshots (num_of_bedrooms, area_in_m2, has_pool, ...), a
min_price Decimal, and the thumbnail s3 key — all b-tree indexed where
filter-relevant.

Separate from `ReadPropertyModel` in `src/listings/adapters/database/models.py`
which is the legacy read mapping over the live `properties` table. This
one is a physically distinct table fed by events.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from listings.adapters.database.models import ListingType, PropertyStatus, Typology
from shared.database.models import Base


class PropertyListingModel(Base):
    __tablename__ = "property_listings"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    organization_id: Mapped[str] = mapped_column(UUID(as_uuid=False), nullable=False, index=True)

    status: Mapped[PropertyStatus] = mapped_column(
        Enum(
            PropertyStatus,
            name="property_status",
            values_callable=lambda e: [x.value for x in e],
            create_type=False,
        ),
        nullable=False,
        index=True,
    )
    listing_type: Mapped[ListingType] = mapped_column(
        Enum(
            ListingType,
            name="listing_type",
            values_callable=lambda e: [x.value for x in e],
            create_type=False,
        ),
        nullable=False,
        index=True,
    )
    typology: Mapped[Typology] = mapped_column(
        Enum(
            Typology,
            name="typology",
            values_callable=lambda e: [x.value for x in e],
            create_type=False,
        ),
        nullable=False,
        index=True,
    )

    # Raw free-text, carried straight from the source event.
    address: Mapped[str] = mapped_column(Text, nullable=False)

    # Populated asynchronously by the enrichment handler.
    parish: Mapped[str | None] = mapped_column(Text, index=True)
    municipality: Mapped[str | None] = mapped_column(Text, index=True)
    district: Mapped[str | None] = mapped_column(Text, index=True)
    location_enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location_enrichment_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )

    # Denormalised characteristics (cheap indexed filters).
    num_of_bedrooms: Mapped[int | None] = mapped_column(Integer, index=True)
    num_of_bathrooms: Mapped[int | None] = mapped_column(Integer, index=True)
    area_in_m2: Mapped[int | None] = mapped_column(Integer, index=True)
    has_pool: Mapped[bool | None] = mapped_column(Boolean, index=True)
    has_garden: Mapped[bool | None] = mapped_column(Boolean, index=True)
    has_elevator: Mapped[bool | None] = mapped_column(Boolean, index=True)

    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), index=True)
    first_image_s3_key: Mapped[str | None] = mapped_column(Text)

    description: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    # Idempotency + pagination.
    source_aggregate_version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        # Supports ORDER BY created_at DESC, id DESC cursor pagination
        # needed by `listings-cursor-pagination-and-filters` (the next spec).
        Index(
            "idx_property_listings_pagination",
            "status",
            "created_at",
            "id",
        ),
    )
