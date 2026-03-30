from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from contract_intelligence.application.dtos.template_versions import (
    CreateTemplateVersionFromSourceResponse,
    TemplateVersionRead,
    UpdateTemplateSectionRequest,
    UpdateTemplateVersionRequest,
)
from contract_intelligence.domain.exceptions import (
    SourceDocumentNotFoundError,
    TemplateSectionNotFoundError,
    TemplateVersionAlreadyPublishedError,
    TemplateVersionNotFoundError,
)
from shared.api.dependencies import get_supabase_user_id

logger = structlog.get_logger()

router = APIRouter(prefix="/contracts/template-versions", tags=["contract-templates"])


@router.post(
    "/from-source/{source_document_id}",
    summary="Create template version from source document",
    description=(
        "Promotes a fully reviewed source document into a new template version. "
        "Copies sections as `TemplateSection` rows with Jinja render slots, "
        "creates field bindings, conditions, and party slots derived from the extraction results."
    ),
    response_model=CreateTemplateVersionFromSourceResponse,
    status_code=201,
)
async def create_from_source(
    source_document_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> CreateTemplateVersionFromSourceResponse:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.template_service.create_template_version_from_source(
            source_document_id
        )
    except SourceDocumentNotFoundError:
        raise HTTPException(status_code=404, detail="Source document not found.")


@router.get(
    "/{version_id}",
    summary="Get a template version",
    description="Returns the full template version record including its schema, rules, and status.",
    response_model=TemplateVersionRead,
)
async def get_version(
    version_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> TemplateVersionRead:
    container = request.app.state.contract_intelligence_container
    try:
        return await container.template_service.get_template_version(version_id)
    except TemplateVersionNotFoundError:
        raise HTTPException(status_code=404, detail="Template version not found.")


@router.patch(
    "/{version_id}",
    summary="Update a template version",
    description=(
        "Partially updates a draft template version. "
        "Allowed fields: `review_notes`, `status`, `schema_json`, `computed_rules_json`."
    ),
    status_code=204,
)
async def update_version(
    version_id: UUID,
    payload: UpdateTemplateVersionRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> None:
    container = request.app.state.contract_intelligence_container
    try:
        await container.template_service.update_template_version(version_id, payload)
    except TemplateVersionNotFoundError:
        raise HTTPException(status_code=404, detail="Template version not found.")


@router.patch(
    "/template-sections/{section_id}",
    summary="Update a template section",
    description=(
        "Partially updates an individual template section -- "
        "title, render template, condition expression, optionality, repeatability, or status."
    ),
    status_code=204,
)
async def update_section(
    section_id: UUID,
    payload: UpdateTemplateSectionRequest,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> None:
    container = request.app.state.contract_intelligence_container
    try:
        await container.template_service.update_template_section(section_id, payload)
    except TemplateSectionNotFoundError:
        raise HTTPException(status_code=404, detail="Template section not found.")


@router.post(
    "/{version_id}/publish",
    summary="Publish a template version",
    description=(
        "Transitions a template version from `draft` / `review` to `approved` and sets it as the "
        "current version on the parent `ContractTemplate`. Fails if the version is already published."
    ),
    status_code=204,
)
async def publish_version(
    version_id: UUID,
    request: Request,
    supabase_user_id: str = Depends(get_supabase_user_id),
) -> None:
    container = request.app.state.contract_intelligence_container
    try:
        await container.template_service.publish_template_version(version_id)
    except TemplateVersionNotFoundError:
        raise HTTPException(status_code=404, detail="Template version not found.")
    except TemplateVersionAlreadyPublishedError:
        raise HTTPException(status_code=409, detail="Template version is already published.")
