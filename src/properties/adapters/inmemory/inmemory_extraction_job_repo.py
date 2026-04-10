from __future__ import annotations

from uuid import UUID

from properties.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from properties.domain.models.extraction_job import ExtractionJob


class InMemoryExtractionJobRepository(ExtractionJobRepository):
    def __init__(self) -> None:
        self._jobs: dict[UUID, ExtractionJob] = {}

    async def save(self, job: ExtractionJob) -> ExtractionJob:
        self._jobs[job.id] = job
        return job

    async def get_by_id(self, job_id: UUID) -> ExtractionJob | None:
        return self._jobs.get(job_id)

    async def list_by_organization(self, organization_id: UUID) -> list[ExtractionJob]:
        return [j for j in self._jobs.values() if j.organization_id == organization_id]

    async def update(self, job: ExtractionJob) -> ExtractionJob:
        self._jobs[job.id] = job
        return job

    async def delete_by_property_id(self, property_id: UUID) -> None:
        self._jobs = {
            jid: job for jid, job in self._jobs.items() if job.property_id != property_id
        }
