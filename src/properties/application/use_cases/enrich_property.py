"""Stage 1+2 of the POI enrichment workflow.

Consumed by the worker on `ENRICH_PROPERTY_REQUESTED.v1`. Discovers
POIs per category from the configured `PlacesService` provider, ranks
them via the proximity ranker, preserves manually-edited categories
unless `force=True`, and atomically replaces the property's POI catalog.

See `.claude/specs/active/2026-05-property-poi-discovery-workflow.md`
for the full design and `.claude/specs/active/2026-05-unified-job-tracking.md`
for the JobTracker integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import structlog

from properties.application.events.property_event import emit_property_updated
from properties.application.ports.places_service import PlacesService
from properties.application.ports.repositories.property_poi_repository import (
    PropertyPoiRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
)
from properties.domain.models.nearby_place import NearbyPlace
from properties.domain.models.property_poi import PoiCategory, PropertyPoi
from properties.domain.services.proximity_ranker import (
    KNOWN_BRANDS_BY_CATEGORY,
    rank_top_places,
)
from shared.events.ports import EventPublisher
from shared.jobs.application.ports.job_tracker import JobTracker
from shared.utils.concurrency import gather_with_concurrency

log = structlog.get_logger()


# Category → underlying provider place_type(s). Multi-type categories
# like PUBLIC_TRANSIT produce multiple find_nearby calls per category.
CATEGORY_TO_PLACE_TYPES: dict[PoiCategory, list[str]] = {
    PoiCategory.HOSPITAL: ["hospital"],
    PoiCategory.BANK: ["bank"],
    PoiCategory.GROCERY: ["supermarket"],
    PoiCategory.SCHOOL: ["school"],
    PoiCategory.PHARMACY: ["pharmacy"],
    PoiCategory.GYM: ["gym"],
    PoiCategory.RESTAURANT: ["restaurant"],
    PoiCategory.COFFEE_SHOP: ["cafe"],
    PoiCategory.LAUNDRY: ["laundry"],
    PoiCategory.GAS_STATION: ["gas_station"],
    PoiCategory.PUBLIC_TRANSIT: [
        "bus_station",
        "subway_station",
        "train_station",
        "transit_station",
    ],
    # Google Places has no "kindergarten" — closest match is primary_school.
    PoiCategory.KINDERGARTEN: ["primary_school"],
    PoiCategory.PARK: ["park"],
    PoiCategory.POST_OFFICE: ["post_office"],
    PoiCategory.LIBRARY: ["library"],
    PoiCategory.SHOPPING_MALL: ["shopping_mall"],
    PoiCategory.BAKERY: ["bakery"],
    PoiCategory.POLICE_STATION: ["police"],
}

DISCOVERY_RADIUS_METERS = 1500
TOP_N_PER_CATEGORY = 5
PLACES_CONCURRENCY_LIMIT = 5

# Categories whose Place Details we still fetch (for address + photos)
# but whose `reviews` we deliberately drop. Sensitive contexts where
# Google reviews are inappropriate or irrelevant in a real-estate
# listing. Spec: 2026-05-poi-rich-metadata §Reviews blacklist.
REVIEWS_BLACKLIST: frozenset[PoiCategory] = frozenset(
    {
        PoiCategory.HOSPITAL,
        PoiCategory.SCHOOL,
        PoiCategory.KINDERGARTEN,
        PoiCategory.POLICE_STATION,
    }
)


@dataclass(frozen=True)
class CategoryDiscoveryResult:
    category: PoiCategory
    places: list[NearbyPlace]
    had_failures: bool


# Maps known exceptions raised inside `_run` to a stable `error_code`
# string for the unified job row. Anything not listed falls through to
# `enrich_failed`. ADR-012 §Producing-context integration.
_ERROR_CODE_BY_EXC: dict[type[Exception], str] = {
    PropertyNotFoundError: "property_not_found",
    PropertyMissingCoordinatesError: "property_missing_coordinates",
}


class EnrichProperty:
    def __init__(
        self,
        property_repo: PropertyRepository,
        property_poi_repo: PropertyPoiRepository,
        places_service: PlacesService,
        job_tracker: JobTracker | None = None,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.property_poi_repo = property_poi_repo
        self.places_service = places_service
        self.job_tracker = job_tracker
        self.domain_event_publisher = domain_event_publisher

    async def execute(
        self,
        *,
        property_id: UUID,
        force: bool,
        requested_by_user_id: UUID,
        tracked_job_id: UUID | None = None,
    ) -> list[PropertyPoi]:
        try:
            persisted = await self._run(
                property_id=property_id,
                force=force,
                requested_by_user_id=requested_by_user_id,
            )
        except Exception as exc:
            error_code = _classify_error(exc)
            if self.job_tracker is not None and tracked_job_id is not None:
                try:
                    await self.job_tracker.fail(
                        tracked_job_id,
                        error_code=error_code,
                        error_message=str(exc),
                    )
                except Exception:
                    log.exception(
                        "enrich_property.job_tracker_fail_failed",
                        tracked_job_id=str(tracked_job_id),
                    )
            raise

        # Success path — record the unified completion. The result_summary
        # carries the dashboard-visible counts.
        if self.job_tracker is not None and tracked_job_id is not None:
            try:
                await self.job_tracker.complete(
                    tracked_job_id,
                    result_summary={
                        "pois_discovered": persisted["discovered_count"],
                        "categories_processed": persisted["run_categories"],
                        "had_failures": persisted["had_failures"],
                    },
                )
            except Exception:
                log.exception(
                    "enrich_property.job_tracker_complete_failed",
                    tracked_job_id=str(tracked_job_id),
                )
        return persisted["pois"]

    async def _run(
        self,
        *,
        property_id: UUID,
        force: bool,
        requested_by_user_id: UUID,
    ) -> dict:
        # 1. Load property + coordinate guard.
        prop = await self.property_repo.get_by_id(property_id)
        if prop is None:
            raise PropertyNotFoundError(str(property_id))
        if prop.latitude is None or prop.longitude is None:
            raise PropertyMissingCoordinatesError(str(property_id))

        # 2. Existing POIs + skip-set for manually-edited categories.
        existing = await self.property_poi_repo.list_by_property(property_id)
        skipped_categories: set[PoiCategory] = (
            set() if force else {poi.category for poi in existing if poi.manually_edited}
        )
        categories_to_run = [cat for cat in PoiCategory if cat not in skipped_categories]

        # 3. Discover + rank per category, concurrently.
        results: list[CategoryDiscoveryResult] = await gather_with_concurrency(
            PLACES_CONCURRENCY_LIMIT,
            *(
                self._discover_category(cat, prop.latitude, prop.longitude)
                for cat in categories_to_run
            ),
        )

        ranked_results: dict[PoiCategory, list[NearbyPlace]] = {}
        for r in results:
            brands = KNOWN_BRANDS_BY_CATEGORY.get(r.category.value)
            ranked_results[r.category] = rank_top_places(
                r.places, known_brands=brands, limit=TOP_N_PER_CATEGORY
            )

        # 4. Provider-down guard: every run category empty AND any failure.
        any_failures = any(r.had_failures for r in results)
        total_discovered = sum(len(places) for places in ranked_results.values())
        if categories_to_run and total_discovered == 0 and any_failures:
            log.warning(
                "enrich_property.provider_down_detected",
                property_id=str(property_id),
                category_count=len(categories_to_run),
            )
            raise ProviderUnavailableError(
                f"POI discovery failed for property {property_id}: "
                "every category returned 0 results AND at least one find_nearby call raised. "
                "Treating as provider outage; SQS will retry."
            )

        # 5. Compose final list — preserve all rows in skipped categories
        #    (manual + auto), overlay newly-discovered rows for run categories.
        preserved_pois = [poi for poi in existing if poi.category in skipped_categories]
        discovered_pois = [
            PropertyPoi(
                id=uuid4(),
                property_id=property_id,
                category=category,
                name=place.name,
                distance_meters=place.distance_meters,
                latitude=place.latitude,
                longitude=place.longitude,
                place_id=place.place_id,
                metadata={"provider": "google"},
                manually_edited=False,
            )
            for category, places in ranked_results.items()
            for place in places
        ]
        final_list = preserved_pois + discovered_pois

        # 6. Persist + bump version.
        persisted = await self.property_poi_repo.replace_for_property(
            property_id=property_id, pois=final_list
        )

        # 7. Audit log if force=True wiped manually-edited rows.
        manual_count = sum(1 for poi in existing if poi.manually_edited)
        if force and manual_count > 0:
            log.warning(
                "enrich_property.force_overwrote_manual_edits",
                property_id=str(property_id),
                wiped_count=manual_count,
                requested_by_user_id=str(requested_by_user_id),
            )

        refreshed = await self.property_repo.bump_aggregate_version(property_id)

        # Emit `PROPERTY_UPDATED.v1` so the listings projector picks up
        # the new POI catalog and the embedding handler re-runs with
        # `NEARBY:` populated. Lean snapshot shape (category, name,
        # distance_meters) is fully written by Phase 1, so we can fire
        # before Phase 2 metadata fan-out — listings doesn't read the
        # Phase 2 fields. Spec
        # `2026-05-property-enrich-emits-update-with-pois.md`.
        await emit_property_updated(self.domain_event_publisher, refreshed, pois=persisted)

        # Phase 2: fan out Place Details for the persisted POIs to fetch
        # address + image_urls + reviews. Per-POI fail-silent — Phase 1
        # is already committed; Phase 2 is best-effort. Spec:
        # 2026-05-poi-rich-metadata §Workflow integration.
        await self._enrich_metadata(persisted)

        log.info(
            "enrich_property.completed",
            property_id=str(property_id),
            run_categories=len(categories_to_run),
            skipped_categories=len(skipped_categories),
            discovered_count=len(discovered_pois),
            # `persisted_count` is what `replace_for_property` returned —
            # if this is 0 while `discovered_count` > 0, the Supabase
            # write silently failed (RLS / wrong DB / etc).
            persisted_count=len(persisted),
            preserved_count=len(preserved_pois),
            force=force,
        )
        return {
            "pois": persisted,
            "discovered_count": len(discovered_pois),
            "run_categories": len(categories_to_run),
            "had_failures": any_failures,
        }

    async def _enrich_metadata(self, pois: list[PropertyPoi]) -> None:
        """Phase 2 of the enrichment workflow.

        For each persisted POI with a `place_id`, fan out a Place Details
        call and update the row with address / image_urls / reviews.
        Per-POI fail-silent: a failure on one POI doesn't affect the
        others. The outer caller never sees an exception.

        Reviews are dropped for blacklisted categories — see
        `REVIEWS_BLACKLIST`. The Google adapter also passes
        `include_reviews=False` to the API for those categories so we
        don't pay the atmosphere SKU on them.
        """
        targets = [p for p in pois if p.place_id]
        if not targets:
            return

        async def _one(poi: PropertyPoi) -> None:
            try:
                include_reviews = poi.category not in REVIEWS_BLACKLIST
                details = await self.places_service.get_place_details(
                    poi.place_id,  # type: ignore[arg-type]  # filtered above
                    include_reviews=include_reviews,
                )
                if details is None:
                    return
                # Defensive: enforce the blacklist on our side too in
                # case a future PlacesService implementation ignores
                # include_reviews and returns reviews anyway.
                reviews = None if poi.category in REVIEWS_BLACKLIST else details.reviews
                await self.property_poi_repo.update_place_details(
                    poi_id=poi.id,
                    address=details.address,
                    image_urls=details.image_urls,
                    reviews=reviews,
                )
            except Exception:
                log.exception(
                    "enrich_property.metadata_fetch_failed",
                    poi_id=str(poi.id),
                    place_id=poi.place_id,
                )

        await gather_with_concurrency(PLACES_CONCURRENCY_LIMIT, *(_one(p) for p in targets))

    async def _discover_category(
        self,
        category: PoiCategory,
        latitude: float,
        longitude: float,
    ) -> CategoryDiscoveryResult:
        place_types = CATEGORY_TO_PLACE_TYPES[category]
        all_places: list[NearbyPlace] = []
        had_failures = False

        for place_type in place_types:
            try:
                places = await self.places_service.find_nearby(
                    latitude=latitude,
                    longitude=longitude,
                    place_type=place_type,
                    radius_meters=DISCOVERY_RADIUS_METERS,
                )
                all_places.extend(places)
            except Exception:
                had_failures = True
                log.exception(
                    "enrich_property.find_nearby_failed",
                    category=category.value,
                    place_type=place_type,
                )

        # Dedup by place_id (multi-type categories like PUBLIC_TRANSIT can
        # return the same metro stop under both subway_station and transit_station).
        seen: set[str] = set()
        deduped: list[NearbyPlace] = []
        for p in all_places:
            if p.place_id and p.place_id in seen:
                continue
            if p.place_id:
                seen.add(p.place_id)
            deduped.append(p)

        return CategoryDiscoveryResult(category=category, places=deduped, had_failures=had_failures)


class ProviderUnavailableError(RuntimeError):
    """The Places provider returned 0 results for every category AND at
    least one underlying call raised — treat as provider outage.

    Distinct subclass so the unified error_code mapping can identify it
    without string-matching."""


_ERROR_CODE_BY_EXC[ProviderUnavailableError] = "provider_unavailable"


def _classify_error(exc: Exception) -> str:
    for exc_type, code in _ERROR_CODE_BY_EXC.items():
        if isinstance(exc, exc_type):
            return code
    return "enrich_failed"
