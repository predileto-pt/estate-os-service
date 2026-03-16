from __future__ import annotations

from uuid import UUID

from property_management.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from property_management.domain.models.extraction_job import ExtractionJob


class ListExtractionJobs:
    def __init__(self, extraction_job_repo: ExtractionJobRepository) -> None:
        self.extraction_job_repo = extraction_job_repo

    async def execute(self, *, user_id: str) -> list[ExtractionJob]:
        return await self.extraction_job_repo.list_by_user(UUID(user_id))
