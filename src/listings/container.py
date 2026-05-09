from listings.application.ports.address_searcher import AddressSearcher
from listings.application.ports.embedding_provider import EmbeddingProvider
from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.application.ports.vector_index import VectorIndex
from listings.application.use_cases.get_property import GetProperty
from listings.application.use_cases.list_org_active_listings import ListOrgActiveListings
from listings.application.use_cases.list_properties import ListProperties


class Container:
    def __init__(
        self,
        property_listing_repo: PropertyListingRepository,
        portugal_address_searcher: AddressSearcher | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        vector_index: VectorIndex | None = None,
        vector_index_namespace: str = "openai-text-embedding-3-small-v1",
        embedding_model_version: str = "text-embedding-3-small",
    ) -> None:
        # Single read-model: the carried-state `property_listings`
        # projection. The legacy `ListingRepository` (read mapping over
        # the live `properties` table) was collapsed into this port —
        # its read methods were absorbed and the legacy port deleted.
        self.property_listing_repo = property_listing_repo

        # Public + admin route use cases.
        self.list_properties = ListProperties(property_listing_repo=property_listing_repo)
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
        # Both ports are optional; when either is None the embedding
        # handler is a no-op (the gate). This is how
        # LISTINGS_EMBEDDING_ENABLED=false is wired — bootstrap simply
        # doesn't construct the adapters.
        self.embedding_provider = embedding_provider
        self.vector_index = vector_index
        self.vector_index_namespace = vector_index_namespace
        self.embedding_model_version = embedding_model_version
