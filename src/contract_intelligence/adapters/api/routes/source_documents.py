from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile

from contract_intelligence.application.dtos.source_documents import (
    SourceDocumentDetail,
    SourceDocumentListItem,
    SourceDocumentRead,
    UploadSourceDocumentResponse,
)
from contract_intelligence.domain.exceptions import (
    DuplicateDocumentHashError,
    SourceDocumentNotFoundError,
)
from shared.api.dependencies import get_supabase_user_id

logger = structlog.get_logger()

router = APIRouter(prefix="/contracts/source-documents", tags=["contract-source-documents"])


@router.post(
    "",
    summary="Upload a source document",
    description=(
        "Accepts a PDF or DOCX file, stores it in S3, computes a content hash for deduplication, "
        "and creates a `ContractSourceDocument` record with status `uploaded`."
    ),
    response_model=UploadSourceDocumentResponse,
    status_code=201,
)
async def upload(
    file: UploadFile,
    request: Request,
    organization_id: UUID = Form(..., description="ID of the owning organization."),
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> UploadSourceDocumentResponse:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.source_document_service.upload_source_document(file, organization_id)
    except DuplicateDocumentHashError:
        raise HTTPException(
            status_code=409, detail="A document with the same content already exists."
        )


@router.get(
    "",
    summary="List source documents",
    description="Returns a summary list of all source documents with contract name, page count, and section count.",
    response_model=list[SourceDocumentListItem],
)
async def list_documents(
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> list[SourceDocumentListItem]:
    container = request.app.state.contract_intelligence_container
    return await container.source_document_service.list_source_documents()


@router.get(
    "/{document_id}",
    summary="Get a source document",
    description="Returns the full metadata for a single source document, including current upload status.",
    response_model=SourceDocumentRead,
)
async def get_document(
    document_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> SourceDocumentRead:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.source_document_service.get_source_document(document_id)
    except SourceDocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Source document not found.")


@router.get(
    "/{document_id}/detail",
    summary="Get source document detail with parse data",
    description="Returns full document metadata including the raw Reducto parse output JSON.",
    response_model=SourceDocumentDetail,
)
async def get_document_detail(
    document_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> SourceDocumentDetail:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.source_document_service.get_source_document_detail(document_id)
    except SourceDocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Source document not found.")


@router.post(
    "/{document_id}/parse",
    summary="Request parsing of a source document",
    description=(
        "Enqueues an async parse job (OCR + layout analysis) for the given document. "
        "The document is split into ordered `SourceSection` rows once parsing completes."
    ),
)
async def parse(
    document_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> dict:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.source_document_service.request_parse(document_id)
    except SourceDocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Source document not found.")


@router.post(
    "/{document_id}/extract",
    summary="Request extraction from a source document",
    description=(
        "Enqueues an async extraction job that uses an LLM to pull structured field evidence "
        "from each parsed section. Results are stored as `SourceFieldEvidence` rows."
    ),
)
async def extract(
    document_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> dict:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.source_document_service.request_extract(document_id)
    except SourceDocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Source document not found.")
