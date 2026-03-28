from uuid import UUID

from applicant_screening.domain.models import (
    ApplicantScreened,
    ApplicantSubmitted,
    DocumentsExtracted,
)


def applicant_submitted(applicant_id: UUID, *, document_count: int = 0) -> ApplicantSubmitted:
    return ApplicantSubmitted(applicant_id=applicant_id, document_count=document_count)


def documents_extracted(applicant_id: UUID, *, document_count: int = 0) -> DocumentsExtracted:
    return DocumentsExtracted(applicant_id=applicant_id, document_count=document_count)


def applicant_screened(applicant_id: UUID, *, risk_level: str = "") -> ApplicantScreened:
    return ApplicantScreened(applicant_id=applicant_id, risk_level=risk_level)
