from __future__ import annotations

from uuid import UUID

from property_management.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from property_management.domain.models.extraction_job import ExtractionJob


class InMemoryExtractionJobRepository(ExtractionJobRepository):
    def __init__(self) -> None:
        self._jobs: dict[UUID, ExtractionJob] = {}

    async def save(self, job: ExtractionJob) -> ExtractionJob:
        self._jobs[job.id] = job
        return job

    async def get_by_id(self, job_id: UUID) -> ExtractionJob | None:
        return self._jobs.get(job_id)

    async def list_by_user(self, user_id: UUID) -> list[ExtractionJob]:
        return [j for j in self._jobs.values() if j.user_id == user_id]

    async def update(self, job: ExtractionJob) -> ExtractionJob:
        self._jobs[job.id] = job
        return job
