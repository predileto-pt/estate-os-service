from __future__ import annotations

from uuid import UUID

import structlog

from properties.application.ports.event_bus import EventBus
from properties.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from properties.domain.exceptions import ExtractionJobNotFoundError
from properties.domain.models.extraction_job import (
    ExtractionJob,
    ExtractionJobStatus,
)
from shared.events.base import DomainEvent
from shared.events.types import (
    BATCH_PROPERTY_EXTRACTION_REQUESTED_V1,
    PROPERTY_EXTRACTION_REQUESTED_V1,
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
            BATCH_PROPERTY_EXTRACTION_REQUESTED_V1
            if len(job.document_keys) > 1
            else PROPERTY_EXTRACTION_REQUESTED_V1
        )
        event = DomainEvent(event_type=event_type, data={"job_id": str(job.id)})
        await self.event_bus.publish(event)

        log.info("extraction.retried", job_id=str(job.id), event_type=event_type)
        return job
