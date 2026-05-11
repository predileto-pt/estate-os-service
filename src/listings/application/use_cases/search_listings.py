"""`SearchListings` — phase-2 read path orchestrator.

The if-q-then-this block: when `GET /api/v1/listings/properties`
receives a non-empty `q`, this use case runs. It orchestrates four
stages (rewrite → embed → ANN → hydrate) with explicit fail-open at
each step, so a single upstream incident never 500s the listings
page.

See spec `2026-05-listing-semantic-search-read-path` §`SearchListings`
for the full design rationale.
"""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import structlog

from listings.application.ports.embedding_provider import EmbeddingProvider
from listings.application.ports.query_understanding import QueryUnderstandingService
from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.application.ports.vector_index import VectorIndex
from listings.domain.location_filter import LocationFilter
from listings.domain.models import PropertyStatus
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import PropertyListing
from listings.domain.vector import VectorFilter, VectorMatch

log = structlog.get_logger()


class SearchListings:
    def __init__(
        self,
        *,
        query_understanding: QueryUnderstandingService,
        embedding_provider: EmbeddingProvider,
        vector_index: VectorIndex,
        property_listing_repo: PropertyListingRepository,
        namespace: str,
        top_k: int,
    ) -> None:
        self._query_understanding = query_understanding
        self._embedding_provider = embedding_provider
        self._vector_index = vector_index
        self._property_listing_repo = property_listing_repo
        self._namespace = namespace
        self._top_k = top_k

    async def execute(
        self,
        *,
        query: str,
        location: LocationFilter,
        filters: PropertyFilters,
    ) -> tuple[list[PropertyListing], int]:
        # 1. Understand the query. Fail-open: on any LLM error, embed
        #    the raw query — search still runs, just less smart.
        try:
            rewritten = await self._query_understanding.rewrite(query)
        except Exception:
            log.warning("search_listings.rewrite_failed", query=query)
            rewritten = query

        # 2. Embed. The top-k bound uses the user's pagination window
        #    so deep pages still get served, capped by VECTOR_INDEX_TOP_K
        #    so offset=999999 can't blow up Pinecone.
        effective_top_k = min(self._top_k, filters.limit + filters.offset)

        try:
            vector = await self._embedding_provider.embed(rewritten)
        except Exception:
            log.exception("search_listings.embed_failed", query=query)
            return await self._relational_fallback(location, filters)

        # 3. ANN search.
        try:
            matches = await self._vector_index.query(
                vector=vector,
                filter=self._build_filter(location, filters),
                top_k=effective_top_k,
                namespace=self._namespace,
            )
        except Exception:
            log.exception("search_listings.vector_query_failed", query=query)
            return await self._relational_fallback(location, filters)

        if not matches:
            return [], 0

        # 4. DB hydrate. `list_by_ids` filters to status='active' at the
        #    SQL level (lowercase StrEnum value), defense in depth on top
        #    of the vector-index metadata `status` filter.
        rows = await self._property_listing_repo.list_by_ids(
            [UUID(m.id) for m in matches]
        )
        ordered = self._reorder_by_score(rows, matches)

        # 5. Paginate over the ranked list.
        page = ordered[filters.offset : filters.offset + filters.limit]
        return page, len(ordered)

    # ──────────── Helpers ────────────

    @staticmethod
    def _build_filter(
        location: LocationFilter,
        filters: PropertyFilters,
    ) -> VectorFilter:
        # `status` literal must match the phase-1 indexer's metadata
        # (the StrEnum's lowercase value). See
        # `embedding_handler._index_metadata`: `"status": row.status.value`.
        clauses: list[dict] = [{"status": {"eq": PropertyStatus.ACTIVE.value}}]

        # Location: each level the user picked applies as an `eq`.
        # Strings lowercased + stripped to match phase-1 index-time casing.
        if location.parish:
            clauses.append({"parish": {"eq": location.parish.lower().strip()}})
        if location.municipality:
            clauses.append({"municipality": {"eq": location.municipality.lower().strip()}})
        if location.district:
            clauses.append({"district": {"eq": location.district.lower().strip()}})

        # Structured params (existing PropertyFilters from ADR-010).
        if filters.listing_type is not None:
            clauses.append({"listing_type": {"eq": filters.listing_type.value}})
        if filters.typology is not None:
            clauses.append({"typology": {"eq": filters.typology.value}})
        if filters.min_price is not None:
            clauses.append({"price_eur": {"gte": float(filters.min_price)}})
        if filters.max_price is not None:
            clauses.append({"price_eur": {"lte": float(filters.max_price)}})

        return {"and": clauses}

    @staticmethod
    def _reorder_by_score(
        rows: list[PropertyListing], matches: list[VectorMatch]
    ) -> list[PropertyListing]:
        """Re-sort `rows` (arbitrary order from `list_by_ids`) into the
        score order from `matches`. Rows present in `matches` but
        missing from `rows` (stale vectors that failed the SQL ACTIVE
        filter) are silently dropped — they shouldn't surface to the
        user."""
        by_id = {str(r.id): r for r in rows}
        return [by_id[m.id] for m in matches if m.id in by_id]

    async def _relational_fallback(
        self, location: LocationFilter, filters: PropertyFilters
    ) -> tuple[list[PropertyListing], int]:
        """Vector path failed — fall back to the structured-filter path
        with the user's location merged in. We lose semantic ranking
        (the user's `q` text is ignored), but they keep getting
        location-correct results. Better than 503'ing the page."""
        merged = replace(
            filters,
            parish=location.parish,
            municipality=location.municipality,
            district=location.district,
        )
        rows = await self._property_listing_repo.list_active(merged)
        total = await self._property_listing_repo.count_active(merged)
        return rows, total
