from __future__ import annotations

import redis.asyncio as aioredis

from listings.adapters.cache.null_page_cache import NullListingsPageCache
from listings.adapters.cache.null_search_result_cache import NullSearchResultCache
from listings.adapters.cache.redis_page_cache import RedisListingsPageCache
from listings.adapters.cache.redis_search_result_cache import RedisSearchResultCache
from listings.application.ports.address_searcher import AddressSearcher
from listings.application.ports.get_agency_contact import GetAgencyContact
from listings.application.ports.embedding_provider import EmbeddingProvider
from listings.application.ports.listings_page_cache import ListingsPageCache
from listings.application.ports.query_extractor import QueryExtractor
from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.application.ports.search_result_cache import SearchResultCache
from listings.application.ports.vector_index import VectorIndex
from listings.application.use_cases.get_property import GetProperty
from listings.application.use_cases.list_locations import ListLocations
from listings.application.use_cases.list_org_active_listings import ListOrgActiveListings
from listings.application.use_cases.list_properties import ListProperties
from listings.application.use_cases.search_listings import SearchListings


class Container:
    def __init__(
        self,
        property_listing_repo: PropertyListingRepository,
        portugal_address_searcher: AddressSearcher | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        vector_index: VectorIndex | None = None,
        vector_index_namespace: str = "openai-text-embedding-3-small-v1",
        embedding_model_version: str = "text-embedding-3-small",
        query_extractor: QueryExtractor | None = None,
        listings_search_ranked_list_size: int = 200,
        max_pre_filter_candidates: int = 1000,
        broad_mode_overshoot: int = 4,
        page_cache_enabled: bool = False,
        page_cache_ttl_seconds: int = 90,
        redis_url: str = "redis://localhost:6379/0",
        # Override hooks for tests — when supplied, skip the
        # Redis-vs-Null branch below and use these directly.
        page_cache: ListingsPageCache | None = None,
        search_cache: SearchResultCache | None = None,
        # Spec `2026-05-listings-agency-contact`: projector calls this on
        # each PROPERTY_* event to resolve the agency display contact.
        # Optional so existing tests that build a bare Container keep working.
        get_agency_contact: "GetAgencyContact | None" = None,
    ) -> None:
        self.property_listing_repo = property_listing_repo
        self.get_agency_contact = get_agency_contact

        # Cache wiring. When `page_cache_enabled=False` (default) we
        # wire Null adapters so use cases' get/set calls stay
        # structurally identical to the Redis path. Tests can also
        # inject their own caches via the override kwargs.
        self._redis: aioredis.Redis | None = None
        if page_cache is not None and search_cache is not None:
            self.page_cache: ListingsPageCache = page_cache
            self.search_cache: SearchResultCache = search_cache
        elif page_cache_enabled:
            # decode_responses=False — values are msgpack bytes, not utf-8 strings.
            self._redis = aioredis.from_url(redis_url, decode_responses=False)
            self.page_cache = RedisListingsPageCache(self._redis)
            self.search_cache = RedisSearchResultCache(self._redis)
        else:
            self.page_cache = NullListingsPageCache()
            self.search_cache = NullSearchResultCache()

        # Public + admin route use cases.
        self.list_properties = ListProperties(
            property_listing_repo=property_listing_repo,
            cache=self.page_cache,
            ttl_seconds=page_cache_ttl_seconds,
        )
        self.get_property = GetProperty(property_listing_repo=property_listing_repo)
        self.list_org_active_listings = ListOrgActiveListings(
            property_listing_repo=property_listing_repo
        )

        # Country-specific AddressSearcher (spec
        # `2026-05-property-address-enrichment-fix`). The handler picks
        # the right implementation via `select_address_searcher`; v1
        # only Portugal is wired.
        self.portugal_address_searcher = portugal_address_searcher

        # Embedding pipeline (spec `2026-05-listing-semantic-search`).
        self.embedding_provider = embedding_provider
        self.vector_index = vector_index
        self.vector_index_namespace = vector_index_namespace
        self.embedding_model_version = embedding_model_version

        # Search read path (ADR-014 + ADR-016). The cache layer means
        # a hit on `(q, filters)` skips both the LLM call and the
        # Pinecone call — pages slice from the cached ranked list.
        self.query_extractor = query_extractor

        # Wire SearchListings only when ALL three ports are present.
        self.search_listings: SearchListings | None = None
        if (
            query_extractor is not None
            and embedding_provider is not None
            and vector_index is not None
        ):
            self.search_listings = SearchListings(
                query_extractor=query_extractor,
                embedding_provider=embedding_provider,
                vector_index=vector_index,
                property_listing_repo=property_listing_repo,
                namespace=vector_index_namespace,
                top_k=listings_search_ranked_list_size,
                max_pre_filter_candidates=max_pre_filter_candidates,
                broad_mode_overshoot=broad_mode_overshoot,
                search_cache=self.search_cache,
                ttl_seconds=page_cache_ttl_seconds,
            )

        self.list_locations = ListLocations()

    async def close(self) -> None:
        """Called by the FastAPI lifespan handler on app shutdown.
        Drains the redis connection pool when the cache is enabled."""
        if self._redis is not None:
            await self._redis.aclose()
