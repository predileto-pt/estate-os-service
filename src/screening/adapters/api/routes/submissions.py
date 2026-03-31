from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from screening.application.dtos import (
    CreateApplicantRequest,
    CreateSubmissionRequest,
    PresignedFileUpload,
    PresignedUploadRequest,
    PresignedUploadResponse,
    ScreeningReportResponse,
    ScreeningStatusResponse,
    SubmissionResponse,
)
from screening.domain.exceptions import DocumentLimitExceededError, DuplicateApplicantError

logger = structlog.get_logger()

router = APIRouter(tags=["applicant-submissions"])


@router.post(
    "/submissions/uploads/presign",
    response_model=PresignedUploadResponse,
    summary="Get presigned S3 URLs for document uploads",
)
async def presign_uploads(
    body: PresignedUploadRequest, request: Request
) -> PresignedUploadResponse:
    container = request.app.state.screening_container

    async with container.uow:
        form_request = await container.uow.intake_form_requests.get_by_id(body.form_request_id)
    if not form_request:
        raise HTTPException(status_code=404, detail="Intake form request not found")

    if len(body.files) > container.max_documents:
        raise HTTPException(
            status_code=400, detail=f"Too many files. Maximum is {container.max_documents}"
        )

    upload_id = str(uuid4())
    presigned_files: list[PresignedFileUpload] = []

    for file_spec in body.files:
        s3_key = f"uploads/{body.form_request_id}/{upload_id}/{file_spec.filename}"
        upload_url = await container.document_storage.get_upload_url(s3_key, file_spec.content_type)
        presigned_files.append(
            PresignedFileUpload(
                filename=file_spec.filename,
                s3_key=s3_key,
                upload_url=upload_url,
                document_type=file_spec.document_type,
            )
        )

    return PresignedUploadResponse(upload_id=upload_id, files=presigned_files)


@router.post(
    "/submissions",
    response_model=SubmissionResponse,
    summary="Submit applicant documents for screening",
)
async def create_submission(body: CreateSubmissionRequest, request: Request) -> SubmissionResponse:
    try:
        applicant_request = CreateApplicantRequest(
            nif=body.nif,
            name=body.name,
            date_of_birth=body.date_of_birth,
            email=body.email,
            organization_id=body.organization_id,
            form_request_id=body.form_request_id,
            listing_type=body.listing_type,
            property_type=body.property_type,
            phone=body.phone,
            property_value=body.property_value,
            monthly_rent=body.monthly_rent,
            property_title=body.property_title,
            property_address=body.property_address,
        )
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    container = request.app.state.screening_container

    # Validate S3 keys belong to this form request
    expected_prefix = f"uploads/{body.form_request_id}/"
    for doc in body.documents:
        if not doc.s3_key.startswith(expected_prefix):
            raise HTTPException(status_code=400, detail=f"Invalid S3 key: {doc.s3_key}")
        if not await container.document_storage.verify_exists(doc.s3_key):
            raise HTTPException(status_code=400, detail=f"File not found in S3: {doc.s3_key}")

    documents = [
        {
            "s3_key": doc.s3_key,
            "filename": doc.filename,
            "content_type": doc.content_type,
            "document_type": doc.document_type,
        }
        for doc in body.documents
    ]

    try:
        applicant_id, submission_id, doc_count = await container.submission_service.submit(
            nif=applicant_request.nif,
            name=applicant_request.name,
            date_of_birth=str(applicant_request.date_of_birth),
            email=applicant_request.email,
            organization_id=applicant_request.organization_id,
            form_request_id=applicant_request.form_request_id,
            listing_type=applicant_request.listing_type,
            property_type=applicant_request.property_type,
            terms_accepted=body.terms_accepted,
            documents=documents,
            phone=applicant_request.phone,
            property_value=applicant_request.property_value,
            monthly_rent=applicant_request.monthly_rent,
            property_title=applicant_request.property_title,
            property_address=applicant_request.property_address,
        )
    except DuplicateApplicantError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except DocumentLimitExceededError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return SubmissionResponse(
        applicant_id=applicant_id,
        documents_uploaded=doc_count,
        message="Submission received. Documents will be processed.",
    )


@router.get(
    "/submissions/{applicant_id}/status",
    response_model=ScreeningStatusResponse,
    summary="Get screening status for a submission",
)
async def get_screening_status(applicant_id: UUID, request: Request) -> ScreeningStatusResponse:
    container = request.app.state.screening_container

    async with container.uow:
        applicant = await container.uow.applicants.get_by_id(applicant_id)
        if not applicant:
            raise HTTPException(status_code=404, detail="Applicant not found")

        report = await container.uow.screening_reports.get_by_applicant_id(applicant_id)

    if report:
        return ScreeningStatusResponse(
            applicant_id=applicant_id,
            status="COMPLETED",
            report=ScreeningReportResponse(
                applicant_id=report.applicant_id,
                risk_level=report.risk_level,
                identity_verified=report.identity_verified,
                income_verified=report.income_verified,
                dti_ratio=report.dti_ratio,
                justification=report.justification,
                listing_type=report.listing_type,
                property_type=report.property_type,
                average_monthly_income=report.average_monthly_income,
            ),
        )

    return ScreeningStatusResponse(applicant_id=applicant_id, status="PROCESSING")
