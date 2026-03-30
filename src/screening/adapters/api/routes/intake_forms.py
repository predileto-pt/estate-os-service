from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from screening.domain.models import ListingType, PropertyType
from screening.domain.models.intake_form_request import IntakeFormRequest
from screening.domain.models.submission import Submission

logger = structlog.get_logger()

router = APIRouter(tags=["intake-form-requests"])


class CreateIntakeFormRequestBody(BaseModel):
    organization_id: UUID
    applicant_name: str
    applicant_email: str
    property_id: str
    listing_type: ListingType
    property_type: PropertyType | None = None
    applicant_phone: str | None = None
    property_title: str | None = None
    property_price: float | None = None
    property_address: str | None = None


class SubmissionSummaryResponse(BaseModel):
    id: UUID
    status: str
    created_at: datetime


class IntakeFormRequestResponse(BaseModel):
    id: UUID
    organization_id: UUID
    applicant_name: str
    applicant_email: str
    applicant_phone: str | None
    property_id: str
    listing_type: str
    property_type: str | None = None
    property_title: str | None
    property_price: float | None
    property_address: str | None
    status: str
    created_at: datetime
    updated_at: datetime
    submission: SubmissionSummaryResponse | None = None


def _form_request_to_response(
    fr: IntakeFormRequest, submission: Submission | None = None
) -> IntakeFormRequestResponse:
    submission_response = None
    if submission:
        submission_response = SubmissionSummaryResponse(
            id=submission.id,
            status=submission.status.value,
            created_at=submission.created_at,
        )
    return IntakeFormRequestResponse(
        id=fr.id,
        organization_id=fr.organization_id,
        applicant_name=fr.applicant_name,
        applicant_email=fr.applicant_email,
        applicant_phone=fr.applicant_phone,
        property_id=fr.property_id,
        listing_type=fr.listing_type.value,
        property_type=fr.property_type.value if fr.property_type else None,
        property_title=fr.property_title,
        property_price=fr.property_price,
        property_address=fr.property_address,
        status=fr.status.value,
        created_at=fr.created_at,
        updated_at=fr.updated_at,
        submission=submission_response,
    )


@router.post(
    "/intake-form-requests",
    response_model=IntakeFormRequestResponse,
    summary="Create an intake form request",
)
async def create_intake_form_request(
    body: CreateIntakeFormRequestBody, request: Request
) -> IntakeFormRequestResponse:
    container = request.app.state.screening_container
    form_request = IntakeFormRequest(
        organization_id=body.organization_id,
        applicant_name=body.applicant_name,
        applicant_email=body.applicant_email,
        property_id=body.property_id,
        listing_type=body.listing_type,
        property_type=body.property_type,
        applicant_phone=body.applicant_phone,
        property_title=body.property_title,
        property_price=body.property_price,
        property_address=body.property_address,
    )
    form_request = await container.intake_form_request_repo.save(form_request)
    return _form_request_to_response(form_request, submission=None)


@router.get(
    "/intake-form-requests",
    response_model=list[IntakeFormRequestResponse],
    summary="List intake form requests for an agency",
)
async def list_intake_form_requests(
    request: Request,
    organization_id: UUID = Query(...),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[IntakeFormRequestResponse]:
    container = request.app.state.screening_container
    requests_list = await container.intake_form_request_repo.list_by_organization_id(
        organization_id, limit=limit, offset=offset
    )
    responses = []
    for r in requests_list:
        submission = await container.submission_repo.get_by_form_request_id(r.id)
        responses.append(_form_request_to_response(r, submission=submission))
    return responses


@router.get(
    "/intake-form-requests/{request_id}",
    response_model=IntakeFormRequestResponse,
    summary="Get an intake form request by ID",
)
async def get_intake_form_request(request_id: UUID, request: Request) -> IntakeFormRequestResponse:
    container = request.app.state.screening_container
    form_request = await container.intake_form_request_repo.get_by_id(request_id)
    if not form_request:
        raise HTTPException(status_code=404, detail="Intake form request not found")
    submission = await container.submission_repo.get_by_form_request_id(form_request.id)
    return _form_request_to_response(form_request, submission=submission)
