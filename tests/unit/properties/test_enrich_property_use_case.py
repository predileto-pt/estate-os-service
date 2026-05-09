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
    CATEGORY_TO_PLACE_TYPES,
    EnrichProperty,
)
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)
from properties.domain.models.nearby_place import NearbyPlace
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
    """Returns canned per-place_type results and records every call."""

    def __init__(
        self,
        results_by_place_type: dict[str, list[NearbyPlace]] | None = None,
        raise_on_place_types: set[str] | None = None,
    ) -> None:
        self.results = results_by_place_type or {}
        self.raise_on = raise_on_place_types or set()
        self.calls: list[tuple[float, float, str, int]] = []

    async def find_nearby(
        self,
        latitude: float,
        longitude: float,
        place_type: str,
        radius_meters: int = 5000,
        keyword: str | None = None,
    ) -> list[NearbyPlace]:
        self.calls.append((latitude, longitude, place_type, radius_meters))
        if place_type in self.raise_on:
            raise RuntimeError(f"Simulated provider failure for {place_type}")
        return self.results.get(place_type, [])


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
        place_type: [_place(f"{place_type}-1", place_id=f"p-{place_type}")]
        for types in CATEGORY_TO_PLACE_TYPES.values()
        for place_type in types
    }
    places = TrackingPlacesService(results_by_place_type=results)

    use_case = EnrichProperty(
        property_repo=property_repo,
        property_poi_repo=property_poi_repo,
        places_service=places,
    )
    await use_case.execute(property_id=prop.id, force=False, requested_by_user_id=USER_ID)

    # 18 categories, with PUBLIC_TRANSIT contributing 4 place_types and others 1 each
    # ⇒ 17 single-type calls + 4 transit calls = 21 calls total.
    expected_call_count = sum(len(types) for types in CATEGORY_TO_PLACE_TYPES.values())
    assert len(places.calls) == expected_call_count
    assert expected_call_count == 21


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
    for school_place_type in CATEGORY_TO_PLACE_TYPES[PoiCategory.SCHOOL]:
        assert school_place_type not in called_place_types

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
    all_place_types = {pt for types in CATEGORY_TO_PLACE_TYPES.values() for pt in types}
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
    all_place_types = {pt for types in CATEGORY_TO_PLACE_TYPES.values() for pt in types}
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
