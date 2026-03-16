from __future__ import annotations

import time
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import structlog

from property_management.application.ports.document_classifier import DocumentClassifier
from property_management.application.ports.document_data_extractor import DocumentDataExtractor
from property_management.application.ports.document_storage import DocumentStorage
from property_management.application.ports.property_extractor import PropertyExtractorService
from property_management.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from property_management.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from property_management.domain.exceptions import ExtractionJobNotFoundError
from property_management.domain.models.extraction_job import ExtractionJob
from property_management.domain.models.property import (
    Property,
    PropertyStatus,
)
from property_management.domain.models.property_characteristics import PropertyCharacteristics
from property_management.domain.models.property_owner import (
    CivilStatus,
    DocumentType,
    PropertyOwner,
)

log = structlog.get_logger()


class ProcessBatchPropertyExtraction:
    def __init__(
        self,
        extraction_job_repo: ExtractionJobRepository,
        document_storage: DocumentStorage,
        document_classifier: DocumentClassifier,
        property_extractor: PropertyExtractorService,
        document_data_extractor: DocumentDataExtractor,
        property_repo: PropertyRepository,
    ) -> None:
        self.extraction_job_repo = extraction_job_repo
        self.document_storage = document_storage
        self.document_classifier = document_classifier
        self.property_extractor = property_extractor
        self.document_data_extractor = document_data_extractor
        self.property_repo = property_repo

    async def execute(self, *, job_id: str) -> ExtractionJob:
        start = time.monotonic()

        job = await self.extraction_job_repo.get_by_id(UUID(job_id))
        if job is None:
            raise ExtractionJobNotFoundError(job_id)

        job.mark_processing()
        await self.extraction_job_repo.update(job)
        log.info("batch_extraction.processing", job_id=job_id)

        try:
            # 1. Download all documents
            documents: list[bytes] = []
            for key in job.document_keys:
                data = await self.document_storage.download(key)
                documents.append(data)

            # 2. Classify documents
            classifications = await self.document_classifier.classify(documents)

            property_docs = []
            id_docs = []
            for clf in classifications:
                if clf.category == "property_document":
                    property_docs.append(documents[clf.index])
                else:
                    id_docs.append(documents[clf.index])

            if not property_docs:
                raise ValueError("No property documents found — cannot create property")

            # 3. Extract property data from property documents
            property_result = await self.property_extractor.extract(property_docs)

            # 4. Extract owner data from each ID document
            id_owners: list[dict] = []
            for id_doc in id_docs:
                owner_data = await self.document_data_extractor.extract_property_owner_data(
                    id_doc, "application/pdf"
                )
                id_owners.append(owner_data)

            # 5. Merge owners: property extraction owners + ID extraction owners
            #    Deduplicate by NIF — ID extraction takes precedence
            owners_by_nif: dict[str, dict] = {}
            for owner_data in property_result.owners:
                nif = owner_data.get("nif")
                if nif:
                    owners_by_nif[nif] = owner_data
            for owner_data in id_owners:
                nif = owner_data.get("nif")
                if nif:
                    owners_by_nif[nif] = owner_data

            # 6. Create Property
            if not job.listing_type or not job.typology:
                raise ValueError("listing_type and typology are required on the job")

            now = datetime.now(timezone.utc)
            characteristics = None
            if property_result.characteristics:
                characteristics = PropertyCharacteristics.from_dict(property_result.characteristics)

            prop = Property(
                id=uuid4(),
                user_id=job.user_id,
                address=property_result.address,
                listing_type=job.listing_type,
                typology=job.typology,
                status=PropertyStatus.DRAFT,
                description=property_result.description,
                characteristics=characteristics,
                created_at=now,
                updated_at=now,
            )
            prop = await self.property_repo.save(prop)

            # 7. Create PropertyOwner records
            for owner_data in owners_by_nif.values():
                dob = owner_data.get("date_of_birth")
                if isinstance(dob, str):
                    dob = date.fromisoformat(dob)
                owner = PropertyOwner(
                    id=uuid4(),
                    property_id=prop.id,
                    full_name=owner_data["full_name"],
                    civil_status=CivilStatus(owner_data["civil_status"]),
                    address=owner_data.get("address", property_result.address),
                    nif=owner_data["nif"],
                    document_type=DocumentType(owner_data["document_type"]),
                    document_id=owner_data["document_id"],
                    issued_by=owner_data["issued_by"],
                    issuing_district=owner_data.get("issuing_district"),
                    date_of_birth=dob,
                    created_at=now,
                    updated_at=now,
                )
                prop = await self.property_repo.save_owner(prop, owner)

            # 8. Mark completed
            job.mark_completed(prop.id)
            await self.extraction_job_repo.update(job)

            duration_ms = int((time.monotonic() - start) * 1000)
            log.info(
                "batch_extraction.completed",
                job_id=job_id,
                property_id=str(prop.id),
                num_owners=len(owners_by_nif),
                duration_ms=duration_ms,
            )
        except Exception as exc:
            job.mark_failed(str(exc))
            await self.extraction_job_repo.update(job)

            duration_ms = int((time.monotonic() - start) * 1000)
            log.error(
                "batch_extraction.failed",
                job_id=job_id,
                error=str(exc),
                duration_ms=duration_ms,
            )

        return job
