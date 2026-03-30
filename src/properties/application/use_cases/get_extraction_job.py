from uuid import UUID

from properties.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from properties.domain.exceptions import ExtractionJobNotFoundError
from properties.domain.models.extraction_job import ExtractionJob


class GetExtractionJob:
    def __init__(self, extraction_job_repo: ExtractionJobRepository) -> None:
        self.extraction_job_repo = extraction_job_repo

    async def execute(self, *, job_id: UUID) -> ExtractionJob:
        job = await self.extraction_job_repo.get_by_id(job_id)
        if job is None:
            raise ExtractionJobNotFoundError(str(job_id))
        return job
