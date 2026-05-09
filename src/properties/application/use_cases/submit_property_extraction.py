from __future__ import annotations

from uuid import UUID

import structlog

from properties.application.ports.document_storage import DocumentStorage
from properties.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from properties.domain.models.extraction_job import (
    ExtractionJob,
    ExtractionJobStatus,
)
from shared.events.base import DomainEvent
from shared.events.ports import CommandPublisher
from shared.events.types import PROPERTY_EXTRACTION_REQUESTED_V1
from shared.jobs.application.ports.job_tracker import JobTracker
from shared.jobs.domain.job import JobEntityType, JobKind

log = structlog.get_logger()


class SubmitPropertyExtraction:
    def __init__(
        self,
        document_storage: DocumentStorage,
        extraction_job_repo: ExtractionJobRepository,
        command_publisher: CommandPublisher,
        extraction_queue_url: str,
        job_tracker: JobTracker | None = None,
    ) -> None:
        self.document_storage = document_storage
        self.extraction_job_repo = extraction_job_repo
        self.command_publisher = command_publisher
        self.extraction_queue_url = extraction_queue_url
        self.job_tracker = job_tracker

    async def execute(
        self,
        *,
        job_id: str,
        user_id: str,
        organization_id: str,
        document_keys: list[str],
        listing_type: str,
        typology: str,
    ) -> ExtractionJob:
        prefix = f"extractions/{job_id}/"
        for key in document_keys:
            if not key.startswith(prefix):
                raise ValueError(f"Invalid S3 key: {key} (must start with {prefix})")
            exists = await self.document_storage.verify_exists(key)
            if not exists:
                raise FileNotFoundError(f"Document not found in S3: {key}")

        # Per ADR-012 §Producing-context integration: start the unified
        # tracking row first, with `entity_id=extraction_job.id` as the
        # placeholder. The worker will repoint to the new property's id
        # after completion via `JobTracker.update_entity_id`.
        tracked_job_id: UUID | None = None
        if self.job_tracker is not None:
            tracked_job_id = await self.job_tracker.start(
                organization_id=UUID(organization_id),
                requested_by_user_id=UUID(user_id),
                kind=JobKind.PROPERTY_DOCUMENT_EXTRACTION,
                entity_type=JobEntityType.PROPERTY,
                entity_id=UUID(job_id),
                title=f"Extrair propriedade — {len(document_keys)} documento(s)",
            )

        job = ExtractionJob(
            id=UUID(job_id),
            user_id=UUID(user_id),
            organization_id=UUID(organization_id),
            status=ExtractionJobStatus.PENDING,
            document_keys=document_keys,
            listing_type=listing_type,
            typology=typology,
            tracked_job_id=tracked_job_id,
        )
        await self.extraction_job_repo.save(job)

        await self.command_publisher.send(
            self.extraction_queue_url,
            DomainEvent(
                event_type=PROPERTY_EXTRACTION_REQUESTED_V1,
                data={"job_id": job_id},
            ),
        )

        log.info(
            "extraction.submitted",
            job_id=job_id,
            user_id=user_id,
            num_documents=len(document_keys),
            tracked_job_id=str(tracked_job_id) if tracked_job_id else None,
        )
        return job
