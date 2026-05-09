from __future__ import annotations

from copy import deepcopy
from uuid import UUID

from shared.jobs.application.ports.job_repository import JobRepository
from shared.jobs.domain.job import Job, JobEntityType, JobKind, JobStatus


class InMemoryJobRepository(JobRepository):
    def __init__(self) -> None:
        self._rows: dict[UUID, Job] = {}

    async def insert(self, job: Job) -> Job:
        self._rows[job.id] = deepcopy(job)
        return deepcopy(job)

    async def update(self, job: Job) -> Job:
        if job.id not in self._rows:
            raise KeyError(f"Job not found: {job.id}")
        self._rows[job.id] = deepcopy(job)
        return deepcopy(job)

    async def get_by_id(self, job_id: UUID) -> Job | None:
        row = self._rows.get(job_id)
        return deepcopy(row) if row is not None else None

    async def list(
        self,
        *,
        organization_id: UUID,
        statuses: list[JobStatus] | None = None,
        kind: JobKind | None = None,
        entity_type: JobEntityType | None = None,
        entity_id: UUID | None = None,
        limit: int = 10,
    ) -> list[Job]:
        rows = [j for j in self._rows.values() if j.organization_id == organization_id]
        if statuses is not None:
            rows = [j for j in rows if j.status in statuses]
        if kind is not None:
            rows = [j for j in rows if j.kind == kind]
        if entity_type is not None:
            rows = [j for j in rows if j.entity_type == entity_type]
        if entity_id is not None:
            rows = [j for j in rows if j.entity_id == entity_id]
        rows.sort(key=lambda j: j.created_at, reverse=True)
        return [deepcopy(j) for j in rows[:limit]]
