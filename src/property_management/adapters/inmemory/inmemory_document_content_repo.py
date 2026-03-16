from __future__ import annotations

from uuid import UUID

from property_management.application.ports.repositories.document_content_repository import (
    DocumentContentRepository,
)
from property_management.domain.models.document_content import DocumentContent


class InMemoryDocumentContentRepository(DocumentContentRepository):
    def __init__(self) -> None:
        self._contents: list[DocumentContent] = []

    async def save(self, content: DocumentContent) -> DocumentContent:
        self._contents.append(content)
        return content

    async def save_batch(self, contents: list[DocumentContent]) -> list[DocumentContent]:
        self._contents.extend(contents)
        return contents

    async def get_by_job_id(self, job_id: UUID) -> list[DocumentContent]:
        return [c for c in self._contents if c.extraction_job_id == job_id]

    async def update_classification(
        self, content_id: UUID, category: str, document_subtype: str
    ) -> None:
        for c in self._contents:
            if c.id == content_id:
                c.category = category
                c.document_subtype = document_subtype
                break
