from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from properties.domain.models.extraction_job import ExtractionJob


class ExtractionJobRepository(ABC):
    @abstractmethod
    async def save(self, job: ExtractionJob) -> ExtractionJob: ...

    @abstractmethod
    async def get_by_id(self, job_id: UUID) -> ExtractionJob | None: ...

    @abstractmethod
    async def list_by_organization(self, organization_id: UUID) -> list[ExtractionJob]: ...

    @abstractmethod
    async def update(self, job: ExtractionJob) -> ExtractionJob: ...

    @abstractmethod
    async def delete_by_property_id(self, property_id: UUID) -> None:
        """Delete all extraction jobs (and their document contents) linked to a property."""
        ...
