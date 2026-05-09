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
    PropertyResponse,
    PropertySummaryResponse,
    PublicPropertyResponse,
    UpdatePropertyAddressRequest,
)
from properties.domain.exceptions import (
    PropertyMissingCoordinatesError,
    PropertyNotFoundError,
    PropertyNotPublishableError,
)

router = APIRouter(prefix="/properties", tags=["properties"])


def _property_response(prop, image_download_urls: dict | None = None) -> dict:
    characteristics = None
    if prop.characteristics:
        characteristics = prop.characteristics.to_dict()
    images = []
    if prop.images and image_download_urls:
        images = [_image_response(i, image_download_urls.get(str(i.id), "")) for i in prop.images]
    return {
        "id": prop.id,
        "organization_id": prop.organization_id,
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


async def _generate_image_download_urls(request, prop) -> dict:
    """Generate presigned download URLs for all images on a property."""
    document_storage = getattr(request.app.state.property_container, "document_storage", None)
    if not document_storage or not prop.images:
        return {}
    urls = {}
    for image in prop.images:
        urls[str(image.id)] = await document_storage.get_download_url(image.s3_key)
    return urls


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
    results = []
    for p in props:
        urls = await _generate_image_download_urls(request, p)
        results.append(_property_response(p, urls))
    return results


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
    results = []
    for p in props:
        urls = await _generate_image_download_urls(request, p)
        results.append(_property_response(p, urls))
    return results


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

    urls = await _generate_image_download_urls(request, prop)
    return _property_response(prop, urls)


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

    urls = await _generate_image_download_urls(request, prop)
    return _property_response(prop, urls)


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

    urls = await _generate_image_download_urls(request, prop)
    return _property_response(prop, urls)


@router.post(
    "/{property_id}/enrich",
    status_code=202,
    summary="Trigger POI auto-discovery for a property",
    description=(
        "Enqueues an `ENRICH_PROPERTY_REQUESTED.v1` command. The worker "
        "discovers nearby POIs via the configured `PlacesService`, ranks "
        "them, and replaces the property's POI catalog. Manually-edited "
        "categories are preserved unless `force=true` is sent."
    ),
    responses={
        202: {"description": "Enrichment command queued"},
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
        await use_case.execute(
            property_id=property_id,
            organization_id=organization_id,
            force=body.force,
            requested_by_user_id=user.id,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except PropertyMissingCoordinatesError:
        raise HTTPException(status_code=422, detail="Property missing coordinates")
    return {"status": "enrichment_queued", "property_id": str(property_id)}
