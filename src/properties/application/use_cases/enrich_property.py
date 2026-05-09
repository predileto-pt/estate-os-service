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
from properties.application.ports.poi_locality_filter import (
    PoiCandidate,
    PoiLocalityFilter,
)
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
from properties.domain.services.locality_scope import resolve_locality_scope
from properties.domain.services.poi_discovery_policy import (
    Country,
    CategoryDiscoveryPolicy,
    resolve_discovery_policy,
)
from properties.domain.services.proximity_ranker import (
    KNOWN_BRANDS_BY_CATEGORY,
    rank_top_places,
)
from shared.events.ports import EventPublisher
from shared.jobs.application.ports.job_tracker import JobTracker
from shared.utils.concurrency import gather_with_concurrency

log = structlog.get_logger()


@dataclass(frozen=True)
class PlaceQuery:
    """One provider call shape for a category.

    `place_type` is the Google Nearby Search type. `keyword` is an
    optional substring filter — used when several categories share the
    same `place_type` (e.g. TIRE_SHOP / AUTO_SHOP both ride on
    `car_repair`) and need to be disambiguated by name.
    """

    place_type: str
    keyword: str | None = None


# Category → underlying provider queries. Multi-query categories like
# PUBLIC_TRANSIT fan out multiple `find_nearby` calls and dedup by
# `place_id` afterwards. Categories that share a `place_type` rely on
# `keyword` to keep their results disjoint.
CATEGORY_TO_QUERIES: dict[PoiCategory, list[PlaceQuery]] = {
    PoiCategory.HOSPITAL: [PlaceQuery("hospital")],
    PoiCategory.BANK: [PlaceQuery("bank")],
    PoiCategory.GROCERY: [PlaceQuery("supermarket")],
    PoiCategory.SCHOOL: [PlaceQuery("school")],
    PoiCategory.PHARMACY: [PlaceQuery("pharmacy")],
    PoiCategory.GYM: [PlaceQuery("gym")],
    PoiCategory.RESTAURANT: [PlaceQuery("restaurant")],
    PoiCategory.COFFEE_SHOP: [PlaceQuery("cafe")],
    PoiCategory.LAUNDRY: [PlaceQuery("laundry")],
    PoiCategory.GAS_STATION: [PlaceQuery("gas_station")],
    PoiCategory.PUBLIC_TRANSIT: [
        PlaceQuery("bus_station"),
        PlaceQuery("subway_station"),
        PlaceQuery("train_station"),
        PlaceQuery("transit_station"),
    ],
    # Google Places has no "kindergarten" — closest match is primary_school.
    PoiCategory.KINDERGARTEN: [PlaceQuery("primary_school")],
    PoiCategory.PARK: [PlaceQuery("park")],
    PoiCategory.POST_OFFICE: [PlaceQuery("post_office")],
    PoiCategory.LIBRARY: [PlaceQuery("library")],
    PoiCategory.SHOPPING_MALL: [PlaceQuery("shopping_mall")],
    PoiCategory.BAKERY: [PlaceQuery("bakery")],
    PoiCategory.POLICE_STATION: [PlaceQuery("police")],
    # Both ride on Google's `car_repair`; PT keywords keep them
    # disjoint. Generic English fallback names are intentionally
    # omitted — the product is PT-first today.
    PoiCategory.TIRE_SHOP: [PlaceQuery("car_repair", keyword="pneus")],
    PoiCategory.AUTO_SHOP: [PlaceQuery("car_repair", keyword="oficina mecânica")],
}

PLACES_CONCURRENCY_LIMIT = 5

# Country defaulted onto every Property today — the write-side aggregate
# doesn't yet carry a country field. Flipping this to a per-aggregate
# read is a follow-up; the policy resolver already accepts `Country`,
# raw strings, or `None`.
DEFAULT_COUNTRY: Country = Country.PORTUGAL

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
    policy: CategoryDiscoveryPolicy


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
        locality_filter: PoiLocalityFilter | None = None,
    ) -> None:
        self.property_repo = property_repo
        self.property_poi_repo = property_poi_repo
        self.places_service = places_service
        self.job_tracker = job_tracker
        self.domain_event_publisher = domain_event_publisher
        # When unset, sanitization is a no-op — useful for early-stage
        # tests / environments without an OpenAI key.
        self.locality_filter = locality_filter

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

        # 3. Discover + rank per category, concurrently. Country drives
        # `CategoryDiscoveryPolicy` selection (radius + result_limit).
        country = DEFAULT_COUNTRY
        results: list[CategoryDiscoveryResult] = await gather_with_concurrency(
            PLACES_CONCURRENCY_LIMIT,
            *(
                self._discover_category(
                    cat, prop.latitude, prop.longitude, country=country
                )
                for cat in categories_to_run
            ),
        )

        ranked_results: dict[PoiCategory, list[NearbyPlace]] = {}
        for r in results:
            brands = KNOWN_BRANDS_BY_CATEGORY.get(r.category.value)
            ranked_results[r.category] = rank_top_places(
                r.places, known_brands=brands, limit=r.policy.result_limit
            )

        # 3b. Locality sanitization. One batched LLM call: drop POIs
        #     whose vicinity puts them in a different concelho (PT) /
        #     city (everywhere else) from the property. Fail-open is
        #     handled inside the filter — exceptions there keep every
        #     candidate; we do not have to.
        ranked_results = await self._filter_by_locality(
            ranked_results=ranked_results,
            property_address=prop.address,
            country=country,
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

    async def _filter_by_locality(
        self,
        *,
        ranked_results: dict[PoiCategory, list[NearbyPlace]],
        property_address: str,
        country: Country | str | None,
    ) -> dict[PoiCategory, list[NearbyPlace]]:
        """Drop ranked candidates whose `vicinity` puts them outside
        the property's locality (PT concelho / non-PT city). No-op when
        no filter is wired or when the run yielded no place_id-bearing
        candidates. Survivors keep their `(category, NearbyPlace)`
        association so the persistence step downstream is unchanged.
        """
        if self.locality_filter is None:
            return ranked_results

        # Index NearbyPlaces by place_id, dropping any without one
        # (Google rarely omits it, but the type allows it). Skipping
        # them is the conservative choice — we can't ask the LLM about
        # an anonymous row.
        candidates: list[PoiCandidate] = []
        place_lookup: dict[str, tuple[PoiCategory, NearbyPlace]] = {}
        for category, places in ranked_results.items():
            for place in places:
                if not place.place_id:
                    continue
                place_lookup[place.place_id] = (category, place)
                candidates.append(
                    PoiCandidate(
                        place_id=place.place_id,
                        name=place.name,
                        address=place.vicinity or "",
                    )
                )

        if not candidates:
            return ranked_results

        country_str = country.value if isinstance(country, Country) else (country or "")
        locality_kind = resolve_locality_scope(country_str)

        try:
            kept = await self.locality_filter.keep_in_locality(
                property_address=property_address,
                country=country_str,
                locality_kind=locality_kind,
                candidates=candidates,
            )
        except Exception:
            # Fail-open at this layer too. The default LLM adapter
            # already swallows its own exceptions, but a custom impl
            # might not — preserve the same invariant either way.
            log.exception(
                "enrich_property.locality_filter_failed_keeping_all",
                country=country_str,
                candidate_count=len(candidates),
            )
            return ranked_results

        kept_ids = {c.place_id for c in kept}

        # Rebuild per-category survivor lists in stable order; keep
        # categories whose places had no place_id untouched.
        sanitized: dict[PoiCategory, list[NearbyPlace]] = {}
        for category, places in ranked_results.items():
            sanitized[category] = [
                p for p in places if not p.place_id or p.place_id in kept_ids
            ]
        return sanitized

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
        *,
        country: Country | str | None,
    ) -> CategoryDiscoveryResult:
        policy = resolve_discovery_policy(country, category)
        queries = CATEGORY_TO_QUERIES[category]
        all_places: list[NearbyPlace] = []
        had_failures = False

        for query in queries:
            try:
                places = await self.places_service.find_nearby(
                    latitude=latitude,
                    longitude=longitude,
                    place_type=query.place_type,
                    radius_meters=policy.radius_meters,
                    keyword=query.keyword,
                )
                all_places.extend(places)
            except Exception:
                had_failures = True
                log.exception(
                    "enrich_property.find_nearby_failed",
                    category=category.value,
                    place_type=query.place_type,
                    keyword=query.keyword,
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

        return CategoryDiscoveryResult(
            category=category,
            places=deduped,
            had_failures=had_failures,
            policy=policy,
        )


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
