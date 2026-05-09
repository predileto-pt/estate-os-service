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
from sqlalchemy.dialects.postgresql import JSONB, UUID
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

    # Raw free-text address has been DROPPED from this read-model
    # (spec 2026-05-property-address-enrichment-fix). The public route
    # served from this table — once it migrates from the legacy
    # `ReadPropertyModel` — will compose location from the structured
    # fields below instead of leaking the street address.

    # Populated asynchronously by the enrichment handler. Stay nullable
    # in the schema; the per-country `AddressSearcher` enforces non-null
    # for its country (e.g. PT requires parish/municipality/district).
    parish: Mapped[str | None] = mapped_column(Text, index=True)
    municipality: Mapped[str | None] = mapped_column(Text, index=True)
    district: Mapped[str | None] = mapped_column(Text, index=True)
    # Country defaults to 'Portugal' at the DB level — the only country
    # supported in v1. Forward-scope columns below populate as the
    # platform expands to other countries.
    country: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'Portugal'"), index=True
    )
    city: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    # NOTE: no `postal_code` column. Postal code is an input signal to
    # the LLM searcher (it rides on every PROPERTY_* event and into the
    # enrichment event) — once the searcher uses it to resolve parish/
    # municipality/district, we don't keep it. Spec
    # 2026-05-property-address-enrichment-fix v5.
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
    # Two more characteristic columns surfaced for the public response;
    # carried in `PROPERTY_*.v1`.characteristics already, just projected.
    floor: Mapped[int | None] = mapped_column(Integer)
    parking_spaces: Mapped[int | None] = mapped_column(Integer)
    # Read by the canonical-text composer (`BUILT: ...` line).
    built_at: Mapped[int | None] = mapped_column(Integer)
    energy_rating: Mapped[str | None] = mapped_column(Text)

    min_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), index=True)
    first_image_s3_key: Mapped[str | None] = mapped_column(Text)

    # Full image + price lists, projected from the snapshot. Lets the
    # public read API serve detail pages from this projection without
    # the legacy `ListingRepository` (read mapping over the live
    # `properties` table). Lean shape — see `ListingImage` /
    # `ListingPrice` value objects in `domain/property_listing.py`.
    images: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    prices: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    description: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    # POIs carried from the upstream property snapshot. Lean shape per
    # spec `2026-05-listing-semantic-search`: list of
    # `{category, name, distance_meters}`. Overwritten by the projector
    # on every applied upsert; consumed by the canonical-text composer.
    pois: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))

    # Embedding pipeline state (ADR-013 §1). All five columns are
    # managed by the embedding handler, never by the projector — the
    # projector excludes them from the upsert SET clause so a property
    # update doesn't regress the embedding state.
    embedding_text_hash: Mapped[str | None] = mapped_column(Text)
    canonical_text_version: Mapped[str | None] = mapped_column(Text)
    embedding_model_version: Mapped[str | None] = mapped_column(Text)
    embedded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'PENDING'")
    )

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
        # Partial index supporting the ops dashboard query
        # `WHERE embedding_status != 'INDEXED'` (spec
        # `2026-05-listing-semantic-search`).
        Index(
            "idx_property_listings_embedding_status_pending",
            "embedding_status",
            postgresql_where=text("embedding_status != 'INDEXED'"),
        ),
    )
