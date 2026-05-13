"""Unit tests for `EnrichProperty` — the orchestrator (stage 1+2).

Covers per-category fan-out, ranking, manually-edited preservation,
multi-type dedup, force semantics, audit logging, the provider-down
guard, and aggregate_version bump.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.adapters.inmemory.inmemory_property_poi_repo import (
    InMemoryPropertyPoiRepository,
)
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.application.ports.places_service import PlacesService
from properties.application.use_cases.enrich_property import (
    CATEGORY_TO_QUERIES,
    EnrichProperty,
)
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)
from properties.domain.models.nearby_place import NearbyPlace, PlaceDetails
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_poi import PoiCategory, PropertyPoi

ORG_ID = UUID("00000000-0000-0000-0000-000000000010")
USER_ID = UUID("00000000-0000-0000-0000-000000000001")


def _property(
    *,
    latitude: float | None = 38.768,
    longitude: float | None = -9.108,
) -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=uuid4(),
        organization_id=ORG_ID,
        title="Test property",
        address="Rua A",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.DRAFT,
        description=None,
        created_at=now,
        updated_at=now,
        latitude=latitude,
        longitude=longitude,
    )


def _place(name: str, place_id: str = "", distance: float = 200.0) -> NearbyPlace:
    return NearbyPlace(
        name=name,
        distance_meters=distance,
        latitude=38.768,
        longitude=-9.108,
        place_id=place_id or f"place-{name}",
    )


def _existing_poi(
    property_id: UUID,
    *,
    category: PoiCategory,
    name: str = "Existing",
    manually_edited: bool = False,
) -> PropertyPoi:
    now = datetime.now(timezone.utc)
    return PropertyPoi(
        id=uuid4(),
        property_id=property_id,
        category=category,
        name=name,
        distance_meters=300.0,
        latitude=38.77,
        longitude=-9.11,
        manually_edited=manually_edited,
        created_at=now,
        updated_at=now,
    )


class TrackingPlacesService(PlacesService):
    """Returns canned per-place_type results and records every call.

    Phase 2 (`get_place_details`) returns `None` by default — most tests
    don't care about rich metadata. Tests that DO care pass
    `place_details_by_id={<place_id>: PlaceDetails(...)}` to seed
    per-place rich data; the use case's _enrich_metadata then writes
    `address` / `image_urls` / `reviews` onto the persisted POI rows.
    """

    def __init__(
        self,
        results_by_place_type: dict[str, list[NearbyPlace]] | None = None,
        raise_on_place_types: set[str] | None = None,
        place_details_by_id: dict[str, "PlaceDetails"] | None = None,
    ) -> None:
        self.results = results_by_place_type or {}
        self.raise_on = raise_on_place_types or set()
        self.place_details = place_details_by_id or {}
        self.calls: list[tuple[float, float, str, int, str | None]] = []

    async def find_nearby(
        self,
        latitude: float,
        longitude: float,
        place_type: str,
        radius_meters: int = 5000,
        keyword: str | None = None,
    ) -> list[NearbyPlace]:
        self.calls.append((latitude, longitude, place_type, radius_meters, keyword))
        if place_type in self.raise_on:
            raise RuntimeError(f"Simulated provider failure for {place_type}")
        # Match keyword-scoped seeds first ("place_type:keyword"), then
        # fall back to the unscoped key — same shape as the in-memory
        # adapter's `set_results`.
        if keyword and (scoped := self.results.get(f"{place_type}:{keyword}")) is not None:
            return scoped
        return self.results.get(place_type, [])

    async def get_place_details(self, place_id, *, include_reviews=True):
        details = self.place_details.get(place_id)
        if details is None or include_reviews:
            return details
        # Caller asked us to skip reviews (blacklisted category) — return
        # the rest. Mirrors the Google adapter's behavior of dropping the
        # reviews payload server-side to save the atmosphere SKU.
        from properties.domain.models.nearby_place import PlaceDetails

        return PlaceDetails(
            place_id=details.place_id,
            address=details.address,
            image_urls=details.image_urls,
            reviews=None,
        )


@pytest.fixture
def property_repo() -> InMemoryPropertyRepository:
    return InMemoryPropertyRepository()


@pytest.fixture
def property_poi_repo() -> InMemoryPropertyPoiRepository:
    return InMemoryPropertyPoiRepository()


# ── basic guards ─────────────────────────────────────────────────────────────


async def test_unknown_property_raises_not_found(property_repo, property_poi_repo):
    places = TrackingPlacesService()
    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    with pytest.raises(PropertyNotFoundError):
        await use_case.execute(property_id=uuid4(), force=False, requested_by_user_id=USER_ID)
    assert places.calls == []


async def test_missing_coordinates_raises(property_repo, property_poi_repo):
    prop = _property(latitude=None, longitude=None)
    await property_repo.save(prop)

    places = TrackingPlacesService()
    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    with pytest.raises(PropertyMissingCoordinatesError):
        await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)
    assert places.calls == []


# ── happy path / fan-out ─────────────────────────────────────────────────────


async def test_happy_path_fans_out_one_call_per_place_type(property_repo, property_poi_repo):
    prop = _property()
    await property_repo.save(prop)

    # Provide canned results for every place_type so all calls succeed.
    results = {
        query.place_type: [_place(f"{query.place_type}-1", place_id=f"p-{query.place_type}")]
        for queries in CATEGORY_TO_QUERIES.values()
        for query in queries
    }
    places = TrackingPlacesService(results_by_place_type=results)

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    # PUBLIC_TRANSIT fans out into 4 place_types; TIRE_SHOP and AUTO_SHOP
    # share `car_repair` but each is its own query (keyword-disambiguated).
    expected_call_count = sum(len(queries) for queries in CATEGORY_TO_QUERIES.values())
    assert len(places.calls) == expected_call_count


async def test_persisted_rows_are_auto_with_provider_metadata(property_repo, property_poi_repo):
    prop = _property()
    await property_repo.save(prop)

    results = {"supermarket": [_place("Pingo Doce", place_id="pd-1")]}
    places = TrackingPlacesService(results_by_place_type=results)

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    stored = await property_poi_repo.list_by_property(prop.id)
    grocery_rows = [p for p in stored if p.category == PoiCategory.GROCERY]
    assert len(grocery_rows) == 1
    assert grocery_rows[0].manually_edited is False
    assert grocery_rows[0].metadata == {"provider": "google"}


async def test_pt_municipality_wide_category_uses_wide_radius_and_caps_at_ten(
    property_repo, property_poi_repo
):
    """For Portugal restaurants we want the municipality-wide policy:
    a wide radius on the provider call AND a hard cap of 10 hits per
    category after ranking. The property is set up in PT (the use case's
    default country). 25 results in → 10 results stored.

    The cap was added on 2026-05-12: unbounded result sets ballooned
    event payloads beyond SNS's 256 KB limit and slowed Phase-2
    Place Details fan-out to minutes.
    """
    from properties.application.use_cases.enrich_property import DEFAULT_COUNTRY
    from properties.domain.services.poi_discovery_policy import (
        Country,
        MUNICIPALITY_WIDE_POLICY,
    )

    assert DEFAULT_COUNTRY is Country.PORTUGAL  # guard the test's premise
    assert MUNICIPALITY_WIDE_POLICY.result_limit == 10  # guard the cap

    prop = _property()
    await property_repo.save(prop)

    # 25 restaurants — capped to 10 by the municipality-wide policy.
    restaurants = [_place(f"Tasca {i}", place_id=f"r-{i}", distance=100.0 + i) for i in range(25)]
    places = TrackingPlacesService(results_by_place_type={"restaurant": restaurants})

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    # Provider was called with the municipality-wide radius.
    restaurant_calls = [c for c in places.calls if c[2] == "restaurant"]
    assert len(restaurant_calls) == 1
    assert restaurant_calls[0][3] == MUNICIPALITY_WIDE_POLICY.radius_meters

    # Closest 10 restaurants survived to persistence; the rest were
    # truncated by the cap.
    stored = await property_poi_repo.list_by_property(prop.id)
    restaurant_rows = [p for p in stored if p.category == PoiCategory.RESTAURANT]
    assert len(restaurant_rows) == 10


async def test_tire_shop_and_auto_shop_share_place_type_disambiguated_by_keyword(
    property_repo, property_poi_repo
):
    """TIRE_SHOP and AUTO_SHOP both ride on Google's `car_repair`. The
    discovery layer disambiguates them via per-category keywords so
    each row lands in the correct bucket."""
    prop = _property()
    await property_repo.save(prop)

    # Two seeded result sets, one per keyword. The TrackingPlacesService
    # serves them based on the keyword argument so we can verify the
    # use case fans out two distinct calls to the same place_type.
    pneus_results = [_place("Borracharia Lisboa", place_id="b-lisboa")]
    oficina_results = [_place("Oficina do João", place_id="o-joao")]
    places = TrackingPlacesService(
        results_by_place_type={
            "car_repair:pneus": pneus_results,
            "car_repair:oficina mecânica": oficina_results,
        }
    )

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    # Two car_repair calls — one per keyword.
    car_repair_calls = [c for c in places.calls if c[2] == "car_repair"]
    assert len(car_repair_calls) == 2
    keywords_used = {c[4] for c in car_repair_calls}
    assert keywords_used == {"pneus", "oficina mecânica"}

    # Each shop lands in the matching category.
    stored = await property_poi_repo.list_by_property(prop.id)
    tire_rows = [p for p in stored if p.category == PoiCategory.TIRE_SHOP]
    auto_rows = [p for p in stored if p.category == PoiCategory.AUTO_SHOP]
    assert [p.name for p in tire_rows] == ["Borracharia Lisboa"]
    assert [p.name for p in auto_rows] == ["Oficina do João"]


async def test_pt_default_category_keeps_top_n_and_focused_radius(property_repo, property_poi_repo):
    """Bank is not in the PT municipality-wide set, so it stays at the
    focused default policy: small radius + top-5 cap."""
    from properties.domain.services.poi_discovery_policy import DEFAULT_POLICY

    prop = _property()
    await property_repo.save(prop)

    banks = [_place(f"Bank {i}", place_id=f"b-{i}", distance=100.0 + i) for i in range(15)]
    places = TrackingPlacesService(results_by_place_type={"bank": banks})

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    bank_calls = [c for c in places.calls if c[2] == "bank"]
    assert len(bank_calls) == 1
    assert bank_calls[0][3] == DEFAULT_POLICY.radius_meters

    stored = await property_poi_repo.list_by_property(prop.id)
    bank_rows = [p for p in stored if p.category == PoiCategory.BANK]
    assert DEFAULT_POLICY.result_limit is not None
    assert len(bank_rows) == DEFAULT_POLICY.result_limit


async def test_locality_filter_drops_rows_outside_property_locality(
    property_repo, property_poi_repo
):
    """The sanitizer is invoked between ranking and persistence:
    rows whose `place_id` the filter rejects never reach the repo,
    while accepted rows flow through unchanged.
    """
    from properties.adapters.inmemory.inmemory_poi_locality_filter import (
        DropByPlaceIdPoiLocalityFilter,
    )
    from properties.domain.services.locality_scope import LocalityKind

    prop = _property()
    await property_repo.save(prop)

    # Two restaurants: one inside the locality, one outside (it gets dropped).
    in_locality = NearbyPlace(
        name="Tasca da Esquina",
        distance_meters=200.0,
        latitude=38.768,
        longitude=-9.108,
        place_id="r-lisboa-1",
        vicinity="Rua A, Lisboa",
    )
    out_of_locality = NearbyPlace(
        name="Outro Sítio",
        distance_meters=400.0,
        latitude=38.69,
        longitude=-9.31,
        place_id="r-oeiras-1",
        vicinity="Rua B, Oeiras",
    )
    places = TrackingPlacesService(
        results_by_place_type={"restaurant": [in_locality, out_of_locality]}
    )
    locality_filter = DropByPlaceIdPoiLocalityFilter(drop_place_ids={"r-oeiras-1"})

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
        locality_filter=locality_filter,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    # Filter received the candidates with their vicinity strings + the
    # property's address + the PT municipality scope.
    assert len(locality_filter.calls) == 1
    property_address, country, scope, candidates = locality_filter.calls[0]
    assert property_address == prop.address
    assert country == "Portugal"
    assert scope is LocalityKind.MUNICIPALITY
    by_id = {c.place_id: c for c in candidates}
    assert by_id["r-lisboa-1"].address == "Rua A, Lisboa"
    assert by_id["r-oeiras-1"].address == "Rua B, Oeiras"

    # Persisted rows: only the in-locality one survived.
    stored = await property_poi_repo.list_by_property(prop.id)
    restaurant_rows = [p for p in stored if p.category == PoiCategory.RESTAURANT]
    assert [p.name for p in restaurant_rows] == ["Tasca da Esquina"]


async def test_no_locality_filter_keeps_every_ranked_row(property_repo, property_poi_repo):
    """When no filter is wired (e.g. local dev without OPENAI_API_KEY),
    sanitization is a no-op — every ranked candidate persists."""
    prop = _property()
    await property_repo.save(prop)

    a = NearbyPlace(
        name="A",
        distance_meters=100.0,
        latitude=38.768,
        longitude=-9.108,
        place_id="a-1",
        vicinity="Rua A, Lisboa",
    )
    b = NearbyPlace(
        name="B",
        distance_meters=200.0,
        latitude=38.769,
        longitude=-9.109,
        place_id="b-1",
        vicinity="Rua B, Oeiras",
    )
    places = TrackingPlacesService(results_by_place_type={"restaurant": [a, b]})

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
        # locality_filter intentionally omitted.
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    stored = await property_poi_repo.list_by_property(prop.id)
    restaurant_rows = sorted(
        (p for p in stored if p.category == PoiCategory.RESTAURANT),
        key=lambda p: p.name,
    )
    assert [p.name for p in restaurant_rows] == ["A", "B"]


async def test_aggregate_version_bumped(property_repo, property_poi_repo):
    prop = _property()
    await property_repo.save(prop)
    version_before = prop.aggregate_version

    places = TrackingPlacesService()  # empty results across the board
    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    refreshed = await property_repo.get_by_id(prop.id)
    assert refreshed.aggregate_version == version_before + 1


# ── multi-type dedup ─────────────────────────────────────────────────────────


async def test_multi_type_category_dedupes_by_place_id(property_repo, property_poi_repo):
    prop = _property()
    await property_repo.save(prop)

    # Both subway_station AND transit_station return the same metro stop.
    same_stop = _place("Saldanha", place_id="metro-saldanha")
    results = {
        "subway_station": [same_stop],
        "transit_station": [same_stop],
        "bus_station": [],
        "train_station": [],
    }
    places = TrackingPlacesService(results_by_place_type=results)

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    stored = await property_poi_repo.list_by_property(prop.id)
    transit_rows = [p for p in stored if p.category == PoiCategory.PUBLIC_TRANSIT]
    assert len(transit_rows) == 1
    assert transit_rows[0].place_id == "metro-saldanha"


# ── manually-edited preservation ─────────────────────────────────────────────


async def test_manual_category_skipped_no_calls_for_its_place_types(
    property_repo, property_poi_repo
):
    prop = _property()
    await property_repo.save(prop)

    # Seed a manually-edited row in SCHOOL.
    manual_school = _existing_poi(
        prop.id, category=PoiCategory.SCHOOL, name="Agent's School", manually_edited=True
    )
    await property_poi_repo.replace_for_property(property_id=prop.id, pois=[manual_school])

    places = TrackingPlacesService()
    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    # SCHOOL's place_type is "school" — it should NEVER appear in the call log.
    called_place_types = {c[2] for c in places.calls}
    for school_query in CATEGORY_TO_QUERIES[PoiCategory.SCHOOL]:
        assert school_query.place_type not in called_place_types

    # The manual SCHOOL row survives.
    stored = await property_poi_repo.list_by_property(prop.id)
    school_rows = [p for p in stored if p.category == PoiCategory.SCHOOL]
    assert len(school_rows) == 1
    assert school_rows[0].name == "Agent's School"
    assert school_rows[0].manually_edited is True


async def test_skipped_category_preserves_all_rows_not_just_manual(
    property_repo, property_poi_repo
):
    """The §6 fix: skipping a category preserves every row in it, not
    only the manually-edited ones. Without this fix, auto rows
    coexisting with a manual row would get silently wiped on re-run."""
    prop = _property()
    await property_repo.save(prop)

    manual = _existing_poi(
        prop.id, category=PoiCategory.SCHOOL, name="Agent's", manually_edited=True
    )
    auto1 = _existing_poi(prop.id, category=PoiCategory.SCHOOL, name="Auto-discovered 1")
    auto2 = _existing_poi(prop.id, category=PoiCategory.SCHOOL, name="Auto-discovered 2")
    await property_poi_repo.replace_for_property(property_id=prop.id, pois=[manual, auto1, auto2])

    places = TrackingPlacesService()
    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    stored = await property_poi_repo.list_by_property(prop.id)
    school_rows = [p for p in stored if p.category == PoiCategory.SCHOOL]
    assert len(school_rows) == 3
    names = {p.name for p in school_rows}
    assert names == {"Agent's", "Auto-discovered 1", "Auto-discovered 2"}


# ── force=True ───────────────────────────────────────────────────────────────


async def test_force_true_runs_every_category_and_wipes_manual_rows(
    property_repo, property_poi_repo
):
    prop = _property()
    await property_repo.save(prop)

    manual_school = _existing_poi(
        prop.id, category=PoiCategory.SCHOOL, name="Agent's School", manually_edited=True
    )
    await property_poi_repo.replace_for_property(property_id=prop.id, pois=[manual_school])

    # Discovery returns a different SCHOOL row.
    results = {"school": [_place("Discovered School", place_id="dsch")]}
    places = TrackingPlacesService(results_by_place_type=results)

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=True, requested_by_user_id=USER_ID)

    # SCHOOL place_type WAS called.
    called_place_types = {c[2] for c in places.calls}
    assert "school" in called_place_types

    # Manual row wiped, discovered row took its place.
    stored = await property_poi_repo.list_by_property(prop.id)
    school_rows = [p for p in stored if p.category == PoiCategory.SCHOOL]
    assert len(school_rows) == 1
    assert school_rows[0].name == "Discovered School"
    assert school_rows[0].manually_edited is False


async def test_force_true_emits_audit_warning_when_wiping_manual_rows(
    property_repo, property_poi_repo
):
    from structlog.testing import capture_logs

    prop = _property()
    await property_repo.save(prop)

    manual1 = _existing_poi(prop.id, category=PoiCategory.SCHOOL, manually_edited=True)
    manual2 = _existing_poi(prop.id, category=PoiCategory.GROCERY, manually_edited=True)
    await property_poi_repo.replace_for_property(property_id=prop.id, pois=[manual1, manual2])

    places = TrackingPlacesService()
    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    with capture_logs() as logs:
        await use_case.execute(property_id=prop.id, force=True, requested_by_user_id=USER_ID)

    audit_logs = [
        log for log in logs if log.get("event") == "enrich_property.force_overwrote_manual_edits"
    ]
    assert len(audit_logs) == 1
    assert audit_logs[0]["wiped_count"] == 2
    assert audit_logs[0]["requested_by_user_id"] == str(USER_ID)
    assert audit_logs[0]["log_level"] == "warning"


# ── provider-down guard ──────────────────────────────────────────────────────


async def test_provider_down_guard_reraises_when_all_calls_fail(property_repo, property_poi_repo):
    """Every find_nearby raises → orchestrator re-raises so SQS can retry.
    Pre-existing POIs in the repo are NOT touched."""
    prop = _property()
    await property_repo.save(prop)

    # Seed a pre-existing auto POI to verify it survives the failed run.
    pre_existing = _existing_poi(prop.id, category=PoiCategory.PARK, name="Pre-existing")
    await property_poi_repo.replace_for_property(property_id=prop.id, pois=[pre_existing])

    # All place_types raise.
    all_place_types = {q.place_type for queries in CATEGORY_TO_QUERIES.values() for q in queries}
    places = TrackingPlacesService(raise_on_place_types=all_place_types)

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    with pytest.raises(RuntimeError, match="provider"):
        await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    # Pre-existing POIs untouched (no replace happened).
    stored = await property_poi_repo.list_by_property(prop.id)
    assert len(stored) == 1
    assert stored[0].name == "Pre-existing"


async def test_legitimate_empty_does_not_trigger_provider_down_guard(
    property_repo, property_poi_repo
):
    """All calls succeed but every category genuinely has no POIs in radius
    → persist empty list normally, no re-raise."""
    prop = _property()
    await property_repo.save(prop)

    # Default TrackingPlacesService returns [] for every place_type, no raises.
    places = TrackingPlacesService()
    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    # Should NOT raise.
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    stored = await property_poi_repo.list_by_property(prop.id)
    assert stored == []


async def test_partial_failure_succeeds_when_other_categories_have_results(
    property_repo, property_poi_repo
):
    """If at least one category has results, the provider-down guard does NOT trigger,
    even if other categories failed. Soft-failure-per-place_type contract."""
    prop = _property()
    await property_repo.save(prop)

    # supermarket succeeds, everything else raises.
    all_place_types = {q.place_type for queries in CATEGORY_TO_QUERIES.values() for q in queries}
    failing = all_place_types - {"supermarket"}
    places = TrackingPlacesService(
        results_by_place_type={"supermarket": [_place("Pingo Doce", place_id="pd-1")]},
        raise_on_place_types=failing,
    )

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    # Should NOT raise — total_discovered > 0.
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    stored = await property_poi_repo.list_by_property(prop.id)
    grocery = [p for p in stored if p.category == PoiCategory.GROCERY]
    assert len(grocery) == 1


class _RecordingPublisher:
    def __init__(self):
        self.published: list = []

    async def publish(self, event):
        self.published.append(event)


async def test_emits_property_updated_with_pois_after_success(property_repo, property_poi_repo):
    """Spec `2026-05-property-enrich-emits-update-with-pois.md` +
    `2026-05-poi-rich-metadata`. After a successful enrichment run,
    EnrichProperty publishes PROPERTY_UPDATED.v1 carrying the POIs in
    the snapshot shape — including the rich Phase 2 fields (address,
    image_urls, reviews) — so the listings projector + detail endpoint
    response surface them. Phase 2 must run BEFORE the emit; emitting
    the pre-Phase-2 lean list silently drops the rich data."""
    from properties.domain.models.nearby_place import PlaceDetails
    from shared.events.types import PROPERTY_UPDATED_V1

    prop = _property()
    await property_repo.save(prop)
    places = TrackingPlacesService(
        results_by_place_type={"supermarket": [_place("Pingo Doce", place_id="pd-1")]},
        place_details_by_id={
            "pd-1": PlaceDetails(
                place_id="pd-1",
                address="Av. da República 12, Lisboa",
                image_urls=["https://cdn/pingo-1.jpg", "https://cdn/pingo-2.jpg"],
                reviews=[{"author": "Ana", "rating": 4, "text": "Bom"}],
            )
        },
    )
    publisher = _RecordingPublisher()

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
        domain_event_publisher=publisher,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    types = [e.event_type for e in publisher.published]
    assert PROPERTY_UPDATED_V1 in types
    event = next(e for e in publisher.published if e.event_type == PROPERTY_UPDATED_V1)
    assert "pois" in event.data
    grocery_pois = [p for p in event.data["pois"] if p["category"] == "grocery"]
    assert len(grocery_pois) == 1
    grocery = grocery_pois[0]
    # Lean fields — unchanged.
    assert grocery["name"] == "Pingo Doce"
    assert "distance_meters" in grocery
    # Rich fields — propagated from Phase 2 through the re-fetch.
    assert grocery["address"] == "Av. da República 12, Lisboa"
    assert grocery["image_urls"] == ["https://cdn/pingo-1.jpg", "https://cdn/pingo-2.jpg"]
    assert grocery["reviews"] == [{"author": "Ana", "rating": 4, "text": "Bom"}]
    # Aggregate version was bumped before emit, so the snapshot version
    # is the post-bump value.
    assert event.data["aggregate_version"] >= 1


async def test_emit_pois_carry_blacklisted_review_null_with_rich_address_and_images(
    property_repo, property_poi_repo
):
    """Defensive regression: even for review-blacklisted categories
    (school / hospital / kindergarten / police), the emit payload
    must still carry `address` and `image_urls` from Phase 2 — only
    `reviews` is suppressed. The pre-fix sequencing bug dropped ALL
    three rich fields uniformly; locking the partial-suppression
    behavior here so it can't regress to the all-or-nothing shape."""
    from properties.domain.models.nearby_place import PlaceDetails
    from shared.events.types import PROPERTY_UPDATED_V1

    prop = _property()
    await property_repo.save(prop)
    places = TrackingPlacesService(
        results_by_place_type={"school": [_place("Escola X", place_id="sch-1")]},
        place_details_by_id={
            "sch-1": PlaceDetails(
                place_id="sch-1",
                address="Rua das Flores 12",
                image_urls=["https://cdn/school.jpg"],
                reviews=[{"author": "ignored", "rating": 1}],
            )
        },
    )
    publisher = _RecordingPublisher()

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
        domain_event_publisher=publisher,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    event = next(
        e for e in publisher.published if e.event_type == PROPERTY_UPDATED_V1
    )
    school = next(p for p in event.data["pois"] if p["category"] == "school")
    assert school["address"] == "Rua das Flores 12"
    assert school["image_urls"] == ["https://cdn/school.jpg"]
    # Blacklist applies — reviews dropped even though Place Details
    # carried them.
    assert school["reviews"] is None


async def test_no_publisher_does_not_raise(property_repo, property_poi_repo):
    """When domain_event_publisher is None (e.g. test or local-dev
    container), the use case still completes successfully — the emit
    helper short-circuits on None publisher."""
    prop = _property()
    await property_repo.save(prop)
    places = TrackingPlacesService(
        results_by_place_type={"supermarket": [_place("X", place_id="x-1")]}
    )

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
        domain_event_publisher=None,
    )
    # Must not raise.
    pois = await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)
    assert len(pois) == 1
