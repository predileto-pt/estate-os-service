from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from shared.api.dependencies import get_supabase_user_id
from property_management.adapters.api.schemas import (
    ExtractionJobResponse,
    PresignedFileResponse,
    PresignRequest,
    PresignResponse,
    SubmitExtractionRequest,
)
from property_management.domain.exceptions import (
    ExtractionJobNotFoundError,
    TooManyDocumentsError,
)

router = APIRouter(prefix="/extraction-jobs", tags=["extraction-jobs"])


def _job_response(job) -> dict:
    return {
        "id": job.id,
        "user_id": job.user_id,
        "organization_id": job.organization_id,
        "status": job.status,
        "document_keys": job.document_keys,
        "listing_type": job.listing_type,
        "typology": job.typology,
        "property_id": job.property_id,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.post(
    "/presign",
    response_model=PresignResponse,
    summary="Get presigned S3 URLs for document upload",
    responses={
        401: {"description": "Not authenticated"},
        422: {"description": "Too many documents"},
    },
)
async def generate_upload_urls(
    body: PresignRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    uc = request.app.state.property_container.generate_upload_urls
    try:
        job_id, presigned_files = await uc.execute(
            files=[f.model_dump() for f in body.files],
        )
    except TooManyDocumentsError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "job_id": job_id,
        "files": [
            PresignedFileResponse(s3_key=f.s3_key, upload_url=f.upload_url) for f in presigned_files
        ],
    }


@router.post(
    "/",
    response_model=ExtractionJobResponse,
    status_code=202,
    summary="Submit extraction job after uploading documents to S3",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Document not found in S3"},
        422: {"description": "Invalid S3 key"},
    },
)
async def submit_extraction(
    body: SubmitExtractionRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    uc = request.app.state.property_container.submit_property_extraction
    try:
        job = await uc.execute(
            job_id=body.job_id,
            user_id=supabase_user_id,
            organization_id=str(body.organization_id),
            document_keys=body.document_keys,
            listing_type=body.listing_type.value,
            typology=body.typology.value,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _job_response(job)


@router.post(
    "/batch",
    response_model=ExtractionJobResponse,
    status_code=202,
    summary="Submit batch extraction job (property docs + ID docs)",
    responses={
        401: {"description": "Not authenticated"},
        404: {"description": "Document not found in S3"},
        422: {"description": "Invalid S3 key"},
    },
)
async def submit_batch_extraction(
    body: SubmitExtractionRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    uc = request.app.state.property_container.submit_batch_property_extraction
    try:
        job = await uc.execute(
            job_id=body.job_id,
            user_id=supabase_user_id,
            organization_id=str(body.organization_id),
            document_keys=body.document_keys,
            listing_type=body.listing_type.value,
            typology=body.typology.value,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _job_response(job)


@router.post(
    "/{job_id}/retry",
    response_model=ExtractionJobResponse,
    summary="Retry a failed extraction job",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Job not found"},
        422: {"description": "Job is not in failed status"},
    },
)
async def retry_extraction_job(
    job_id: UUID,
    organization_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    get_uc = request.app.state.property_container.get_extraction_job
    try:
        job = await get_uc.execute(job_id=job_id)
    except ExtractionJobNotFoundError:
        raise HTTPException(status_code=404, detail="Extraction job not found")

    if str(job.organization_id) != str(organization_id):
        raise HTTPException(status_code=403, detail="Not authorized")

    retry_uc = request.app.state.property_container.retry_extraction_job
    try:
        job = await retry_uc.execute(job_id=job_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return _job_response(job)


@router.get(
    "/",
    response_model=list[ExtractionJobResponse],
    summary="List extraction jobs",
    responses={401: {"description": "Not authenticated"}},
)
async def list_extraction_jobs(
    organization_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    uc = request.app.state.property_container.list_extraction_jobs
    jobs = await uc.execute(organization_id=str(organization_id))
    return [_job_response(j) for j in jobs]


@router.get(
    "/{job_id}",
    response_model=ExtractionJobResponse,
    summary="Get extraction job status",
    responses={
        401: {"description": "Not authenticated"},
        403: {"description": "Not authorized"},
        404: {"description": "Job not found"},
    },
)
async def get_extraction_job(
    job_id: UUID,
    organization_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
):
    uc = request.app.state.property_container.get_extraction_job
    try:
        job = await uc.execute(job_id=job_id)
    except ExtractionJobNotFoundError:
        raise HTTPException(status_code=404, detail="Extraction job not found")

    if str(job.organization_id) != str(organization_id):
        raise HTTPException(status_code=403, detail="Not authorized")

    return _job_response(job)
