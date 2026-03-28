from abc import ABC, abstractmethod
from uuid import UUID

from applicant_screening.domain.models import Document


class DocumentRepository(ABC):
    @abstractmethod
    async def save(self, document: Document) -> Document: ...

    @abstractmethod
    async def get_by_id(self, document_id: UUID) -> Document | None: ...

    @abstractmethod
    async def get_by_applicant_id(self, applicant_id: UUID) -> list[Document]: ...

    @abstractmethod
    async def update(self, document: Document) -> Document: ...
