"""`SearchListings` — ADR-014 read-path orchestrator + ADR-016 cache.

The if-q-then-this block: when `GET /api/v1/listings/properties`
receives a non-empty `q`, this use case runs. Five-stage pipeline
behind a single-value search-result cache:

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
   each, concatenate.

Then: cache the resulting `(parsed, ranked_ids)` tuple atomically.
The cursor (`SearchCursor(fp, offset)`) is just a position into
that cached ranked list — subsequent pages of the same `(q,
filters)` skip the entire pipeline (no LLM call, no Pinecone call)
and just `list_by_ids` the slice.

Fail-open envelope at every external call. Extractor errors →
empty ParsedQuery. SQL errors → broad mode. Embed errors →
_relational_fallback. Vector errors → _relational_fallback.

Returns a 2-tuple `(CachedPage, parsed)` — the route handler needs
`parsed.nearby_pois` to compose the matched/unmatched POI lists on
the response. The cache hit path returns the same `parsed` so the
response stays stable across cache hits and misses.

Spec: `2026-05-listings-cursor-pagination-and-page-cache.md`.
"""

from __future__ import annotations

import asyncio
from typing import Iterable
from uuid import UUID

import structlog

from listings.application.ports.embedding_provider import EmbeddingProvider
from listings.application.ports.listings_page_cache import CachedPage
from listings.application.ports.query_extractor import QueryExtractor
from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.application.ports.search_result_cache import (
    CachedSearchResult,
    SearchResultCache,
)
from listings.application.ports.vector_index import VectorIndex
from listings.domain.location_filter import LocationFilter
from listings.domain.models import PropertyStatus
from listings.domain.pagination import (
    SearchCursor,
    build_search_cache_key,
    encode,
)
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
        search_cache: SearchResultCache,
        ttl_seconds: int,
    ) -> None:
        self._query_extractor = query_extractor
        self._embedding_provider = embedding_provider
        self._vector_index = vector_index
        self._property_listing_repo = property_listing_repo
        self._namespace = namespace
        self._top_k = top_k
        self._max_pre_filter_candidates = max_pre_filter_candidates
        self._broad_mode_overshoot = broad_mode_overshoot
        self._search_cache = search_cache
        self._ttl = ttl_seconds

    async def execute(
        self,
        *,
        fp: str,
        q: str,
        location: LocationFilter,
        filters: PropertyFilters,
        cursor: SearchCursor | None,
        limit: int,
    ) -> tuple[CachedPage, ParsedQuery]:
        key = build_search_cache_key(fp=fp)
        offset = cursor.offset if cursor else 0

        hit = await self._search_cache.get(key)
        if hit is not None:
            log.info("search_result_cache.hit", key_fp=key[-16:])
            return await self._page_from_cache(hit, fp=fp, offset=offset, limit=limit)

        # Cache miss — run the full pipeline. `_compute_ranked` hydrates
        # the full top-k row set (needed for partition_and_rank); we
        # store only the ID order so cache values stay small.
        parsed, ordered_rows = await self._compute_ranked(q, location, filters)
        ranked_ids = [r.id for r in ordered_rows]

        await self._search_cache.set(
            key,
            CachedSearchResult(parsed=parsed, ranked_ids=ranked_ids),
            self._ttl,
        )
        log.info(
            "search_result_cache.miss",
            key_fp=key[-16:],
            ranked_count=len(ranked_ids),
        )

        # We already hydrated the rows — slice from them directly
        # instead of re-fetching for this first response.
        page_rows = ordered_rows[offset : offset + limit]
        has_more = offset + limit < len(ranked_ids)
        next_cursor = (
            encode(SearchCursor(fp=fp, offset=offset + limit)) if has_more else None
        )
        return CachedPage(items=page_rows, next_cursor=next_cursor), parsed

    # ──────────── Cache hit slice + hydrate ────────────

    async def _page_from_cache(
        self,
        hit: CachedSearchResult,
        *,
        fp: str,
        offset: int,
        limit: int,
    ) -> tuple[CachedPage, ParsedQuery]:
        page_ids = hit.ranked_ids[offset : offset + limit]
        if not page_ids:
            # Offset is past the cached ranked list — bounded depth
            # ceiling (spec acceptance criterion).
            return CachedPage(items=[], next_cursor=None), hit.parsed

        rows = await self._property_listing_repo.list_by_ids(page_ids)
        # list_by_ids order is unspecified — restore the rank-order
        # using the cached ID list as the truth.
        order = {pid: i for i, pid in enumerate(page_ids)}
        rows.sort(key=lambda r: order[r.id])

        has_more = offset + limit < len(hit.ranked_ids)
        next_cursor = (
            encode(SearchCursor(fp=fp, offset=offset + limit)) if has_more else None
        )
        return CachedPage(items=rows, next_cursor=next_cursor), hit.parsed

    # ──────────── Full pipeline (cache miss) ────────────

    async def _compute_ranked(
        self,
        query: str,
        location: LocationFilter,
        filters: PropertyFilters,
    ) -> tuple[ParsedQuery, list[PropertyListing]]:
        # 1. Extract. Fail-open: ParsedQuery(free_text_remainder=query).
        try:
            parsed = await self._query_extractor.extract(query)
        except Exception:
            log.warning("search_listings.extract_failed", query=query)
            parsed = ParsedQuery(free_text_remainder=query)

        # 2. Render the canonical-text-v3-shaped embed string.
        embed_text = _render_query_for_embed(parsed)
        if not embed_text.strip():
            embed_text = f"DESCRIPTION: {query}"

        # 3. Parallel stage — return_exceptions=True is load-bearing.
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
            log.exception("search_listings.sql_prefilter_failed", query=query)
            candidates: list[UUID] = []
            saturated = True
        else:
            candidates = candidates_or_err
            saturated = len(candidates) >= self._max_pre_filter_candidates

        if isinstance(vector_or_err, BaseException):
            log.exception("search_listings.embed_failed", query=query)
            return parsed, await self._relational_fallback(
                candidates=candidates, parsed=parsed,
            )
        vector: list[float] = vector_or_err

        # 4. Cardinality-guarded ANN.
        try:
            matches = await self._run_vector_query(
                vector=vector,
                candidates=candidates,
                cardinality_saturated=saturated,
            )
        except Exception:
            log.exception("search_listings.vector_query_failed", query=query)
            return parsed, await self._relational_fallback(
                candidates=candidates, parsed=parsed,
            )

        if not matches:
            return parsed, []

        # 5. Hydrate (status='active' enforced at the SQL level).
        rows = await self._property_listing_repo.list_by_ids(
            [UUID(m.id) for m in matches]
        )
        ordered = self._partition_and_rank(rows, matches, parsed)
        return parsed, ordered

    # ──────────── Helpers (unchanged from pre-cache implementation) ────────────

    async def _run_vector_query(
        self,
        *,
        vector: list[float],
        candidates: list[UUID],
        cardinality_saturated: bool,
    ) -> list[VectorMatch]:
        if cardinality_saturated:
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
            return matches[: self._top_k]
        elif candidates:
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
            return []

    @staticmethod
    def _partition_and_rank(
        rows: list[PropertyListing],
        matches: list[VectorMatch],
        parsed: ParsedQuery,
    ) -> list[PropertyListing]:
        by_id = {str(r.id): r for r in rows}
        matched: list[PropertyListing] = []
        partial: list[PropertyListing] = []
        for m in matches:
            row = by_id.get(m.id)
            if row is None:
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
    ) -> list[PropertyListing]:
        """Vector path failed. Reuse the SQL pre-filter candidates and
        skip the ANN ranking. Apply partition-and-rank so NULL-data
        rows still go to the bottom of the page."""
        if not candidates:
            return []
        rows = await self._property_listing_repo.list_by_ids(
            candidates[: self._top_k]
        )
        matched, partial = _split_buckets(rows, parsed)
        matched.sort(key=lambda r: (r.created_at, str(r.id)), reverse=True)
        partial.sort(key=lambda r: (r.created_at, str(r.id)), reverse=True)
        return matched + partial


def _render_query_for_embed(parsed: ParsedQuery) -> str:
    """Render ParsedQuery as a canonical-text-v3-shaped string."""
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
