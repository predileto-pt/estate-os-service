from __future__ import annotations

from uuid import UUID

import structlog

from property_management.application.ports.document_storage import DocumentStorage
from property_management.application.ports.event_bus import EventBus
from property_management.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from property_management.domain.events import PropertyExtractionRequested
from property_management.domain.models.extraction_job import (
    ExtractionJob,
    ExtractionJobStatus,
)

log = structlog.get_logger()


class SubmitPropertyExtraction:
    def __init__(
        self,
        document_storage: DocumentStorage,
        extraction_job_repo: ExtractionJobRepository,
        event_bus: EventBus,
    ) -> None:
        self.document_storage = document_storage
        self.extraction_job_repo = extraction_job_repo
        self.event_bus = event_bus

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

        job = ExtractionJob(
            id=UUID(job_id),
            user_id=UUID(user_id),
            organization_id=UUID(organization_id),
            status=ExtractionJobStatus.PENDING,
            document_keys=document_keys,
            listing_type=listing_type,
            typology=typology,
        )
        await self.extraction_job_repo.save(job)

        await self.event_bus.publish(PropertyExtractionRequested(job_id=job_id))

        log.info(
            "extraction.submitted",
            job_id=job_id,
            user_id=user_id,
            num_documents=len(document_keys),
        )
        return job
