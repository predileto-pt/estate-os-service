from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from contract_intelligence.application.dtos.review import (
    SourceReviewBundleRead,
    UpdateFieldEvidenceReviewRequest,
    UpdateSourceSectionReviewRequest,
)
from contract_intelligence.domain.exceptions import (
    FieldEvidenceNotFoundError,
    SourceDocumentNotFoundError,
    SourceSectionNotFoundError,
)
from shared.api.dependencies import get_supabase_user_id

logger = structlog.get_logger()

router = APIRouter(prefix="/contracts/review", tags=["contract-review"])


@router.get(
    "/source-documents/{document_id}",
    summary="Get review bundle for a source document",
    description=(
        "Returns the document's parsed sections together with all extracted field evidence "
        "so that a reviewer can inspect, accept, or correct them in one view."
    ),
    response_model=SourceReviewBundleRead,
)
async def get_review_bundle(
    document_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> SourceReviewBundleRead:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.review_service.get_source_review_bundle(document_id)
    except SourceDocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Source document not found.")


@router.patch(
    "/source-sections/{section_id}",
    summary="Update source section review",
    description=(
        "Sets the review status of a parsed section (e.g. `accepted`, `corrected`, `rejected`) "
        "and optionally provides a corrected `normalized_text`."
    ),
    status_code=204,
)
async def update_section_review(
    section_id: UUID,
    payload: UpdateSourceSectionReviewRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> None:
    container = request.app.state.contract_intelligence_container
    try:
        await container.review_service.update_source_section_review(section_id, payload)
    except SourceSectionNotFoundError:
        raise HTTPException(status_code=404, detail="Source section not found.")


@router.patch(
    "/source-field-evidence/{evidence_id}",
    summary="Update field evidence review",
    description=(
        "Sets the review status of an extracted field (e.g. `accepted`, `corrected`) "
        "and optionally provides a `corrected_value_json`."
    ),
    status_code=204,
)
async def update_field_evidence_review(
    evidence_id: UUID,
    payload: UpdateFieldEvidenceReviewRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> None:
    container = request.app.state.contract_intelligence_container
    try:
        await container.review_service.update_field_evidence_review(evidence_id, payload)
    except FieldEvidenceNotFoundError:
        raise HTTPException(status_code=404, detail="Field evidence not found.")
