from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

import structlog

from properties.application.ports.document_parser import DocumentParser
from properties.application.ports.document_storage import DocumentStorage
from properties.application.ports.property_extractor import (
    PropertyExtractorService,
)
from properties.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import ExtractionJobNotFoundError
from properties.domain.models.extraction_job import ExtractionJob, ExtractionJobStatus
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_characteristics import (
    PropertyCharacteristics,
)
from shared.events.base import DomainEvent as SharedDomainEvent
from shared.events.ports import EventPublisher
from shared.events.types import PROPERTY_CREATED_V1

log = structlog.get_logger()


class ProcessPropertyExtraction:
    def __init__(
        self,
        extraction_job_repo: ExtractionJobRepository,
        document_storage: DocumentStorage,
        document_parser: DocumentParser,
        property_extractor: PropertyExtractorService,
        property_repo: PropertyRepository,
        domain_event_publisher: EventPublisher | None = None,
    ) -> None:
        self.extraction_job_repo = extraction_job_repo
        self.document_storage = document_storage
        self.document_parser = document_parser
        self.property_extractor = property_extractor
        self.property_repo = property_repo
        self.domain_event_publisher = domain_event_publisher

    async def execute(self, *, job_id: str) -> ExtractionJob:
        start = time.monotonic()

        job = await self.extraction_job_repo.get_by_id(UUID(job_id))
        if job is None:
            raise ExtractionJobNotFoundError(job_id)

        if job.status == ExtractionJobStatus.COMPLETED:
            log.info(
                "extraction.skip_already_completed",
                job_id=job_id,
                property_id=str(job.property_id) if job.property_id else None,
            )
            return job

        job.mark_processing()
        await self.extraction_job_repo.update(job)
        log.info("extraction.processing", job_id=job_id)

        try:
            # 1. Download documents
            documents = []
            for key in job.document_keys:
                data = await self.document_storage.download(key)
                documents.append(data)

            # 2. Parse documents (single OCR pass)
            parsed_texts = await self.document_parser.parse_batch(documents)

            # 3. Extract property data from parsed text
            result = await self.property_extractor.extract(parsed_texts)

            now = datetime.now(timezone.utc)
            characteristics = None
            if result.characteristics:
                characteristics = PropertyCharacteristics.from_dict(result.characteristics)

            if not job.listing_type or not job.typology:
                raise ValueError("listing_type and typology are required on the job")

            # Extract geolocation (non-fatal)
            latitude = None
            longitude = None
            try:
                geo = await self.property_extractor.extract_geolocation(result.address)
                latitude = geo.latitude
                longitude = geo.longitude
            except Exception:
                log.warning("extraction.geolocation_failed", address=result.address)

            prop = Property(
                id=uuid4(),
                organization_id=job.organization_id,
                address=result.address,
                listing_type=ListingType(job.listing_type),
                typology=Typology(job.typology),
                status=PropertyStatus.DRAFT,
                description=result.description,
                characteristics=characteristics,
                latitude=latitude,
                longitude=longitude,
                created_at=now,
                updated_at=now,
            )
            prop = await self.property_repo.save(prop)

            if self.domain_event_publisher:
                try:
                    await self.domain_event_publisher.publish(
                        SharedDomainEvent(
                            event_type=PROPERTY_CREATED_V1, data={"property_id": str(prop.id)}
                        )
                    )
                except Exception:
                    log.exception(
                        "extraction.domain_event_failed",
                        property_id=str(prop.id),
                    )

            job.mark_completed(prop.id)
            await self.extraction_job_repo.update(job)

            duration_ms = int((time.monotonic() - start) * 1000)
            log.info(
                "extraction.completed",
                job_id=job_id,
                property_id=str(prop.id),
                duration_ms=duration_ms,
            )
        except Exception as exc:
            job.mark_failed(str(exc))
            await self.extraction_job_repo.update(job)

            duration_ms = int((time.monotonic() - start) * 1000)
            log.exception(
                "extraction.failed",
                job_id=job_id,
                error=str(exc),
                exc_type=type(exc).__qualname__,
                duration_ms=duration_ms,
            )

        return job
