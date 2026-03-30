from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from contract_intelligence.application.dtos.generated_contracts import (
    CreateGeneratedContractFromCRMRequest,
    GeneratedContractRead,
    RenderGeneratedContractResponse,
)
from contract_intelligence.domain.exceptions import (
    GeneratedContractNotFoundError,
    TemplateVersionNotFoundError,
)
from shared.api.dependencies import get_supabase_user_id

logger = structlog.get_logger()

router = APIRouter(prefix="/contracts/generated-contracts", tags=["contract-generation"])


@router.post(
    "/from-crm",
    summary="Create generated contract from CRM data",
    description=(
        "Resolves CRM contact and property records, maps them onto the template version's "
        "field bindings and party slots, and creates a `GeneratedContract` in `draft` status."
    ),
    response_model=GeneratedContractRead,
    status_code=201,
)
async def create_from_crm(
    payload: CreateGeneratedContractFromCRMRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> GeneratedContractRead:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.generated_contract_service.create_from_crm(payload)
    except TemplateVersionNotFoundError:
        raise HTTPException(status_code=404, detail="Template version not found.")


@router.get(
    "/{contract_id}",
    summary="Get a generated contract",
    description="Returns the full generated contract including its rendered schema and current status.",
    response_model=GeneratedContractRead,
)
async def get_contract(
    contract_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> GeneratedContractRead:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.generated_contract_service.get_generated_contract(contract_id)
    except GeneratedContractNotFoundError:
        raise HTTPException(status_code=404, detail="Generated contract not found.")


@router.post(
    "/{contract_id}/render",
    summary="Render a generated contract",
    description=(
        "Renders each section of the generated contract through the Jinja template engine, "
        "produces a PDF artifact, stores it in S3, and returns the artifact metadata."
    ),
    response_model=RenderGeneratedContractResponse,
)
async def render_contract(
    contract_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> RenderGeneratedContractResponse:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.generated_contract_service.render_generated_contract(contract_id)
    except GeneratedContractNotFoundError:
        raise HTTPException(status_code=404, detail="Generated contract not found.")
