from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from properties.application.ports.places_service import PlacesService
from properties.application.ports.repositories.property_amenity_repository import (
    PropertyAmenityRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)
from properties.domain.models.property_amenity import (
    TOP_PLACES_LIMIT,
    AmenityCategory,
    NearbyPlace,
    PropertyAmenity,
)
from properties.domain.services.amenity_ranker import rank_places, rank_top_places
from shared.utils.concurrency import gather_with_concurrency

log = structlog.get_logger()

# Max concurrent Google Places API calls per discovery run.
# Keeps us well under Google's QPS limits while still being ~5x faster
# than sequential calls.
PLACES_CONCURRENCY_LIMIT = 5

CATEGORY_PLACE_TYPE_MAP: dict[AmenityCategory, str] = {
    AmenityCategory.HOSPITAL: "hospital",
    AmenityCategory.BANK: "bank",
    AmenityCategory.GROCERY: "supermarket",
    AmenityCategory.SCHOOL: "school",
    AmenityCategory.LAUNDRY: "laundry",
    AmenityCategory.COFFEE_SHOP: "cafe",
    AmenityCategory.PHARMACY: "pharmacy",
    AmenityCategory.GYM: "gym",
    AmenityCategory.RESTAURANT: "restaurant",
}

GROCERY_CHAINS = [
    "Continente",
    "Lidl",
    "Pingo Doce",
    "Intermarché",
    "Mercadona",
]


class DiscoverPropertyAmenities:
    def __init__(
        self,
        property_repo: PropertyRepository,
        places_service: PlacesService,
        amenity_repo: PropertyAmenityRepository,
    ) -> None:
        self.property_repo = property_repo
        self.places_service = places_service
        self.amenity_repo = amenity_repo

    async def execute(self, *, property_id: str) -> list[PropertyAmenity]:
        prop = await self.property_repo.get_by_id(UUID(property_id))
        if not prop:
            raise PropertyNotFoundError(property_id)

        if prop.latitude is None or prop.longitude is None:
            raise PropertyMissingCoordinatesError(property_id)

        now = datetime.now(timezone.utc)

        # Discover all categories concurrently (max PLACES_CONCURRENCY_LIMIT at a time).
        # Each coroutine handles its own errors and returns [] on failure.
        results = await gather_with_concurrency(
            PLACES_CONCURRENCY_LIMIT,
            *(
                self._discover_category(category, prop.latitude, prop.longitude, property_id)
                for category in AmenityCategory
            ),
        )

        amenities: list[PropertyAmenity] = []
        for category, places in results:
            if not places:
                continue

            best = rank_places(places, category)
            top = rank_top_places(places, category, limit=TOP_PLACES_LIMIT)
            amenities.append(
                PropertyAmenity(
                    id=uuid4(),
                    property_id=prop.id,
                    category=category,
                    nearest_name=best.name,
                    nearest_distance_meters=best.distance_meters,
                    nearest_latitude=best.latitude,
                    nearest_longitude=best.longitude,
                    total_count=len(places),
                    created_at=now,
                    updated_at=now,
                    nearest_place_id=best.place_id,
                    nearest_google_maps_url=best.google_maps_url,
                    top_places=top,
                )
            )

        await self.amenity_repo.delete_by_property_id(prop.id)
        if amenities:
            amenities = await self.amenity_repo.save_batch(amenities)

        log.info(
            "discovery.completed",
            property_id=property_id,
            categories_found=len(amenities),
        )
        return amenities

    async def _discover_category(
        self,
        category: AmenityCategory,
        latitude: float,
        longitude: float,
        property_id: str,
    ) -> tuple[AmenityCategory, list[NearbyPlace]]:
        try:
            if category == AmenityCategory.GROCERY:
                places = await self._discover_groceries(latitude, longitude)
            else:
                place_type = CATEGORY_PLACE_TYPE_MAP[category]
                places = await self.places_service.find_nearby(
                    latitude=latitude,
                    longitude=longitude,
                    place_type=place_type,
                )
        except Exception:
            log.exception(
                "discovery.category_failed",
                property_id=property_id,
                category=category.value,
            )
            places = []

        if not places:
            log.info(
                "discovery.no_results",
                property_id=property_id,
                category=category.value,
            )

        return (category, places)

    async def _discover_groceries(self, latitude: float, longitude: float) -> list[NearbyPlace]:
        # Run all chain searches + generic search concurrently.
        async def _search_chain(keyword: str | None) -> list[NearbyPlace]:
            try:
                return await self.places_service.find_nearby(
                    latitude=latitude,
                    longitude=longitude,
                    place_type="supermarket",
                    keyword=keyword,
                )
            except Exception:
                log.exception("discovery.grocery_search_failed", keyword=keyword)
                return []

        chain_results = await gather_with_concurrency(
            PLACES_CONCURRENCY_LIMIT,
            *(_search_chain(chain) for chain in GROCERY_CHAINS),
            _search_chain(None),  # generic supermarket search
        )

        # Deduplicate by name across all results.
        seen_names: set[str] = set()
        all_places: list[NearbyPlace] = []
        for results in chain_results:
            for place in results:
                if place.name not in seen_names:
                    seen_names.add(place.name)
                    all_places.append(place)

        return all_places
