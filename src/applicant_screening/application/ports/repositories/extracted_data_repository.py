from abc import ABC, abstractmethod
from uuid import UUID

from applicant_screening.domain.models import ExtractedData


class ExtractedDataRepository(ABC):
    @abstractmethod
    async def save(self, extracted_data: ExtractedData) -> ExtractedData: ...

    @abstractmethod
    async def get_by_document_id(self, document_id: UUID) -> ExtractedData | None: ...
