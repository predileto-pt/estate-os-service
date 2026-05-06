from listings.application.ports.address_parser import AddressParser
from listings.application.ports.listing_repository import ListingRepository
from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.application.use_cases.get_property import GetProperty
from listings.application.use_cases.list_org_active_listings import ListOrgActiveListings
from listings.application.use_cases.list_properties import ListProperties


class Container:
    def __init__(
        self,
        listing_repo: ListingRepository,
        property_listing_repo: PropertyListingRepository | None = None,
        address_parser: AddressParser | None = None,
    ) -> None:
        # Legacy read-model (mirrors properties table; served by the
        # current `GET /api/v1/listings/*` route).
        self.listing_repo = listing_repo
        self.list_properties = ListProperties(listing_repo=listing_repo)
        self.get_property = GetProperty(listing_repo=listing_repo)
        self.list_org_active_listings = ListOrgActiveListings(listing_repo=listing_repo)

        # New carried-state read-model (property_listings table, populated
        # by the projector). Consumed by the events_worker handlers.
        # Optional for backwards-compat with existing tests that only
        # need the legacy read path.
        self.property_listing_repo = property_listing_repo
        self.address_parser = address_parser
