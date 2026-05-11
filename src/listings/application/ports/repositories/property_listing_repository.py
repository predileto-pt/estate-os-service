"""Repository port for the `property_listings` read-model table.

Two responsibilities, sharing one port:

- **Write side** (called by the listings worker handlers):
    - `upsert_from_event` — idempotent INSERT/UPDATE from a full
      carried-state event payload. Guarded by
      `source_aggregate_version > current` — older events are silently
      dropped so out-of-order redelivery is safe.
    - `delete_if_newer` — guarded delete. Same version guard as upsert.
    - `update_location` — patch enrichment columns after the LLM
      parses the free-text address.
    - `increment_enrichment_attempts` — bump-only counter.
    - `set_embedding_indexed` / `set_embedding_status` — embedding
      handler write paths.

- **Read side** (called by the public + admin route handlers; absorbed
  from the deprecated `ListingRepository`):
    - `get_by_id` — single-property fetch.
    - `list_active` / `count_active` — public-facing structured-filter
      list.
    - `list_active_for_organization` / `count_active_for_organization`
      — admin variant scoped to one org.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from listings.application.ports.address_searcher import ParsedAddress
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import PropertyListing


class PropertyListingRepository(ABC):
    @abstractmethod
    async def get_by_id(self, property_id: UUID) -> PropertyListing | None: ...

    # ──────────── Read side (public / admin route handlers) ────────────

    @abstractmethod
    async def list_active(self, filters: PropertyFilters) -> list[PropertyListing]:
        """Return rows where `status='active'`, applying structured
        filters from `PropertyFilters`. Sorted by `created_at DESC, id
        DESC`. Bounded by `filters.limit`/`filters.offset`."""

    @abstractmethod
    async def count_active(self, filters: PropertyFilters) -> int:
        """Count of `list_active` matches before limit/offset."""

    @abstractmethod
    async def list_active_for_organization(
        self, organization_id: UUID, filters: PropertyFilters
    ) -> list[PropertyListing]:
        """Same as `list_active`, scoped to one organization. Permission
        enforcement is route-side via `require_org_member`."""

    @abstractmethod
    async def count_active_for_organization(
        self, organization_id: UUID, filters: PropertyFilters
    ) -> int: ...

    # ──────────── Search read path (hydrate) ────────────

    @abstractmethod
    async def list_by_ids(self, ids: list[UUID]) -> list[PropertyListing]:
        """Bulk-fetch active rows by id, for the search hydrate step.

        **Order is unspecified** — both adapters return rows in
        storage order (Postgres' `WHERE id = ANY(:ids)` does NOT
        preserve input-array order). The calling use case
        (`SearchListings`) re-sorts by vector-index score; never
        rely on input-id order being preserved.

        **Filters to `status='active'` at the SQL level** — defense in
        depth on top of the vector-index `status` metadata filter, so
        a stale Pinecone vector for a now-WITHDRAWN listing doesn't
        leak into the public response.

        Empty `ids` returns an empty list (no SQL round-trip).
        """

    # NOTE: `list_locations` (DISTINCT parish/municipality/district
    # over active rows) was REMOVED 2026-05-11. The
    # `/api/v1/listings/locations` endpoint now reads from a bundled
    # JSON catalog (src/listings/static_data/locations.json) so the
    # FE renders the full geography from day one — even before any
    # listings are indexed in a region. See spec
    # `2026-05-listing-semantic-search-read-path` amendment.

    # ──────────── Write side (listings worker handlers) ───────────────

    @abstractmethod
    async def upsert_from_event(
        self,
        *,
        event_data: dict,
        source_occurred_at: datetime,
    ) -> PropertyListing | None:
        """Insert or update using the carried-state event payload.

        Returns the row if the write succeeded; returns None if the
        write was idempotency-dropped (incoming `source_aggregate_version`
        is <= the stored value).
        """

    @abstractmethod
    async def delete_if_newer(
        self,
        *,
        property_id: UUID,
        source_aggregate_version: int,
        source_occurred_at: datetime,
    ) -> bool:
        """Delete the row iff `source_aggregate_version` > current stored
        value. Returns True if the row was deleted, False if dropped.
        """

    @abstractmethod
    async def update_location(
        self,
        *,
        property_id: UUID,
        parsed: ParsedAddress,
    ) -> PropertyListing | None:
        """Persist the universal `ParsedAddress` envelope returned by
        the country-specific `AddressSearcher` — every per-country
        implementation fills its country's fields and leaves the
        others None. The row absorbs Nones in nullable columns. Also
        bumps `location_enrichment_attempts` and sets
        `location_enriched_at = NOW()` on success. Returns None if the
        row doesn't exist (already deleted).
        """

    @abstractmethod
    async def increment_enrichment_attempts(self, *, property_id: UUID) -> PropertyListing | None:
        """Bump `location_enrichment_attempts` without setting
        `location_enriched_at` — called when the LLM parse fails so a
        monitor query can surface stuck rows.
        """

    @abstractmethod
    async def set_embedding_indexed(
        self,
        *,
        property_id: UUID,
        embedding_text_hash: str,
        canonical_text_version: str,
        embedding_model_version: str,
        embedded_at: datetime,
    ) -> PropertyListing | None:
        """Mark a row as successfully indexed: persist the canonical-text
        hash, the schema/model versions, the timestamp, and flip
        `embedding_status` to `INDEXED`. Returns None if the row was
        deleted between the embed call and this write.
        """

    @abstractmethod
    async def set_embedding_status(
        self, *, property_id: UUID, status: str
    ) -> PropertyListing | None:
        """Update only `embedding_status` (e.g. PENDING / FAILED). Used
        on transient state transitions; the success path uses
        `set_embedding_indexed` instead, which writes the full tuple
        atomically. Returns None if the row doesn't exist.
        """
