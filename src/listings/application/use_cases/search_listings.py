"""`SearchListings` — ADR-014 read-path orchestrator.

The if-q-then-this block: when `GET /api/v1/listings/properties`
receives a non-empty `q`, this use case runs. Five stages:

1. Extract: LLM parses query → ParsedQuery (closed-vocab POIs,
   structural facets, free_text_remainder).
2. Parallel (asyncio.gather, return_exceptions=True):
   (a) SQL pre-filter on property_listings → list[UUID] candidates.
   (b) Embed the canonical-text-v3-shaped render of ParsedQuery.
3. Cardinality-guarded ANN. Normal mode: Pinecone with
   `listing_id IN candidates` filter. Broad mode (when SQL hit
   the LIMIT cap): broad Pinecone query + post-intersect.
4. Hydrate via list_by_ids (filters status='active' at SQL —
   defense in depth on top of the vector-index metadata filter).
5. Partition rows into matched / partial-data buckets (NULL-data
   rows go to the bottom of the page), sort by cosine within
   each, concatenate, paginate.

Fail-open envelope at every external call. Extractor errors →
empty ParsedQuery. SQL errors → broad mode. Embed errors →
_relational_fallback. Vector errors → _relational_fallback.

Returns a 3-tuple `(rows, total, parsed)` — the route handler
needs `parsed.nearby_pois` to compose the matched/unmatched POI
lists on the response.

Spec: 2026-05-listing-search-structured-extraction §6/§8/§11.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Iterable
from uuid import UUID

import structlog

from listings.application.ports.embedding_provider import EmbeddingProvider
from listings.application.ports.query_extractor import QueryExtractor
from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.application.ports.vector_index import VectorIndex
from listings.domain.location_filter import LocationFilter
from listings.domain.models import PropertyStatus
from listings.domain.parsed_query import ParsedQuery
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import PropertyListing
from listings.domain.vector import VectorMatch

log = structlog.get_logger()


class SearchListings:
    def __init__(
        self,
        *,
        query_extractor: QueryExtractor,
        embedding_provider: EmbeddingProvider,
        vector_index: VectorIndex,
        property_listing_repo: PropertyListingRepository,
        namespace: str,
        top_k: int,
        max_pre_filter_candidates: int = 1000,
        broad_mode_overshoot: int = 4,
    ) -> None:
        self._query_extractor = query_extractor
        self._embedding_provider = embedding_provider
        self._vector_index = vector_index
        self._property_listing_repo = property_listing_repo
        self._namespace = namespace
        self._top_k = top_k
        self._max_pre_filter_candidates = max_pre_filter_candidates
        self._broad_mode_overshoot = broad_mode_overshoot

    async def execute(
        self,
        *,
        query: str,
        location: LocationFilter,
        filters: PropertyFilters,
    ) -> tuple[list[PropertyListing], int, ParsedQuery]:
        # 1. Extract. Fail-open: ParsedQuery(free_text_remainder=query).
        try:
            parsed = await self._query_extractor.extract(query)
        except Exception:
            log.warning("search_listings.extract_failed", query=query)
            parsed = ParsedQuery(free_text_remainder=query)

        # 2. Render the canonical-text-v3-shaped embed string.
        embed_text = _render_query_for_embed(parsed)
        if not embed_text.strip():
            # Defensive: extractor produced an empty ParsedQuery (e.g.
            # LLM returned `{}`). Fall back to the raw query as a
            # DESCRIPTION: block so the embedder has SOMETHING to encode.
            embed_text = f"DESCRIPTION: {query}"

        # 3. Parallel stage — return_exceptions=True is load-bearing.
        # Default asyncio.gather re-raises the first exception, which
        # would defeat the per-stage fail-open envelope.
        candidates_or_err, vector_or_err = await asyncio.gather(
            self._property_listing_repo.list_ids_for_search(
                location=location,
                route_filters=filters,
                parsed=parsed,
                limit=self._max_pre_filter_candidates,
            ),
            self._embedding_provider.embed(embed_text),
            return_exceptions=True,
        )

        if isinstance(candidates_or_err, BaseException):
            log.exception(
                "search_listings.sql_prefilter_failed", query=query
            )
            candidates: list[UUID] = []
            saturated = True  # falls through to broad-mode
        else:
            candidates = candidates_or_err
            saturated = len(candidates) >= self._max_pre_filter_candidates

        if isinstance(vector_or_err, BaseException):
            log.exception("search_listings.embed_failed", query=query)
            return await self._relational_fallback(
                candidates=candidates, parsed=parsed, filters=filters
            )
        vector: list[float] = vector_or_err

        # 4. Cardinality-guarded ANN. Fail-open: vector exceptions
        # trigger the same _relational_fallback.
        try:
            matches = await self._run_vector_query(
                vector=vector,
                candidates=candidates,
                cardinality_saturated=saturated,
            )
        except Exception:
            log.exception("search_listings.vector_query_failed", query=query)
            return await self._relational_fallback(
                candidates=candidates, parsed=parsed, filters=filters
            )

        if not matches:
            return [], 0, parsed

        # 5. Hydrate. list_by_ids filters status='active' at the SQL
        # level (defense in depth on top of the vector metadata filter).
        rows = await self._property_listing_repo.list_by_ids(
            [UUID(m.id) for m in matches]
        )
        ordered = self._partition_and_rank(rows, matches, parsed)
        total = len(ordered)
        page = ordered[filters.offset : filters.offset + filters.limit]
        return page, total, parsed

    # ──────────── Helpers ────────────

    async def _run_vector_query(
        self,
        *,
        vector: list[float],
        candidates: list[UUID],
        cardinality_saturated: bool,
    ) -> list[VectorMatch]:
        if cardinality_saturated:
            # SQL pre-filter hit the LIMIT. Don't bother filtering at
            # Pinecone — over-broad ID lists hurt more than they help.
            # Run broad, intersect after.
            log.info("search_listings.broad_mode", reason="prefilter_saturated")
            matches = await self._vector_index.query(
                vector=vector,
                filter={"status": {"eq": PropertyStatus.ACTIVE.value}},
                top_k=self._top_k * self._broad_mode_overshoot,
                namespace=self._namespace,
            )
            if candidates:
                candidate_set = {str(c) for c in candidates}
                return [m for m in matches if m.id in candidate_set][: self._top_k]
            # No candidates AND saturated — SQL pre-filter failed
            # entirely. Return the broad matches without intersection.
            return matches[: self._top_k]
        elif candidates:
            # Normal mode: push the candidate IDs into the Pinecone
            # filter. NB: we filter on `listing_id` (a metadata field
            # the embedding handler writes — see
            # embedding_handler._index_metadata), NOT on `id` —
            # Pinecone's vector ID is first-class and not filterable
            # through `filter=`.
            return await self._vector_index.query(
                vector=vector,
                filter={
                    "and": [
                        {"status": {"eq": PropertyStatus.ACTIVE.value}},
                        {"listing_id": {"in": [str(c) for c in candidates]}},
                    ]
                },
                top_k=self._top_k,
                namespace=self._namespace,
            )
        else:
            # SQL pre-filter returned 0. No listings match the
            # structural criteria — don't bother calling Pinecone.
            return []

    @staticmethod
    def _partition_and_rank(
        rows: list[PropertyListing],
        matches: list[VectorMatch],
        parsed: ParsedQuery,
    ) -> list[PropertyListing]:
        """Score-order with NULL-data rows pushed to the bottom of the
        page. A row goes into the partial bucket when at least one
        ParsedQuery criterion that was SET can't be evaluated against
        the row because the corresponding column is None. Otherwise
        it's in the matched bucket. Each bucket is internally ordered
        by vector cosine score."""
        by_id = {str(r.id): r for r in rows}
        matched: list[PropertyListing] = []
        partial: list[PropertyListing] = []
        for m in matches:
            row = by_id.get(m.id)
            if row is None:
                # Stale vector — Pinecone returned an id that's no
                # longer ACTIVE on `property_listings` (the SQL hydrate
                # filter dropped it). Defense in depth working.
                continue
            if _has_unevaluable_criterion(row, parsed):
                partial.append(row)
            else:
                matched.append(row)
        return matched + partial

    async def _relational_fallback(
        self,
        *,
        candidates: list[UUID],
        parsed: ParsedQuery,
        filters: PropertyFilters,
    ) -> tuple[list[PropertyListing], int, ParsedQuery]:
        """Vector path failed. Reuse the SQL pre-filter candidates and
        skip the ANN ranking. Apply partition-and-rank so NULL-data
        rows still go to the bottom of the page (deterministic order
        within each bucket: created_at desc, id desc — no cosine
        available). Pagination applies just like the happy path."""
        if not candidates:
            return [], 0, parsed
        # Cap to top_k before hydrate — same bound the happy path uses
        # so the response shape stays predictable.
        rows = await self._property_listing_repo.list_by_ids(
            candidates[: self._top_k]
        )
        matched, partial = _split_buckets(rows, parsed)
        matched.sort(key=lambda r: (r.created_at, str(r.id)), reverse=True)
        partial.sort(key=lambda r: (r.created_at, str(r.id)), reverse=True)
        ordered = matched + partial
        total = len(ordered)
        page = ordered[filters.offset : filters.offset + filters.limit]
        return page, total, parsed


def _render_query_for_embed(parsed: ParsedQuery) -> str:
    """Render ParsedQuery as a canonical-text-v3-shaped string. Same
    sectional layout as the listing-side composer
    (`src/listings/application/services/canonical_text.py`) — cosine
    compares like-with-like.

    Pure function. Returns "" when ParsedQuery is empty; the caller
    is responsible for the fallback (DESCRIPTION: raw_query).
    """
    sections: list[str] = []
    if parsed.typology:
        sections.append(f"TYPOLOGY: {parsed.typology.value}")

    chars: list[str] = []
    if parsed.min_bedrooms:
        chars.append(f"T{parsed.min_bedrooms}")
    if parsed.min_area_m2 is not None or parsed.max_area_m2 is not None:
        if parsed.min_area_m2 is not None and parsed.max_area_m2 is not None:
            chars.append(f"{parsed.min_area_m2}-{parsed.max_area_m2}m²")
        elif parsed.min_area_m2 is not None:
            chars.append(f"≥{parsed.min_area_m2}m²")
        else:
            chars.append(f"≤{parsed.max_area_m2}m²")
    if parsed.min_bathrooms:
        chars.append(f"{parsed.min_bathrooms} casas de banho")
    if chars:
        sections.append(f"CHARACTERISTICS: {', '.join(chars)}")

    features: list[str] = []
    if parsed.has_pool:
        features.append("piscina")
    if parsed.has_garden:
        features.append("jardim")
    if parsed.has_elevator:
        features.append("elevador")
    if parsed.has_parking:
        features.append("garagem")
    if features:
        sections.append(f"FEATURES: {', '.join(features)}")

    if parsed.nearby_pois:
        sections.append(
            f"NEARBY: {', '.join(p.value for p in parsed.nearby_pois)}"
        )

    if parsed.free_text_remainder.strip():
        sections.append(f"DESCRIPTION: {parsed.free_text_remainder.strip()}")

    return "\n".join(sections)


def _split_buckets(
    rows: Iterable[PropertyListing], parsed: ParsedQuery
) -> tuple[list[PropertyListing], list[PropertyListing]]:
    matched: list[PropertyListing] = []
    partial: list[PropertyListing] = []
    for row in rows:
        if _has_unevaluable_criterion(row, parsed):
            partial.append(row)
        else:
            matched.append(row)
    return matched, partial


def _has_unevaluable_criterion(row: PropertyListing, parsed: ParsedQuery) -> bool:
    """True if at least one ParsedQuery criterion that was SET can't
    be evaluated against this row because the corresponding column
    is None. The SQL pre-filter admits these rows; the use case
    pushes them to the bottom of the result page via
    `_partition_and_rank`.

    Note: only `has_*=True` triggers the partial bucket. Future
    polarity-parsing (`has_pool=False` etc.) would need symmetric
    handling here — landed under "Out of scope follow-ups" in the
    spec.
    """
    if parsed.min_bedrooms is not None and row.num_of_bedrooms is None:
        return True
    if parsed.min_bathrooms is not None and row.num_of_bathrooms is None:
        return True
    if (
        parsed.min_area_m2 is not None or parsed.max_area_m2 is not None
    ) and row.area_in_m2 is None:
        return True
    if parsed.has_pool is True and row.has_pool is None:
        return True
    if parsed.has_garden is True and row.has_garden is None:
        return True
    if parsed.has_elevator is True and row.has_elevator is None:
        return True
    if parsed.has_parking is True and row.parking_spaces is None:
        return True
    if (
        parsed.min_price is not None or parsed.max_price is not None
    ) and row.min_price is None:
        return True
    return False
