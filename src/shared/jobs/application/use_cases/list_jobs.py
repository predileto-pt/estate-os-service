from __future__ import annotations

from uuid import UUID

from shared.jobs.application.ports.job_repository import JobRepository
from shared.jobs.domain.job import Job, JobEntityType, JobKind, JobStatus


class ListJobs:
    def __init__(self, job_repo: JobRepository) -> None:
        self.job_repo = job_repo

    async def execute(
        self,
        *,
        organization_id: UUID,
        statuses: list[JobStatus] | None = None,
        kind: JobKind | None = None,
        entity_type: JobEntityType | None = None,
        entity_id: UUID | None = None,
        limit: int = 10,
    ) -> list[Job]:
        return await self.job_repo.list(
            organization_id=organization_id,
            statuses=statuses,
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            limit=limit,
        )
