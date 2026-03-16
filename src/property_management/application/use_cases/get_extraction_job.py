from uuid import UUID

from property_management.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from property_management.domain.exceptions import ExtractionJobNotFoundError
from property_management.domain.models.extraction_job import ExtractionJob


class GetExtractionJob:
    def __init__(self, extraction_job_repo: ExtractionJobRepository) -> None:
        self.extraction_job_repo = extraction_job_repo

    async def execute(self, *, job_id: UUID) -> ExtractionJob:
        job = await self.extraction_job_repo.get_by_id(job_id)
        if job is None:
            raise ExtractionJobNotFoundError(str(job_id))
        return job
