"""Unit tests for EnrichProperty's Phase 2 (_enrich_metadata).

Spec: 2026-05-poi-rich-metadata. Asserts:
- Successful POIs get address / image_urls / reviews populated.
- Per-POI fail-silent: one failure doesn't affect others.
- Reviews blacklist: HOSPITAL/SCHOOL/KINDERGARTEN/POLICE_STATION never
  surface reviews, even if Google returned them.
- Manual POIs (no place_id) are skipped.
- include_reviews=False is passed for blacklisted categories.
"""

from datetime import datetime, timezone
from uuid import uuid4

from properties.adapters.inmemory.inmemory_places_service import (
    InMemoryPlacesService,
)
from properties.adapters.inmemory.inmemory_property_poi_repo import (
    InMemoryPropertyPoiRepository,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.use_cases.enrich_property import (
    REVIEWS_BLACKLIST,
    EnrichProperty,
)
from properties.domain.models.nearby_place import PlaceDetails
from properties.domain.models.property_poi import PoiCategory, PropertyPoi


def _poi(*, category=PoiCategory.GROCERY, place_id="abc") -> PropertyPoi:
    now = datetime.now(timezone.utc)
    return PropertyPoi(
        id=uuid4(),
        property_id=uuid4(),
        category=category,
        name="Pingo Doce",
        distance_meters=120.0,
        latitude=38.7,
        longitude=-9.1,
        place_id=place_id,
        created_at=now,
        updated_at=now,
    )


async def _make_use_case(places_results=None):
    poi_repo = InMemoryPropertyPoiRepository()
    places = InMemoryPlacesService(results=places_results)
    use_case = EnrichProperty(
        property_repo=InMemoryPropertyRepository(),
        property_poi_repo=poi_repo,
        places_service=places,
    )
    return use_case, poi_repo, places


async def test_success_populates_all_three_fields():
    use_case, poi_repo, places = await _make_use_case()
    poi = _poi(category=PoiCategory.GROCERY, place_id="grocery-1")
    # Persist then re-load — _enrich_metadata's update_place_details
    # operates on rows already in the repo.
    await poi_repo.replace_for_property(property_id=poi.property_id, pois=[poi])
    persisted = (await poi_repo.list_by_property(poi.property_id))[0]

    places.set_place_details(
        "grocery-1",
        PlaceDetails(
            place_id="grocery-1",
            address="R. Áurea 100, 1100-063 Lisboa, Portugal",
            image_urls=[
                "https://lh3.googleusercontent.com/A",
                "https://lh3.googleusercontent.com/B",
            ],
            reviews=[
                {"author_name": "Ana", "rating": 5, "text": "Excelente!", "time": 1},
            ],
        ),
    )

    await use_case._enrich_metadata([persisted])
    refreshed = await poi_repo.get_by_id(persisted.id)
    assert refreshed.address == "R. Áurea 100, 1100-063 Lisboa, Portugal"
    assert refreshed.image_urls == [
        "https://lh3.googleusercontent.com/A",
        "https://lh3.googleusercontent.com/B",
    ]
    assert refreshed.reviews == [
        {"author_name": "Ana", "rating": 5, "text": "Excelente!", "time": 1},
    ]


async def test_blacklisted_categories_get_address_and_images_but_null_reviews():
    """For HOSPITAL / SCHOOL / KINDERGARTEN / POLICE_STATION, reviews
    must always be None — even if Google returns reviews."""
    use_case, poi_repo, places = await _make_use_case()
    for cat in REVIEWS_BLACKLIST:
        place_id = f"{cat.value}-1"
        poi = _poi(category=cat, place_id=place_id)
        await poi_repo.replace_for_property(property_id=poi.property_id, pois=[poi])
        # Defensive: seed a PlaceDetails *with* reviews so we can verify
        # they get filtered out by the use case even if the adapter
        # ignored include_reviews=False.
        places.set_place_details(
            place_id,
            PlaceDetails(
                place_id=place_id,
                address="Rua Test 1",
                image_urls=["https://lh3.googleusercontent.com/X"],
                reviews=[{"author_name": "Z", "rating": 1, "text": "uh"}],
            ),
        )

        persisted = (await poi_repo.list_by_property(poi.property_id))[0]
        await use_case._enrich_metadata([persisted])
        refreshed = await poi_repo.get_by_id(persisted.id)
        assert refreshed.address == "Rua Test 1"
        assert refreshed.image_urls == ["https://lh3.googleusercontent.com/X"]
        assert refreshed.reviews is None, f"reviews must be None for blacklisted {cat.value}"


async def test_partial_failure_does_not_affect_other_pois():
    """One POI's get_place_details returns None — that POI keeps
    defaults; other POIs still get enriched."""
    use_case, poi_repo, places = await _make_use_case()
    property_id = uuid4()
    poi_a = _poi(category=PoiCategory.RESTAURANT, place_id="restaurant-a")
    poi_a = PropertyPoi(**{**poi_a.__dict__, "property_id": property_id})
    poi_b = _poi(category=PoiCategory.RESTAURANT, place_id="restaurant-b")
    poi_b = PropertyPoi(**{**poi_b.__dict__, "property_id": property_id})
    await poi_repo.replace_for_property(property_id=property_id, pois=[poi_a, poi_b])

    # A succeeds, B fails (None).
    places.set_place_details(
        "restaurant-a",
        PlaceDetails(
            place_id="restaurant-a",
            address="Rua A",
            image_urls=["https://cdn/a"],
            reviews=[{"author_name": "x", "rating": 4, "text": "ok"}],
        ),
    )
    places.set_place_details("restaurant-b", None)

    persisted = await poi_repo.list_by_property(property_id)
    await use_case._enrich_metadata(persisted)

    # Map by place_id since list ordering is by created_at.
    by_pid = {p.place_id: p for p in await poi_repo.list_by_property(property_id)}
    assert by_pid["restaurant-a"].address == "Rua A"
    assert by_pid["restaurant-a"].image_urls == ["https://cdn/a"]
    assert by_pid["restaurant-a"].reviews == [{"author_name": "x", "rating": 4, "text": "ok"}]
    # B's metadata stays at the default (no place_details was set).
    assert by_pid["restaurant-b"].address is None
    assert by_pid["restaurant-b"].image_urls == []
    assert by_pid["restaurant-b"].reviews is None


async def test_pois_without_place_id_are_skipped():
    """Manually-entered POIs have no place_id — they must not trigger
    a Place Details call."""
    use_case, poi_repo, places = await _make_use_case()
    poi = _poi(category=PoiCategory.GROCERY, place_id=None)
    await poi_repo.replace_for_property(property_id=poi.property_id, pois=[poi])
    persisted = (await poi_repo.list_by_property(poi.property_id))[0]

    # No PlaceDetails seeded — if _enrich_metadata called the service,
    # InMemoryPlacesService.get_place_details would return None and we'd
    # fall through. The real assertion: no exceptions, no row mutation.
    await use_case._enrich_metadata([persisted])
    refreshed = await poi_repo.get_by_id(persisted.id)
    assert refreshed.address is None
    assert refreshed.image_urls == []
    assert refreshed.reviews is None


async def test_empty_input_is_a_noop():
    use_case, _, _ = await _make_use_case()
    # Just verify no exception.
    await use_case._enrich_metadata([])


async def test_include_reviews_false_passed_for_blacklisted_categories():
    """Verifies the cost-aware contract — for blacklisted categories,
    we pass include_reviews=False to the PlacesService so the underlying
    Google call doesn't request the atmosphere SKU."""
    use_case, poi_repo, places = await _make_use_case()

    # Track the include_reviews values the adapter saw.
    seen_calls: list[tuple[str, bool]] = []
    original = places.get_place_details

    async def spy(place_id, *, include_reviews=True):
        seen_calls.append((place_id, include_reviews))
        return await original(place_id, include_reviews=include_reviews)

    places.get_place_details = spy  # type: ignore[method-assign]

    pois = [
        _poi(category=PoiCategory.GROCERY, place_id="g-1"),
        _poi(category=PoiCategory.SCHOOL, place_id="s-1"),  # blacklisted
        _poi(category=PoiCategory.RESTAURANT, place_id="r-1"),
    ]
    for p in pois:
        await poi_repo.replace_for_property(property_id=p.property_id, pois=[p])
        persisted = (await poi_repo.list_by_property(p.property_id))[0]
        await use_case._enrich_metadata([persisted])

    assert ("g-1", True) in seen_calls
    assert ("s-1", False) in seen_calls
    assert ("r-1", True) in seen_calls
