from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from applicant_screening.application.dtos import ScreeningReportResponse

logger = structlog.get_logger()

router = APIRouter(tags=["applicants"])


class ApplicantDetailResponse(BaseModel):
    id: UUID
    name: str
    email: str
    phone: str | None = None
    organization_id: UUID
    form_request_id: UUID
    listing_type: str
    property_type: str | None = None
    property_value: float | None
    monthly_rent: float | None
    property_title: str
    property_address: str
    status: str | None = None
    screening_report: ScreeningReportResponse | None = None


@router.get(
    "/applicants",
    response_model=list[ApplicantDetailResponse],
    summary="List applicants by organization",
)
async def list_applicants(
    request: Request,
    organization_id: UUID = Query(...),
) -> list[ApplicantDetailResponse]:
    container = request.app.state.applicant_screening_container

    applicants = await container.applicant_repo.list_by_organization_id(organization_id)

    responses = []
    for applicant in applicants:
        report = await container.screening_report_repo.get_by_applicant_id(applicant.id)
        report_response = None
        if report:
            report_response = ScreeningReportResponse(
                applicant_id=report.applicant_id,
                risk_level=report.risk_level,
                identity_verified=report.identity_verified,
                income_verified=report.income_verified,
                dti_ratio=report.dti_ratio,
                justification=report.justification,
                listing_type=report.listing_type,
                property_type=report.property_type,
                average_monthly_income=report.average_monthly_income,
            )

        submission = await container.submission_repo.get_by_applicant_id(applicant.id)

        responses.append(
            ApplicantDetailResponse(
                id=applicant.id,
                name=applicant.name,
                email=applicant.email,
                phone=applicant.phone,
                organization_id=applicant.organization_id,
                form_request_id=applicant.form_request_id,
                listing_type=applicant.listing_type.value,
                property_type=applicant.property_type.value if applicant.property_type else None,
                property_value=applicant.property_value,
                monthly_rent=applicant.monthly_rent,
                property_title=applicant.property_title,
                property_address=applicant.property_address,
                status=submission.status if submission else None,
                screening_report=report_response,
            )
        )
    return responses


@router.get(
    "/applicants/{applicant_id}",
    response_model=ApplicantDetailResponse,
    summary="Get applicant details with screening report",
)
async def get_applicant(applicant_id: UUID, request: Request) -> ApplicantDetailResponse:
    container = request.app.state.applicant_screening_container
    applicant = await container.applicant_repo.get_by_id(applicant_id)
    if not applicant:
        raise HTTPException(status_code=404, detail="Applicant not found")

    report = await container.screening_report_repo.get_by_applicant_id(applicant_id)
    report_response = None
    if report:
        report_response = ScreeningReportResponse(
            applicant_id=report.applicant_id,
            risk_level=report.risk_level,
            identity_verified=report.identity_verified,
            income_verified=report.income_verified,
            dti_ratio=report.dti_ratio,
            justification=report.justification,
            listing_type=report.listing_type,
            property_type=report.property_type,
            average_monthly_income=report.average_monthly_income,
        )

    submission = await container.submission_repo.get_by_applicant_id(applicant_id)

    return ApplicantDetailResponse(
        id=applicant.id,
        name=applicant.name,
        email=applicant.email,
        phone=applicant.phone,
        organization_id=applicant.organization_id,
        form_request_id=applicant.form_request_id,
        listing_type=applicant.listing_type.value,
        property_type=applicant.property_type.value if applicant.property_type else None,
        property_value=applicant.property_value,
        monthly_rent=applicant.monthly_rent,
        property_title=applicant.property_title,
        property_address=applicant.property_address,
        status=submission.status if submission else None,
        screening_report=report_response,
    )
