from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from shared.api.dependencies import get_supabase_user_id
from property_management.adapters.api.routes.properties import _property_response
from property_management.adapters.api.schemas import (
    CreatePropertyOwnerRequest,
    PropertyOwnerResponse,
    PropertyResponse,
)
from property_management.domain.exceptions import (
    DocumentExtractionError,
    InvalidNIFError,
    PropertyNotFoundError,
    PropertyOwnerNotFoundError,
)

router = APIRouter(prefix="/property-owners", tags=["property-owners"])


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
        "created_at": owner.created_at,
        "updated_at": owner.updated_at,
    }


async def _verify_property_ownership(
    request: Request, property_id: UUID, supabase_user_id: str
) -> None:
    get_prop_uc = request.app.state.property_container.get_property
    try:
        prop = await get_prop_uc.execute(property_id=property_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    if str(prop.user_id) != supabase_user_id:
        raise HTTPException(status_code=403, detail="Not authorized")


@router.post(
    "/",
    response_model=PropertyResponse,
    status_code=201,
    summary="Create property owner",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
        422: {"description": "Invalid NIF"},
    },
)
async def create_property_owner(
    body: CreatePropertyOwnerRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    await _verify_property_ownership(request, body.property_id, supabase_user_id)

    create_uc = request.app.state.property_container.create_property_owner
    try:
        prop = await create_uc.execute(
            property_id=body.property_id,
            full_name=body.full_name,
            civil_status=body.civil_status,
            address=body.address,
            nif=body.nif,
            document_type=body.document_type,
            document_id=body.document_id,
            issued_by=body.issued_by,
            issuing_district=body.issuing_district,
            date_of_birth=body.date_of_birth,
        )
    except InvalidNIFError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    return _property_response(prop)


@router.post(
    "/extract-from-document",
    response_model=PropertyResponse,
    status_code=201,
    summary="Extract property owner from document",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
        422: {"description": "Extraction failed"},
    },
)
async def extract_from_document(
    request: Request,
    property_id: UUID = Form(...),
    file: UploadFile = File(...),
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    await _verify_property_ownership(request, property_id, supabase_user_id)

    extract_uc = request.app.state.property_container.extract_property_owner_from_document
    try:
        file_bytes = await file.read()
        prop = await extract_uc.execute(
            property_id=property_id,
            file_bytes=file_bytes,
            content_type=file.content_type or "image/jpeg",
        )
    except (DocumentExtractionError, InvalidNIFError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    return _property_response(prop)


@router.get(
    "/",
    response_model=list[PropertyOwnerResponse],
    summary="List property owners",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
    },
)
async def list_property_owners(
    property_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    await _verify_property_ownership(request, property_id, supabase_user_id)

    list_uc = request.app.state.property_container.list_property_owners
    owners = await list_uc.execute(property_id=property_id)
    return [_owner_response(o) for o in owners]


@router.get(
    "/{owner_id}",
    response_model=PropertyOwnerResponse,
    summary="Get property owner",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property owner not found"},
    },
)
async def get_property_owner(
    owner_id: UUID,
    property_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    await _verify_property_ownership(request, property_id, supabase_user_id)

    get_uc = request.app.state.property_container.get_property_owner
    try:
        owner = await get_uc.execute(property_id=property_id, owner_id=owner_id)
    except PropertyOwnerNotFoundError:
        raise HTTPException(status_code=404, detail="Property owner not found")

    return _owner_response(owner)
