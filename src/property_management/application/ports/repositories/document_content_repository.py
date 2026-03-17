from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from property_management.domain.models.document_content import DocumentContent


class DocumentContentRepository(ABC):
    @abstractmethod
    async def save(self, content: DocumentContent) -> DocumentContent: ...

    @abstractmethod
    async def save_batch(self, contents: list[DocumentContent]) -> list[DocumentContent]: ...

    @abstractmethod
    async def get_by_job_id(self, job_id: UUID) -> list[DocumentContent]: ...

    @abstractmethod
    async def update_classification(
        self, content_id: UUID, category: str, document_subtype: str
    ) -> None: ...

    @abstractmethod
    async def update_extraction_reasoning(
        self, content_id: UUID, extraction_reasoning: str
    ) -> None: ...
