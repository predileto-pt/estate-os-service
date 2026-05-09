from __future__ import annotations

from uuid import UUID

from shared.jobs.application.ports.job_repository import JobRepository
from shared.jobs.domain.job import Job


class GetJob:
    """Returns the job or None — the route layer maps None to 404 alongside
    the cross-org existence-leak prevention."""

    def __init__(self, job_repo: JobRepository) -> None:
        self.job_repo = job_repo

    async def execute(self, job_id: UUID) -> Job | None:
        return await self.job_repo.get_by_id(job_id)
