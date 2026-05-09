"""Read-model domain type for the `property_listings` table.

Distinct from the legacy `ListedProperty` in `src/listings/domain/models.py`
— that one mirrors the write-side `properties` row via `extend_existing=True`.
This one is a deliberately denormalised read-model populated by the
projector from carried-state `PROPERTY_*` events. It stores structured
location columns (parish/municipality/district) that the write side
doesn't carry and lets the listings API filter on indexed b-trees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from listings.domain.models import ListingType, PropertyStatus, Typology


@dataclass(frozen=True)
class ListingPoi:
    """Lean POI projection carried from the upstream property snapshot.

    Spec `2026-05-listing-semantic-search`: only the three fields the
    canonical-text composer needs to render `NEARBY:`. Listings does
    not import `properties.PropertyPoi`.
    """

    category: str
    name: str
    distance_meters: float


@dataclass
class PropertyListing:
    id: UUID  # == properties.id
    organization_id: UUID
    status: PropertyStatus
    listing_type: ListingType
    typology: Typology

    # Raw free-text, carried through unchanged from the source event.
    address: str

    # Populated asynchronously by the enrichment handler. NULL until
    # enriched or for addresses the parser can't resolve.
    parish: str | None
    municipality: str | None
    district: str | None
    location_enriched_at: datetime | None
    location_enrichment_attempts: int

    # Denormalised characteristics — b-tree indexed for filters.
    num_of_bedrooms: int | None
    num_of_bathrooms: int | None
    area_in_m2: int | None
    has_pool: bool | None
    has_garden: bool | None
    has_elevator: bool | None

    # Snapshot of the minimum price across this property's prices at
    # event time; drives cheap range filters in the listings API.
    min_price: Decimal | None

    # First image (display_order == 0) s3 key — used for thumbnail rendering.
    first_image_s3_key: str | None

    description: str | None
    latitude: float | None
    longitude: float | None

    # Idempotency + ordering for cursor pagination.
    source_aggregate_version: int
    source_occurred_at: datetime
    created_at: datetime
    updated_at: datetime

    # Embedding pipeline state (ADR-013, spec
    # `2026-05-listing-semantic-search`). Default values match a freshly
    # projected row that hasn't been embedded yet.
    pois: list[ListingPoi] = field(default_factory=list)
    embedding_text_hash: str | None = None
    canonical_text_version: str | None = None
    embedding_model_version: str | None = None
    embedded_at: datetime | None = None
    embedding_status: str = "PENDING"
