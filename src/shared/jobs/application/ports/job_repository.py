from __future__ import annotations

from typing import Protocol
from uuid import UUID

from shared.jobs.domain.job import Job, JobEntityType, JobKind, JobStatus


class JobRepository(Protocol):
    async def insert(self, job: Job) -> Job: ...

    async def update(self, job: Job) -> Job: ...

    async def get_by_id(self, job_id: UUID) -> Job | None: ...

    async def list(
        self,
        *,
        organization_id: UUID,
        statuses: list[JobStatus] | None = None,
        kind: JobKind | None = None,
        entity_type: JobEntityType | None = None,
        entity_id: UUID | None = None,
        limit: int = 10,
    ) -> list[Job]: ...
