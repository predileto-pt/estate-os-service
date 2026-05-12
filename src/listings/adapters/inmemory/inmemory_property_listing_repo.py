"""In-memory `PropertyListingRepository` for tests.

Same idempotency semantics as the SQLAlchemy adapter:
`upsert_from_event` drops the write when the incoming
`source_aggregate_version` is <= the stored value; `delete_if_newer`
drops the delete when the incoming version is <= stored.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from listings.application.ports.address_searcher import ParsedAddress
from listings.application.ports.get_agency_contact import AgencyContact
from listings.application.ports.repositories.property_listing_repository import (
    PropertyListingRepository,
)
from listings.domain.location_filter import LocationFilter
from listings.domain.models import ListingType, PropertyStatus, Typology
from listings.domain.pagination import ListCursor
from listings.domain.parsed_query import ParsedQuery
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import (
    ListingImage,
    ListingPoi,
    ListingPrice,
    PropertyListing,
)


class InMemoryPropertyListingRepository(PropertyListingRepository):
    def __init__(self) -> None:
        self._rows: dict[UUID, PropertyListing] = {}

    async def get_by_id(self, property_id: UUID) -> PropertyListing | None:
        return self._rows.get(property_id)

    # ──────────── Read side (public + admin route handlers) ────────────

    def _matches_filters(self, listing: PropertyListing, filters: PropertyFilters) -> bool:
        if listing.status != PropertyStatus.ACTIVE:
            return False
        if filters.listing_type is not None and listing.listing_type != filters.listing_type:
            return False
        if filters.typology is not None and listing.typology != filters.typology:
            return False
        if filters.parish is not None and listing.parish != filters.parish:
            return False
        if filters.municipality is not None and listing.municipality != filters.municipality:
            return False
        if filters.district is not None and listing.district != filters.district:
            return False
        if filters.min_price is not None:
            if listing.min_price is None or listing.min_price < filters.min_price:
                return False
        if filters.max_price is not None:
            if listing.min_price is None or listing.min_price > filters.max_price:
                return False
        return True

    def _matched_rows(
        self, filters: PropertyFilters, organization_id: UUID | None = None
    ) -> list[PropertyListing]:
        rows = list(self._rows.values())
        if organization_id is not None:
            rows = [r for r in rows if r.organization_id == organization_id]
        rows = [r for r in rows if self._matches_filters(r, filters)]
        rows.sort(key=lambda r: (r.created_at, str(r.id)), reverse=True)
        return rows

    async def list_active(self, filters: PropertyFilters) -> list[PropertyListing]:
        rows = self._matched_rows(filters)
        return rows[filters.offset : filters.offset + filters.limit]

    async def count_active(self, filters: PropertyFilters) -> int:
        return len(self._matched_rows(filters))

    async def list_active_keyset(
        self,
        *,
        filters: PropertyFilters,
        cursor: ListCursor | None,
        limit: int,
    ) -> tuple[list[PropertyListing], bool]:
        rows = self._matched_rows(filters)
        if cursor is not None:
            # Mirror the SQL: strictly past the cursor position in
            # (created_at DESC, id DESC) order.
            rows = [
                r for r in rows if (r.created_at, str(r.id)) < (cursor.created_at, str(cursor.id))
            ]
        page = rows[: limit + 1]
        has_more = len(page) > limit
        return page[:limit], has_more

    async def list_active_for_organization(
        self, organization_id: UUID, filters: PropertyFilters
    ) -> list[PropertyListing]:
        rows = self._matched_rows(filters, organization_id=organization_id)
        return rows[filters.offset : filters.offset + filters.limit]

    async def count_active_for_organization(
        self, organization_id: UUID, filters: PropertyFilters
    ) -> int:
        return len(self._matched_rows(filters, organization_id=organization_id))

    # ──────────── Search read path (hydrate) ────────────

    async def list_by_ids(self, ids: list[UUID]) -> list[PropertyListing]:
        if not ids:
            return []
        wanted = set(ids)
        # ACTIVE filter at the "SQL" level (mirrors the SqlAlchemy adapter's
        # WHERE status='active'). Order is unspecified per the port docstring.
        return [
            row
            for row in self._rows.values()
            if row.id in wanted and row.status == PropertyStatus.ACTIVE
        ]

    async def list_ids_for_search(
        self,
        *,
        location: LocationFilter,
        route_filters: PropertyFilters,
        parsed: ParsedQuery,
        limit: int,
    ) -> list[UUID]:
        """Python-side mirror of the SQL pre-filter. Same semantics —
        status='active' + location + route-param hard filters +
        ParsedQuery soft-hard (NULL admitted) — applied via predicates
        in a list comprehension."""
        # Conflict resolution: route-param wins WHEN SET; parsed
        # applies when route is None.
        eff_typology = (
            route_filters.typology if route_filters.typology is not None else parsed.typology
        )
        eff_min_price = (
            route_filters.min_price if route_filters.min_price is not None else parsed.min_price
        )
        eff_max_price = (
            route_filters.max_price if route_filters.max_price is not None else parsed.max_price
        )

        def _matches(row: PropertyListing) -> bool:
            if row.status != PropertyStatus.ACTIVE:
                return False
            if location.parish and row.parish != location.parish:
                return False
            if location.municipality and row.municipality != location.municipality:
                return False
            if location.district and row.district != location.district:
                return False

            if eff_typology is not None and row.typology != eff_typology:
                return False
            if (
                route_filters.listing_type is not None
                and row.listing_type != route_filters.listing_type
            ):
                return False

            if eff_min_price is not None:
                if row.min_price is not None and row.min_price < eff_min_price:
                    return False
            if eff_max_price is not None:
                if row.min_price is not None and row.min_price > eff_max_price:
                    return False

            # ParsedQuery soft-hard filters — NULL admitted (the
            # column being None doesn't fail; the column being set
            # and failing the criterion does).
            if parsed.min_bedrooms is not None:
                if row.num_of_bedrooms is not None and row.num_of_bedrooms < parsed.min_bedrooms:
                    return False
            if parsed.min_bathrooms is not None:
                if row.num_of_bathrooms is not None and row.num_of_bathrooms < parsed.min_bathrooms:
                    return False
            if parsed.min_area_m2 is not None:
                if row.area_in_m2 is not None and row.area_in_m2 < parsed.min_area_m2:
                    return False
            if parsed.max_area_m2 is not None:
                if row.area_in_m2 is not None and row.area_in_m2 > parsed.max_area_m2:
                    return False
            if parsed.has_pool is True:
                if row.has_pool is not None and row.has_pool is not True:
                    return False
            if parsed.has_garden is True:
                if row.has_garden is not None and row.has_garden is not True:
                    return False
            if parsed.has_elevator is True:
                if row.has_elevator is not None and row.has_elevator is not True:
                    return False
            if parsed.has_parking is True:
                # has_parking derives from parking_spaces > 0; NULL admitted.
                if row.parking_spaces is not None and row.parking_spaces <= 0:
                    return False
            return True

        ids: list[UUID] = []
        for row in self._rows.values():
            if _matches(row):
                ids.append(row.id)
                if len(ids) >= limit:
                    break
        return ids

    # NOTE: `list_locations` was removed 2026-05-11 — /locations now
    # reads from a static JSON catalog. See port docstring.

    # ──────────── Write side (listings worker handlers) ───────────────

    async def upsert_from_event(
        self,
        *,
        event_data: dict,
        source_occurred_at: datetime,
        agency: "AgencyContact | None" = None,
    ) -> PropertyListing | None:
        property_id = UUID(event_data["id"])
        incoming_version: int = event_data["aggregate_version"]
        existing = self._rows.get(property_id)
        if existing is not None and existing.source_aggregate_version >= incoming_version:
            return None  # idempotency guard — drop older/equal event

        now = datetime.now(timezone.utc)
        chars = event_data.get("characteristics") or {}
        prices = event_data.get("prices") or []
        min_price: Decimal | None = None
        for p in prices:
            try:
                amt = Decimal(str(p["amount"]))
            except (InvalidOperation, KeyError, TypeError):
                continue
            if min_price is None or amt < min_price:
                min_price = amt

        images = event_data.get("images") or []
        first_image = None
        for img in images:
            if img.get("display_order") == 0:
                first_image = img.get("s3_key")
                break
        if first_image is None and images:
            first_image = images[0].get("s3_key")

        # POIs: when the snapshot carries `pois` it's authoritative; when
        # absent, preserve whatever's on the existing row.
        # Rich fields (address, image_urls, reviews) — ADR-014 §13/§14:
        # default to None / [] for snapshots that pre-date the rich
        # payload (back-compat with old events still in the queue).
        if "pois" in event_data:
            pois = [
                ListingPoi(
                    category=p["category"],
                    name=p["name"],
                    distance_meters=float(p["distance_meters"]),
                    address=p.get("address"),
                    image_urls=list(p.get("image_urls") or []),
                    reviews=p.get("reviews"),
                )
                for p in (event_data.get("pois") or [])
            ]
        else:
            pois = list(existing.pois) if existing else []

        # Full image + price lists (lean shape, snapshot-derived).
        images_list = [
            ListingImage(
                id=UUID(img["id"]),
                s3_key=img["s3_key"],
                display_order=int(img["display_order"]),
            )
            for img in images
            if "id" in img and "s3_key" in img and "display_order" in img
        ]
        prices_list = [
            ListingPrice(
                amount=Decimal(str(p["amount"])),
                listing_type=ListingType(p["listing_type"]),
            )
            for p in prices
            if "amount" in p and "listing_type" in p
        ]

        listing = PropertyListing(
            id=property_id,
            organization_id=UUID(event_data["organization_id"]),
            title=event_data.get("title") or "Property",
            status=PropertyStatus(event_data["status"]),
            listing_type=ListingType(event_data["listing_type"]),
            typology=Typology(event_data["typology"]),
            # `address` removed from this read-model (spec
            # 2026-05-property-address-enrichment-fix). The
            # event still carries `data["address"]`; we don't store it.
            parish=existing.parish if existing else None,
            municipality=existing.municipality if existing else None,
            district=existing.district if existing else None,
            location_enriched_at=existing.location_enriched_at if existing else None,
            location_enrichment_attempts=(existing.location_enrichment_attempts if existing else 0),
            num_of_bedrooms=chars.get("num_of_bedrooms"),
            num_of_bathrooms=chars.get("num_of_bathrooms"),
            area_in_m2=(int(chars["area_in_m2"]) if chars.get("area_in_m2") is not None else None),
            has_pool=chars.get("has_pool"),
            has_garden=chars.get("has_garden"),
            has_elevator=chars.get("has_elevator"),
            floor=chars.get("floor"),
            parking_spaces=chars.get("parking_spaces"),
            built_at=chars.get("built_at"),
            energy_rating=chars.get("energy_rating"),
            country=existing.country if existing else (event_data.get("country") or "Portugal"),
            city=existing.city if existing else None,
            state=existing.state if existing else None,
            region=existing.region if existing else None,
            min_price=min_price,
            first_image_s3_key=first_image,
            images=images_list,
            prices=prices_list,
            description=event_data.get("description"),
            latitude=event_data.get("latitude"),
            longitude=event_data.get("longitude"),
            source_aggregate_version=incoming_version,
            source_occurred_at=source_occurred_at,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            pois=pois,
            # Embedding columns are owned by the embedding handler — preserve
            # what's there (initial value for fresh row, untouched on update).
            embedding_text_hash=existing.embedding_text_hash if existing else None,
            canonical_text_version=existing.canonical_text_version if existing else None,
            embedding_model_version=existing.embedding_model_version if existing else None,
            embedded_at=existing.embedded_at if existing else None,
            embedding_status=existing.embedding_status if existing else "PENDING",
            # Agency contact (spec 2026-05-listings-agency-contact). When the
            # projector supplies `agency=...` write the three fields. When it's
            # None (legacy paths that don't resolve), preserve whatever the
            # existing row had.
            agency_name=(
                agency.name if agency is not None else (existing.agency_name if existing else None)
            ),
            agency_email=(
                agency.email
                if agency is not None
                else (existing.agency_email if existing else None)
            ),
            agency_phone=(
                agency.phone
                if agency is not None
                else (existing.agency_phone if existing else None)
            ),
        )
        self._rows[property_id] = listing
        return listing

    async def delete_if_newer(
        self,
        *,
        property_id: UUID,
        source_aggregate_version: int,
        source_occurred_at: datetime,
    ) -> bool:
        existing = self._rows.get(property_id)
        if existing is None:
            return False
        if existing.source_aggregate_version >= source_aggregate_version:
            return False
        del self._rows[property_id]
        return True

    async def update_location(
        self,
        *,
        property_id: UUID,
        parsed: ParsedAddress,
    ) -> PropertyListing | None:
        existing = self._rows.get(property_id)
        if existing is None:
            return None
        existing.parish = parsed.parish
        existing.municipality = parsed.municipality
        existing.district = parsed.district
        existing.country = parsed.country
        existing.city = parsed.city
        existing.state = parsed.state
        existing.region = parsed.region
        existing.location_enriched_at = datetime.now(timezone.utc)
        existing.location_enrichment_attempts += 1
        return existing

    async def increment_enrichment_attempts(self, *, property_id: UUID) -> PropertyListing | None:
        existing = self._rows.get(property_id)
        if existing is None:
            return None
        existing.location_enrichment_attempts += 1
        return existing

    async def set_embedding_indexed(
        self,
        *,
        property_id: UUID,
        embedding_text_hash: str,
        canonical_text_version: str,
        embedding_model_version: str,
        embedded_at: datetime,
    ) -> PropertyListing | None:
        existing = self._rows.get(property_id)
        if existing is None:
            return None
        existing.embedding_text_hash = embedding_text_hash
        existing.canonical_text_version = canonical_text_version
        existing.embedding_model_version = embedding_model_version
        existing.embedded_at = embedded_at
        existing.embedding_status = "INDEXED"
        return existing

    async def set_embedding_status(
        self, *, property_id: UUID, status: str
    ) -> PropertyListing | None:
        existing = self._rows.get(property_id)
        if existing is None:
            return None
        existing.embedding_status = status
        return existing
