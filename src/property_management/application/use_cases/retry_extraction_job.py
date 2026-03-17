from __future__ import annotations

from uuid import UUID

import structlog

from property_management.application.ports.event_bus import EventBus
from property_management.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from property_management.domain.exceptions import ExtractionJobNotFoundError
from property_management.domain.models.extraction_job import (
    ExtractionJob,
    ExtractionJobStatus,
)

log = structlog.get_logger()


class RetryExtractionJob:
    def __init__(
        self,
        extraction_job_repo: ExtractionJobRepository,
        event_bus: EventBus,
    ) -> None:
        self.extraction_job_repo = extraction_job_repo
        self.event_bus = event_bus

    async def execute(self, *, job_id: UUID) -> ExtractionJob:
        job = await self.extraction_job_repo.get_by_id(job_id)
        if job is None:
            raise ExtractionJobNotFoundError(str(job_id))

        if job.status != ExtractionJobStatus.FAILED:
            raise ValueError(
                f"Only failed jobs can be retried (current status: {job.status.value})"
            )

        job.mark_retrying()
        await self.extraction_job_repo.update(job)

        event_type = (
            "BATCH_PROPERTY_EXTRACTION_REQUESTED"
            if len(job.document_keys) > 1
            else "PROPERTY_EXTRACTION_REQUESTED"
        )
        await self.event_bus.publish(
            {
                "event_type": event_type,
                "data": {"job_id": str(job.id)},
            }
        )

        log.info("extraction.retried", job_id=str(job.id), event_type=event_type)
        return job
