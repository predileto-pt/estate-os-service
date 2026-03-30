from __future__ import annotations

import uuid

from contract_intelligence.application.dtos.template_versions import (
    CreateTemplateVersionFromSourceResponse,
    TemplateVersionRead,
    UpdateTemplateSectionRequest,
    UpdateTemplateVersionRequest,
)
from contract_intelligence.application.ports.repositories import TemplateRepository


class TemplateService:
    def __init__(self, repo: TemplateRepository) -> None:
        self._repo = repo

    async def create_template_version_from_source(
        self, source_document_id: uuid.UUID
    ) -> CreateTemplateVersionFromSourceResponse:
        raise NotImplementedError

    async def get_template_version(self, version_id: uuid.UUID) -> TemplateVersionRead:
        raise NotImplementedError

    async def update_template_version(
        self, version_id: uuid.UUID, payload: UpdateTemplateVersionRequest
    ) -> None:
        raise NotImplementedError

    async def update_template_section(
        self, section_id: uuid.UUID, payload: UpdateTemplateSectionRequest
    ) -> None:
        raise NotImplementedError

    async def publish_template_version(self, version_id: uuid.UUID) -> None:
        raise NotImplementedError
