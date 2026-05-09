from __future__ import annotations

from uuid import uuid4
from uuid import UUID

from shared.jobs.application.ports.job_repository import JobRepository
from shared.jobs.domain.job import Job, JobEntityType, JobKind, JobStatus


class StartJob:
    def __init__(self, job_repo: JobRepository) -> None:
        self.job_repo = job_repo

    async def execute(
        self,
        *,
        organization_id: UUID,
        requested_by_user_id: UUID,
        kind: JobKind,
        entity_type: JobEntityType,
        entity_id: UUID,
        title: str,
    ) -> Job:
        job = Job(
            id=uuid4(),
            organization_id=organization_id,
            requested_by_user_id=requested_by_user_id,
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
            status=JobStatus.PROCESSING,
        )
        return await self.job_repo.insert(job)
