from listings.application.ports.listing_repository import ListingRepository
from listings.application.use_cases.get_property import GetProperty
from listings.application.use_cases.list_properties import ListProperties


class Container:
    def __init__(self, listing_repo: ListingRepository) -> None:
        self.listing_repo = listing_repo
        self.list_properties = ListProperties(listing_repo=listing_repo)
        self.get_property = GetProperty(listing_repo=listing_repo)
