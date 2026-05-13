from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from organizations.domain.models.membership import Membership
from identity.domain.models.user import User
from shared.api.dependencies import (
    assert_org_member,
    get_supabase_user_id,
    require_org_member,
)
from properties.adapters.api.schemas import (
    CreatePropertyRequest,
    EnrichPropertyRequest,
    EnrichPropertyResponse,
    PropertyResponse,
    PropertySummaryResponse,
    PublicPropertyResponse,
    UpdatePropertyAddressRequest,
    UpdatePropertyCharacteristicsRequest,
    UpdatePropertyTitleRequest,
)
from shared.jobs.adapters.api.schemas import JobResponse
from shared.jobs.domain.job import JobEntityType, JobKind
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
    PropertyNotPublishableError,
    PropertyNotUnpublishableError,
)

router = APIRouter(prefix="/properties", tags=["properties"])


def _property_response(prop, image_download_urls: dict | None = None) -> dict:
    """Build the response dict.

    `image_download_urls` is kept for back-compat with callers but is no
    longer needed — the public URL is stored on `PropertyImage.url` at
    upload time and served as-is. When the parameter is provided, its
    values override the stored URL (legacy paths / test seams). When not
    provided (the new default), `_image_response` reads `image.url`.
    """
    characteristics = None
    if prop.characteristics:
        characteristics = prop.characteristics.to_dict()
    images = []
    if prop.images:
        images = [
            _image_response(
                i,
                (image_download_urls or {}).get(str(i.id)) or (i.url or ""),
            )
            for i in prop.images
        ]
    return {
        "id": prop.id,
        "organization_id": prop.organization_id,
        "title": prop.title,
        "address": prop.address,
        "listing_type": prop.listing_type,
        "typology": prop.typology,
        "status": prop.status,
        "description": prop.description,
        "characteristics": characteristics,
        "latitude": prop.latitude,
        "longitude": prop.longitude,
        "created_at": prop.created_at,
        "updated_at": prop.updated_at,
        "owners": [_owner_response(o) for o in prop.owners],
        "prices": [_price_response(p) for p in prop.prices],
        "images": images,
    }


def _price_response(price) -> dict:
    return {
        "id": price.id,
        "property_id": price.property_id,
        "amount": price.amount,
        "listing_type": price.listing_type,
        "created_at": price.created_at,
        "updated_at": price.updated_at,
    }


def _image_response(image, download_url: str) -> dict:
    return {
        "id": image.id,
        "property_id": image.property_id,
        "s3_key": image.s3_key,
        "filename": image.filename,
        "content_type": image.content_type,
        "size_bytes": image.size_bytes,
        "display_order": image.display_order,
        "download_url": download_url,
        "created_at": image.created_at,
        "updated_at": image.updated_at,
    }


# `_generate_image_download_urls` was removed: image URLs are stored on
# `PropertyImage.url` at upload time and served directly from the projection.
# Routes pass no override dict; `_property_response` falls through to `image.url`.


def _owner_response(owner) -> dict:
    return {
        "id": owner.id,
        "property_id": owner.property_id,
        "full_name": owner.full_name,
        "civil_status": owner.civil_status,
        "address": owner.address,
        "nif": owner.nif,
        "document_type": owner.document_type,
        "document_id": owner.document_id,
        "issued_by": owner.issued_by,
        "issuing_district": owner.issuing_district,
        "date_of_birth": owner.date_of_birth,
        "email": owner.email,
        "phone_number": owner.phone_number,
        "email_verified": owner.email_verified,
        "phone_verified": owner.phone_verified,
        "created_at": owner.created_at,
        "updated_at": owner.updated_at,
    }


@router.get(
    "/active",
    response_model=list[PublicPropertyResponse],
    summary="List active properties (public)",
)
async def list_active_properties(request: Request):
    uc = request.app.state.property_container.list_active_properties
    props = await uc.execute()
    return [_property_response(p) for p in props]


@router.post(
    "/",
    response_model=PropertyResponse,
    status_code=201,
    summary="Create property",
    responses={401: {"description": "Not authenticated"}},
)
async def create_property(
    body: CreatePropertyRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    await assert_org_member(request, supabase_user_id, body.organization_id)
    create_uc = request.app.state.property_container.create_property
    prop = await create_uc.execute(
        organization_id=str(body.organization_id),
        title=body.title,
        address=body.address,
        listing_type=body.listing_type,
        typology=body.typology,
        description=body.description,
    )
    return _property_response(prop)


@router.get(
    "/",
    response_model=list[PropertyResponse],
    summary="List properties",
    responses={401: {"description": "Not authenticated"}},
)
async def list_properties(
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    list_uc = request.app.state.property_container.list_properties
    props = await list_uc.execute(organization_id=str(organization_id))
    return [_property_response(p) for p in props]


@router.get(
    "/summary",
    response_model=list[PropertySummaryResponse],
    summary="List properties summary",
    responses={401: {"description": "Not authenticated"}},
)
async def list_properties_summary(
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    list_uc = request.app.state.property_container.list_properties
    props = await list_uc.execute(organization_id=str(organization_id))
    return [
        {
            "id": p.id,
            "address": p.address,
            "listing_type": p.listing_type,
            "typology": p.typology,
            "price": max(p.prices, key=lambda pr: pr.created_at).amount if p.prices else None,
            "owners": [{"full_name": o.full_name} for o in p.owners],
        }
        for p in props
    ]


@router.get(
    "/{property_id}",
    response_model=PropertyResponse,
    summary="Get property",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
    },
)
async def get_property(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    get_uc = request.app.state.property_container.get_property
    try:
        prop = await get_uc.execute(property_id=property_id, organization_id=organization_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    return _property_response(prop)


@router.delete(
    "/{property_id}",
    status_code=204,
    summary="Delete a property (hard delete)",
    description=(
        "Permanently delete a property and all related data: owners, prices, images "
        "(including S3 objects), amenities, and extraction jobs. Only the organization's "
        "OWNER or ADMIN can perform this action."
    ),
    responses={
        204: {"description": "Property deleted"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized — must be OWNER or ADMIN of the organization"},
        404: {"description": "Property not found"},
    },
)
async def delete_property(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    member: tuple[User, Membership] = Depends(require_org_member),
):
    _user, membership = member
    role_value = membership.role.value if hasattr(membership.role, "value") else membership.role
    if role_value not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only OWNER or ADMIN can delete properties")

    delete_uc = request.app.state.property_container.delete_property
    try:
        await delete_uc.execute(property_id=property_id, organization_id=organization_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    return None


@router.patch(
    "/{property_id}/title",
    response_model=PropertyResponse,
    summary="Update property title",
    description=(
        "Replace a property's `title`. Strips surrounding whitespace; "
        "empty / whitespace-only inputs are rejected at the schema layer (422). "
        "On no-op (new value equal to current after normalization) returns the "
        "existing aggregate without bumping `aggregate_version` or emitting an event."
    ),
    responses={
        200: {"description": "Title updated (or unchanged on no-op)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
        422: {"description": "Title failed schema validation (empty/whitespace-only)"},
    },
)
async def update_property_title(
    property_id: UUID,
    body: UpdatePropertyTitleRequest,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    update_uc = request.app.state.property_container.update_property_title
    try:
        prop = await update_uc.execute(
            property_id=property_id,
            organization_id=organization_id,
            title=body.title,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    return _property_response(prop)


@router.patch(
    "/{property_id}/characteristics",
    response_model=PropertyResponse,
    summary="Update property characteristics (partial)",
    description=(
        "Partial update of `characteristics`. Only fields explicitly present "
        "in the request body are applied; pass `null` to clear a field. "
        "On no-op (merged result equal to current) returns the existing "
        "aggregate without bumping `aggregate_version` or emitting an event."
    ),
    responses={
        200: {"description": "Characteristics updated (or unchanged on no-op)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
        422: {"description": "Domain validation failed (e.g. non-positive area)"},
    },
)
async def update_property_characteristics(
    property_id: UUID,
    body: UpdatePropertyCharacteristicsRequest,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    update_uc = request.app.state.property_container.update_property_characteristics
    sent = body.model_fields_set
    kwargs = {name: getattr(body, name) for name in sent}
    try:
        prop = await update_uc.execute(
            property_id=property_id,
            organization_id=organization_id,
            **kwargs,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _property_response(prop)


@router.patch(
    "/{property_id}/address",
    response_model=PropertyResponse,
    summary="Update property address",
    description=(
        "Replace a property's `address`. Strips surrounding whitespace; "
        "empty / whitespace-only inputs are rejected at the schema layer (422). "
        "On no-op (new value equal to current after normalization) returns the "
        "existing aggregate without bumping `aggregate_version` or emitting an event."
    ),
    responses={
        200: {"description": "Address updated (or unchanged on no-op)"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
        422: {"description": "Address failed schema validation (empty/whitespace-only)"},
    },
)
async def update_property_address(
    property_id: UUID,
    body: UpdatePropertyAddressRequest,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    update_uc = request.app.state.property_container.update_property_address
    try:
        prop = await update_uc.execute(
            property_id=property_id,
            organization_id=organization_id,
            address=body.address,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    return _property_response(prop)


@router.post(
    "/{property_id}/enhance-description",
    response_model=PropertyResponse,
    summary="Rewrite the property's description via LLM",
    description=(
        "Sends the property's current description plus its structured facts "
        "(title, address, listing type, typology, characteristics) to a "
        "LangChain + GPT-4o-mini adapter that returns polished marketing copy. "
        "The new value is persisted, `aggregate_version` is bumped, and "
        "`PROPERTY_UPDATED.v1` is emitted so the listings projector re-indexes."
    ),
    responses={
        200: {"description": "Description enhanced"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
        503: {"description": "LLM adapter not configured (missing OPENAI_API_KEY)"},
    },
)
async def enhance_property_description(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    use_case = request.app.state.property_container.enhance_property_description
    if use_case is None:
        raise HTTPException(
            status_code=503,
            detail="Description enhancer is not configured on this deployment.",
        )
    try:
        prop = await use_case.execute(
            property_id=property_id,
            organization_id=organization_id,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    return _property_response(prop)


@router.post(
    "/{property_id}/publish",
    response_model=PropertyResponse,
    summary="Publish a property to the public portal",
    description=(
        "Flip a property from DRAFT or WITHDRAWN to ACTIVE and broadcast "
        "PROPERTY_PUBLISHED.v1 so the listings context picks it up. "
        "Only the organization's OWNER or ADMIN can perform this action."
    ),
    responses={
        200: {"description": "Property published"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized — must be OWNER or ADMIN of the organization"},
        404: {"description": "Property not found"},
        422: {"description": "Property is not publishable (missing fields or wrong status)"},
    },
)
async def publish_property(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    member: tuple[User, Membership] = Depends(require_org_member),
):
    _user, membership = member
    role_value = membership.role.value if hasattr(membership.role, "value") else membership.role
    if role_value not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only OWNER or ADMIN can publish properties")

    publish_uc = request.app.state.property_container.publish_property
    try:
        prop = await publish_uc.execute(
            property_id=property_id,
            organization_id=organization_id,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except PropertyNotPublishableError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Property is not publishable", "reasons": exc.reasons},
        )

    return _property_response(prop)


@router.post(
    "/{property_id}/unpublish",
    response_model=PropertyResponse,
    summary="Unpublish a property — take it off the public listings",
    description=(
        "Flip a property from ACTIVE back to DRAFT and broadcast "
        "PROPERTY_UNPUBLISHED.v1. The listings context deletes the "
        "property_listings row on receipt — the property disappears "
        "from the public site but stays in the agent's dashboard as "
        "a draft. Symmetric to /publish; only the organization's "
        "OWNER or ADMIN can perform this action."
    ),
    responses={
        200: {"description": "Property unpublished"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized — must be OWNER or ADMIN of the organization"},
        404: {"description": "Property not found"},
        422: {"description": "Property is not unpublishable (not currently ACTIVE)"},
    },
)
async def unpublish_property(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    member: tuple[User, Membership] = Depends(require_org_member),
):
    _user, membership = member
    role_value = membership.role.value if hasattr(membership.role, "value") else membership.role
    if role_value not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="Only OWNER or ADMIN can unpublish properties")

    unpublish_uc = request.app.state.property_container.unpublish_property
    try:
        prop = await unpublish_uc.execute(
            property_id=property_id,
            organization_id=organization_id,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except PropertyNotUnpublishableError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Property is not unpublishable", "reasons": exc.reasons},
        )

    return _property_response(prop)


@router.post(
    "/{property_id}/enrich",
    response_model=EnrichPropertyResponse,
    status_code=202,
    summary="Trigger POI auto-discovery for a property",
    description=(
        "Enqueues an `ENRICH_PROPERTY_REQUESTED.v1` command and registers a "
        "unified background-job row (ADR-012). Returns the `job_id` so the "
        "frontend can poll `GET /admin/jobs/{id}` for status. The worker "
        "discovers nearby POIs via the configured `PlacesService`, ranks "
        "them, and replaces the property's POI catalog. Manually-edited "
        "categories are preserved unless `force=true` is sent."
    ),
    responses={
        202: {"description": "Enrichment command queued; job_id returned"},
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
        404: {"description": "Property not found"},
        422: {"description": "Property is missing coordinates"},
    },
)
async def enrich_property(
    property_id: UUID,
    organization_id: UUID,
    body: EnrichPropertyRequest,
    request: Request,
    member: tuple[User, Membership] = Depends(require_org_member),
):
    user, _membership = member
    use_case = request.app.state.property_container.enqueue_enrich_property
    try:
        tracked_job_id = await use_case.execute(
            property_id=property_id,
            organization_id=organization_id,
            force=body.force,
            requested_by_user_id=user.id,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except PropertyMissingCoordinatesError:
        raise HTTPException(status_code=422, detail="Property missing coordinates")
    return {
        "job_id": tracked_job_id,
        "status": "processing",
        "property_id": property_id,
    }


@router.get(
    "/{property_id}/jobs",
    response_model=list[JobResponse],
    summary="List background jobs for a property",
    description=(
        "Returns the most recent background-job rows scoped to this property "
        "(`entity_type=PROPERTY, entity_id=property_id`). Filter by `kind` "
        "to scope to a specific workflow (e.g. `property_enrichment`). "
        "Backed by the shared `jobs` infra (ADR-012)."
    ),
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not a member of this organization"},
    },
)
async def list_property_jobs(
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    kind: JobKind | None = None,
    limit: int = 10,
    _member: tuple[User, Membership] = Depends(require_org_member),
):
    if not (1 <= limit <= 50):
        raise HTTPException(status_code=422, detail="limit must be between 1 and 50")
    use_case = request.app.state.jobs_container.list_jobs
    jobs = await use_case.execute(
        organization_id=organization_id,
        kind=kind,
        entity_type=JobEntityType.PROPERTY,
        entity_id=property_id,
        limit=limit,
    )
    return [
        {
            "id": j.id,
            "organization_id": j.organization_id,
            "requested_by_user_id": j.requested_by_user_id,
            "kind": j.kind,
            "status": j.status,
            "entity_type": j.entity_type,
            "entity_id": j.entity_id,
            "title": j.title,
            "error_code": j.error_code,
            "error_message": j.error_message,
            "result_summary": j.result_summary,
            "started_at": j.started_at,
            "completed_at": j.completed_at,
            "created_at": j.created_at,
            "updated_at": j.updated_at,
        }
        for j in jobs
    ]
