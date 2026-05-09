from __future__ import annotations

from typing import Any
from uuid import UUID

from shared.jobs.application.ports.job_repository import JobRepository
from shared.jobs.application.ports.job_tracker import JobTracker
from shared.jobs.application.use_cases.complete_job import CompleteJob
from shared.jobs.application.use_cases.fail_job import FailJob
from shared.jobs.application.use_cases.start_job import StartJob
from shared.jobs.domain.exceptions import JobNotFoundError
from shared.jobs.domain.job import JobEntityType, JobKind


class DefaultJobTracker(JobTracker):
    """Concrete `JobTracker` adapter — wraps the four lifecycle operations
    into the `JobTracker` Protocol shape. `bootstrap.py` constructs one
    instance and passes it into every producing-context container."""

    def __init__(self, job_repo: JobRepository) -> None:
        self._job_repo = job_repo
        self._start = StartJob(job_repo)
        self._complete = CompleteJob(job_repo)
        self._fail = FailJob(job_repo)

    async def start(
        self,
        *,
        organization_id: UUID,
        requested_by_user_id: UUID,
        kind: JobKind,
        entity_type: JobEntityType,
        entity_id: UUID,
        title: str,
    ) -> UUID:
        job = await self._start.execute(
            organization_id=organization_id,
            requested_by_user_id=requested_by_user_id,
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            title=title,
        )
        return job.id

    async def complete(
        self,
        job_id: UUID,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        await self._complete.execute(job_id, result_summary)

    async def fail(
        self,
        job_id: UUID,
        error_code: str,
        error_message: str,
    ) -> None:
        await self._fail.execute(job_id, error_code, error_message)

    async def update_entity_id(self, job_id: UUID, entity_id: UUID) -> None:
        job = await self._job_repo.get_by_id(job_id)
        if job is None:
            raise JobNotFoundError(str(job_id))
        job.update_entity_id(entity_id)
        await self._job_repo.update(job)
