from __future__ import annotations

from uuid import UUID

from shared.jobs.application.ports.job_repository import JobRepository
from shared.jobs.domain.exceptions import JobNotFoundError


class FailJob:
    def __init__(self, job_repo: JobRepository) -> None:
        self.job_repo = job_repo

    async def execute(
        self,
        job_id: UUID,
        error_code: str,
        error_message: str,
    ) -> None:
        job = await self.job_repo.get_by_id(job_id)
        if job is None:
            raise JobNotFoundError(str(job_id))
        job.mark_failed(error_code=error_code, error_message=error_message)
        await self.job_repo.update(job)
