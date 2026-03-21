from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from shared.api.dependencies import get_supabase_user_id
from property_management.adapters.api.routes.properties import (
    _generate_image_download_urls,
    _property_response,
)
from property_management.adapters.api.schemas import (
    PresignImageRequest,
    PresignImageResponse,
    PropertyResponse,
    RecordPropertyImageRequest,
    ReorderPropertyImagesRequest,
)
from property_management.domain.exceptions import (
    PropertyImageNotFoundError,
    PropertyNotFoundError,
)

router = APIRouter(prefix="/property-images", tags=["property-images"])


async def _verify_property_ownership(
    request: Request, property_id: UUID, organization_id: UUID
) -> None:
    get_prop_uc = request.app.state.property_container.get_property
    try:
        prop = await get_prop_uc.execute(property_id=property_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    if str(prop.organization_id) != str(organization_id):
        raise HTTPException(status_code=403, detail="Not authorized")


@router.post(
    "/presign",
    response_model=PresignImageResponse,
    summary="Generate presigned upload URLs for property images",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
    },
)
async def presign_image_uploads(
    body: PresignImageRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    await _verify_property_ownership(request, body.property_id, body.organization_id)

    generate_uc = request.app.state.property_container.generate_image_upload_urls
    try:
        presigned = await generate_uc.execute(
            property_id=body.property_id,
            files=[f.model_dump() for f in body.files],
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")

    return {
        "files": [
            {
                "image_id": p.image_id,
                "s3_key": p.s3_key,
                "upload_url": p.upload_url,
            }
            for p in presigned
        ]
    }


@router.post(
    "/",
    response_model=PropertyResponse,
    status_code=201,
    summary="Record property image metadata after upload",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property not found"},
        400: {"description": "Max images reached or file not found"},
    },
)
async def record_property_image(
    body: RecordPropertyImageRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    await _verify_property_ownership(request, body.property_id, body.organization_id)

    record_uc = request.app.state.property_container.record_property_image
    try:
        prop = await record_uc.execute(
            property_id=body.property_id,
            image_id=body.image_id,
            s3_key=body.s3_key,
            filename=body.filename,
            content_type=body.content_type,
            size_bytes=body.size_bytes,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e))

    urls = await _generate_image_download_urls(request, prop)
    return _property_response(prop, urls)


@router.delete(
    "/{image_id}",
    response_model=PropertyResponse,
    summary="Delete a property image",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Property or image not found"},
    },
)
async def delete_property_image(
    image_id: UUID,
    property_id: UUID,
    organization_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    await _verify_property_ownership(request, property_id, organization_id)

    delete_uc = request.app.state.property_container.delete_property_image
    try:
        prop = await delete_uc.execute(property_id=property_id, image_id=image_id)
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except PropertyImageNotFoundError:
        raise HTTPException(status_code=404, detail="Property image not found")

    urls = await _generate_image_download_urls(request, prop)
    return _property_response(prop, urls)


@router.put(
    "/reorder",
    response_model=PropertyResponse,
    summary="Reorder property images",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        400: {"description": "Invalid image IDs"},
        404: {"description": "Property not found"},
    },
)
async def reorder_property_images(
    body: ReorderPropertyImagesRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    await _verify_property_ownership(request, body.property_id, body.organization_id)

    reorder_uc = request.app.state.property_container.reorder_property_images
    try:
        prop = await reorder_uc.execute(
            property_id=body.property_id,
            image_ids=body.image_ids,
        )
    except PropertyNotFoundError:
        raise HTTPException(status_code=404, detail="Property not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    urls = await _generate_image_download_urls(request, prop)
    return _property_response(prop, urls)
