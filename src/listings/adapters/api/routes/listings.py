from decimal import Decimal
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from identity.domain.models.user import User
from listings.adapters.api.schemas import (
    CountryNode,
    CursorPageResponse,
    DistrictNode,
    ListedPropertyResponse,
    LocationTreeResponse,
    MunicipalityNode,
    PaginatedListingResponse,
    POIResponse,
    PropertyCharacteristicsResponse,
    PropertyImageResponse,
    PropertyPriceResponse,
)
from listings.adapters.api.search_validation import (
    normalize_query,
    validate_location_for_search,
)
from listings.domain.exceptions import PropertyNotFoundError
from listings.domain.location_filter import LocationFilter
from listings.domain.models import ListingType, Typology
from listings.domain.pagination import (
    CursorDecodeError,
    CursorFilterMismatchError,
    CursorVersionError,
    ListCursor,
    SearchCursor,
    decode_token,
    filter_fingerprint,
    validate_fp,
)
from listings.domain.poi_category import PoiCategory
from listings.domain.property_filters import PropertyFilters
from listings.domain.property_listing import PropertyListing
from organizations.domain.models.membership import Membership
from shared.api.dependencies import require_org_member

logger = structlog.get_logger()

router = APIRouter(tags=["property-listings"])
admin_router = APIRouter(tags=["property-listings-admin"])


async def _generate_image_urls(request: Request, prop: PropertyListing) -> dict[str, str]:
    document_storage = getattr(request.app.state, "_listing_document_storage", None)
    if not document_storage or not prop.images:
        return {}
    urls = {}
    for image in prop.images:
        urls[str(image.id)] = await document_storage.get_download_url(image.s3_key)
    return urls


def _to_response(prop: PropertyListing, image_urls: dict[str, str]) -> ListedPropertyResponse:
    """Map the projection row to the public response.

    `address` intentionally absent (privacy fix). Structured location
    fields (parish/municipality/district/country) are now exposed from
    the projection. Characteristics are flattened into a response sub-
    object — `PropertyListing` carries them as flat columns rather
    than a nested `PropertyCharacteristics` object.
    """
    # Build the characteristics block only if any field is populated.
    char_fields = {
        "area_in_m2": prop.area_in_m2,
        "num_of_bedrooms": prop.num_of_bedrooms,
        "num_of_bathrooms": prop.num_of_bathrooms,
        "built_at": prop.built_at,
        "energy_rating": prop.energy_rating,
        "floor": prop.floor,
        "parking_spaces": prop.parking_spaces,
        "has_elevator": prop.has_elevator,
        "has_garden": prop.has_garden,
        "has_pool": prop.has_pool,
    }
    characteristics = (
        PropertyCharacteristicsResponse(**char_fields)
        if any(v is not None for v in char_fields.values())
        else None
    )

    return ListedPropertyResponse(
        id=prop.id,
        organization_id=prop.organization_id,
        listing_type=prop.listing_type,
        typology=prop.typology,
        description=prop.description,
        characteristics=characteristics,
        parish=prop.parish,
        municipality=prop.municipality,
        district=prop.district,
        country=prop.country,
        latitude=prop.latitude,
        longitude=prop.longitude,
        created_at=prop.created_at,
        updated_at=prop.updated_at,
        prices=[
            PropertyPriceResponse(amount=p.amount, listing_type=p.listing_type) for p in prop.prices
        ],
        images=[
            PropertyImageResponse(
                id=img.id,
                display_order=img.display_order,
                download_url=image_urls.get(str(img.id), ""),
            )
            for img in prop.images
        ],
    )


@router.get(
    "/properties",
    response_model=CursorPageResponse,
    summary="List active properties with filters (q = semantic search)",
    responses={
        200: {
            "description": (
                "Listing results — vector-ranked when `q` is set, otherwise structured-filter "
                "order. `next_cursor` is an opaque token; pass it back as `?cursor=` for the "
                "next page. `null` means end of results."
            ),
        },
        400: {
            "description": (
                "Cursor problem. `detail` is one of: "
                "`cursor_unsupported_version` (drop cursor + refetch from head — schema bump), "
                "`cursor_invalid` (drop cursor + refetch from head — corrupt token), "
                "`cursor_kind_mismatch` (drop cursor + refetch from head — search was toggled "
                "or filters changed mode), "
                "`cursor_filter_mismatch` (drop cursor + refetch from head — user changed filters)."
            ),
        },
        422: {"description": "`q` was provided without any location filter."},
    },
)
async def list_properties(
    request: Request,
    q: str | None = Query(
        None,
        max_length=2000,
        description=(
            "Free-text semantic query. When provided, at least one of "
            "`parish`/`municipality`/`district` is required (422 otherwise)."
        ),
    ),
    listing_type: ListingType | None = Query(
        None, description="Filter by listing type (sale/purchase)"
    ),
    typology: Typology | None = Query(
        None, description="Filter by typology (house/apartment/land/ruin)"
    ),
    min_price: Decimal | None = Query(None, ge=0, description="Minimum price filter"),
    max_price: Decimal | None = Query(None, ge=0, description="Maximum price filter"),
    parish: str | None = Query(
        None, description="Exact-match filter on the structured `parish` column."
    ),
    municipality: str | None = Query(
        None, description="Exact-match filter on the structured `municipality` column."
    ),
    district: str | None = Query(
        None, description="Exact-match filter on the structured `district` column."
    ),
    cursor: str | None = Query(
        None,
        description="Opaque token from a prior response's `next_cursor`. Omit for the head page.",
    ),
    limit: int = Query(
        20,
        ge=1,
        le=20,
        description="Results per page (1–20). Cap matches the infinite-scroll tick size.",
    ),
) -> CursorPageResponse:
    container = request.app.state.listing_container

    normalized_q = normalize_query(q)
    validate_location_for_search(
        normalized_q=normalized_q,
        parish=parish,
        municipality=municipality,
        district=district,
    )

    is_search_mode = (
        normalized_q is not None
        and getattr(container, "search_listings", None) is not None
    )
    # Each mode owns location in exactly one place: `filters` for list,
    # `LocationFilter` for search. Building `filters` mode-aware avoids
    # double-counting parish/municipality/district in the fingerprint.
    filters = PropertyFilters(
        listing_type=listing_type,
        typology=typology,
        min_price=min_price,
        max_price=max_price,
        parish=parish if not is_search_mode else None,
        municipality=municipality if not is_search_mode else None,
        district=district if not is_search_mode else None,
        limit=None,
        offset=None,
    )
    location = (
        LocationFilter(parish=parish, municipality=municipality, district=district)
        if is_search_mode
        else None
    )
    fp = filter_fingerprint(
        q=normalized_q if is_search_mode else None,
        filters=filters,
        location=location,
    )

    # Two-step decode: decode_token → kind check → validate_fp. Error
    # precedence is version > invalid > kind > filter so the FE sees a
    # `cursor_kind_mismatch` when search was toggled between requests,
    # not a misleading `cursor_filter_mismatch`.
    decoded_cursor: ListCursor | SearchCursor | None = None
    if cursor is not None:
        try:
            decoded_cursor = decode_token(cursor)
        except CursorVersionError:
            raise HTTPException(status_code=400, detail="cursor_unsupported_version")
        except CursorDecodeError:
            raise HTTPException(status_code=400, detail="cursor_invalid")

        expected_kind = SearchCursor if is_search_mode else ListCursor
        if not isinstance(decoded_cursor, expected_kind):
            raise HTTPException(status_code=400, detail="cursor_kind_mismatch")

        try:
            validate_fp(decoded_cursor, expected_fp=fp)
        except CursorFilterMismatchError:
            raise HTTPException(status_code=400, detail="cursor_filter_mismatch")

    requested_pois: tuple[PoiCategory, ...] = ()
    if not is_search_mode:
        page = await container.list_properties.execute(
            fp=fp,
            filters=filters,
            cursor=decoded_cursor,  # type: ignore[arg-type]
            limit=limit,
        )
    else:
        assert location is not None  # is_search_mode guarantees this
        page, parsed = await container.search_listings.execute(
            fp=fp,
            q=normalized_q,
            location=location,
            filters=filters,
            cursor=decoded_cursor,  # type: ignore[arg-type]
            limit=limit,
        )
        requested_pois = parsed.nearby_pois

    items: list[ListedPropertyResponse] = []
    for prop in page.items:
        image_urls = await _generate_image_urls(request, prop)
        items.append(_to_response_with_pois(prop, image_urls, requested_pois))

    return CursorPageResponse(items=items, next_cursor=page.next_cursor, limit=limit)


def _to_response_with_pois(
    prop: PropertyListing,
    image_urls: dict[str, str],
    requested_pois: tuple[PoiCategory, ...],
) -> ListedPropertyResponse:
    """Extends `_to_response` with matched/unmatched POI buckets when
    `requested_pois` is set (q-set search path). The structured-filter
    (q-empty) path passes `requested_pois=()` and gets the default
    empty lists.

    Spec: ADR-014 §12 / §15.
    """
    base = _to_response(prop, image_urls)
    if not requested_pois:
        # q-empty path — base already has the schema-default empty
        # matched_pois/unmatched_pois.
        return base
    requested = {p.value for p in requested_pois}
    listing_categories = {poi.category for poi in prop.pois}
    matched_pois = [
        POIResponse(
            category=poi.category,
            name=poi.name,
            distance_meters=poi.distance_meters,
            address=poi.address,
            image_urls=list(poi.image_urls),
            reviews=poi.reviews,
        )
        for poi in prop.pois
        if poi.category in requested
    ]
    # Explicit ascending-distance sort. `prop.pois` from the projection
    # is in discovery order (whatever order properties emitted in
    # build_property_snapshot), NOT distance order. The canonical-text
    # composer sorts by distance for the NEARBY: line — that sort
    # doesn't propagate to the JSONB projection.
    matched_pois.sort(key=lambda p: p.distance_meters)
    unmatched_pois = sorted(requested - listing_categories)
    return base.model_copy(
        update={"matched_pois": matched_pois, "unmatched_pois": unmatched_pois}
    )


@router.get(
    "/properties/{property_id}",
    response_model=ListedPropertyResponse,
    summary="Get a single active property by ID",
)
async def get_property(property_id: UUID, request: Request) -> ListedPropertyResponse:
    container = request.app.state.listing_container
    try:
        prop = await container.get_property.execute(property_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    image_urls = await _generate_image_urls(request, prop)
    return _to_response(prop, image_urls)


@router.get(
    "/locations",
    response_model=LocationTreeResponse,
    summary="Hierarchical tree of populated locations (FE selector)",
)
async def list_locations(request: Request) -> LocationTreeResponse:
    """Powers the FE's location selector for the search read path.

    Returns the hierarchical tree of populated locations
    (district → municipality → parish) derived from the
    `property_listings` projection. Regions with zero published
    listings are excluded.

    TTL-cached at the use-case layer — repeated requests inside the
    window don't re-query the DB.
    """
    container = request.app.state.listing_container
    tree = await container.list_locations.execute()
    return LocationTreeResponse(
        countries=[
            CountryNode(
                code=c.code,
                name=c.name,
                districts=[
                    DistrictNode(
                        name=d.name,
                        municipalities=[
                            MunicipalityNode(name=m.name, parishes=m.parishes)
                            for m in d.municipalities
                        ],
                    )
                    for d in c.districts
                ],
            )
            for c in tree.countries
        ]
    )


# ── Admin (auth-gated, org-scoped) ───────────────────────────────────────────


@admin_router.get(
    "/properties",
    response_model=PaginatedListingResponse,
    summary="List active listings for the caller's organization (admin view)",
    responses={
        200: {"description": "Active listings for the organization"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
    },
)
async def list_org_active_listings(
    organization_id: UUID,
    request: Request,
    listing_type: ListingType | None = Query(
        None, description="Filter by listing type (sale/purchase)"
    ),
    typology: Typology | None = Query(
        None, description="Filter by typology (house/apartment/land/ruin)"
    ),
    min_price: Decimal | None = Query(None, ge=0, description="Minimum price filter"),
    max_price: Decimal | None = Query(None, ge=0, description="Maximum price filter"),
    parish: str | None = Query(
        None, description="Exact-match filter on the structured `parish` column."
    ),
    municipality: str | None = Query(
        None, description="Exact-match filter on the structured `municipality` column."
    ),
    district: str | None = Query(
        None, description="Exact-match filter on the structured `district` column."
    ),
    limit: int = Query(20, ge=1, le=100, description="Number of results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    _member: tuple[User, Membership] = Depends(require_org_member),
) -> PaginatedListingResponse:
    container = request.app.state.listing_container
    filters = PropertyFilters(
        listing_type=listing_type,
        typology=typology,
        min_price=min_price,
        max_price=max_price,
        parish=parish,
        municipality=municipality,
        district=district,
        limit=limit,
        offset=offset,
    )
    properties, total = await container.list_org_active_listings.execute(
        organization_id=organization_id,
        filters=filters,
    )

    items = []
    for prop in properties:
        image_urls = await _generate_image_urls(request, prop)
        items.append(_to_response(prop, image_urls))

    return PaginatedListingResponse(items=items, total=total, limit=limit, offset=offset)
