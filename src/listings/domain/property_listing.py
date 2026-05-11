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


@dataclass(frozen=True, eq=True, unsafe_hash=False)
class ListingPoi:
    """POI projection carried from the upstream property snapshot.

    Three lean fields (`category`, `name`, `distance_meters`) drive
    the canonical-text composer's `NEARBY:` line. Three rich fields
    (`address`, `image_urls`, `reviews`) drive the
    `matched_pois` response on the search read path (ADR-014 §14)
    — populated from the snapshot once `build_property_snapshot`
    on the properties side ships its §13 extension.

    `unsafe_hash=False`: `frozen=True` would normally synthesize
    `__hash__` from all fields, but `list[dict]` reviews are
    unhashable contents — calling `hash(ListingPoi(...))` would
    raise `TypeError`. We disable the synthesized hash explicitly:
    `ListingPoi` is a value object (immutable) but not hashable.
    The matched-POI composition path never hashes individual POIs
    (it hashes only `poi.category` strings via set comprehensions),
    so this is safe.

    Listings does NOT import `properties.PropertyPoi` — the
    closed-vocabulary alignment is pinned by a contract test in
    `tests/unit/listings/test_poi_category_contract.py`.
    """

    category: str
    name: str
    distance_meters: float
    address: str | None = None
    image_urls: list[str] = field(default_factory=list)
    reviews: list[dict] | None = None


@dataclass(frozen=True)
class ListingImage:
    """Lean image projection carried from the upstream property snapshot.

    Mirrors the snapshot shape produced by `build_property_snapshot()`
    in the properties context. The public listings response renders
    these as `{display_order, download_url}` pairs — `id` is preserved
    so URLs can be keyed per image at the route layer.
    """

    id: UUID
    s3_key: str
    display_order: int


@dataclass(frozen=True)
class ListingPrice:
    """Lean price projection. Snapshot shape: amount + listing_type.

    No price `id` because the public listings response doesn't expose
    it (no per-price actions on the public surface). The
    write-side `PropertyPrice` keeps its id; the projection drops it.
    """

    amount: Decimal
    listing_type: ListingType


@dataclass
class PropertyListing:
    id: UUID  # == properties.id
    organization_id: UUID
    status: PropertyStatus
    listing_type: ListingType
    typology: Typology

    # Raw `address` was dropped from this read-model — privacy fix
    # (spec `2026-05-property-address-enrichment-fix`). The free-text
    # address still lives on the write-side `Property` aggregate;
    # the projector reads it from the upstream event payload only to
    # forward it to the LLM enrichment handler.

    # Populated asynchronously by the enrichment handler. Per-country
    # invariant enforced by the `AddressSearcher` — PT must have
    # parish/municipality/district; future US fills city/state.
    # `country` / `city` / `state` / `postal_code` / `region` are at
    # the bottom of this dataclass with defaults so the dataclass
    # init order is valid.
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

    # Read by the canonical-text composer (`BUILT: ...` line).
    built_at: int | None = None
    energy_rating: str | None = None

    # Two more characteristics surfaced in the public response.
    floor: int | None = None
    parking_spaces: int | None = None

    # Forward-scope multi-country location columns. Populated by future
    # per-country `AddressSearcher` implementations (spec
    # `2026-05-property-address-enrichment-fix`); not written by anyone
    # in v1. NOTE: no `postal_code` here — it's an LLM-input signal,
    # not a persisted field.
    country: str = "Portugal"
    city: str | None = None
    state: str | None = None
    region: str | None = None

    # Full image + price lists projected from the snapshot. Lean shape
    # — only the fields the public response renders. Drops the
    # `filename`/`content_type`/`size_bytes` from `PropertyImage` and
    # the `id` from `PropertyPrice`.
    images: list[ListingImage] = field(default_factory=list)
    prices: list[ListingPrice] = field(default_factory=list)

    # Embedding pipeline state (ADR-013, spec
    # `2026-05-listing-semantic-search`). Default values match a freshly
    # projected row that hasn't been embedded yet.
    pois: list[ListingPoi] = field(default_factory=list)
    embedding_text_hash: str | None = None
    canonical_text_version: str | None = None
    embedding_model_version: str | None = None
    embedded_at: datetime | None = None
    embedding_status: str = "PENDING"
