from __future__ import annotations

import time
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import structlog

from properties.application.ports.document_classifier import DocumentClassifier
from properties.application.ports.document_data_extractor import DocumentDataExtractor
from properties.application.ports.document_parser import DocumentParser
from properties.application.ports.document_storage import DocumentStorage
from properties.application.ports.property_extractor import PropertyExtractorService
from properties.application.ports.repositories.document_content_repository import (
    DocumentContentRepository,
)
from properties.application.ports.repositories.extraction_job_repository import (
    ExtractionJobRepository,
)
from properties.application.ports.repositories.property_repository import (
    PropertyRepository,
)
from properties.domain.exceptions import ExtractionJobNotFoundError
from properties.domain.models.document_content import DocumentContent
from properties.domain.models.extraction_job import ExtractionJob, ExtractionJobStatus
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_characteristics import PropertyCharacteristics
from properties.domain.models.property_owner import (
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
        document_parser: DocumentParser,
        document_classifier: DocumentClassifier,
        property_extractor: PropertyExtractorService,
        document_data_extractor: DocumentDataExtractor,
        property_repo: PropertyRepository,
        document_content_repo: DocumentContentRepository,
    ) -> None:
        self.extraction_job_repo = extraction_job_repo
        self.document_storage = document_storage
        self.document_parser = document_parser
        self.document_classifier = document_classifier
        self.property_extractor = property_extractor
        self.document_data_extractor = document_data_extractor
        self.property_repo = property_repo
        self.document_content_repo = document_content_repo

    async def execute(self, *, job_id: str) -> ExtractionJob:
        start = time.monotonic()

        job = await self.extraction_job_repo.get_by_id(UUID(job_id))
        if job is None:
            raise ExtractionJobNotFoundError(job_id)

        if job.status == ExtractionJobStatus.COMPLETED:
            log.info(
                "batch_extraction.skip_already_completed",
                job_id=job_id,
                property_id=str(job.property_id) if job.property_id else None,
            )
            return job

        job.mark_processing()
        await self.extraction_job_repo.update(job)
        log.info("batch_extraction.processing", job_id=job_id)

        try:
            # Check for already-parsed content (retry scenario)
            existing_contents = await self.document_content_repo.get_by_job_id(job.id)
            if (
                existing_contents
                and len(existing_contents) == len(job.document_keys)
                and all(c.parsed_text for c in existing_contents)
            ):
                log.info(
                    "batch_extraction.using_cached_parse",
                    job_id=job_id,
                    num_docs=len(existing_contents),
                )
                contents = existing_contents
                parsed_texts = [c.parsed_text for c in existing_contents]
            else:
                # 1. Download all documents from S3
                documents: list[bytes] = []
                for key in job.document_keys:
                    data = await self.document_storage.download(key)
                    documents.append(data)

                # 2. Parse all documents with Reducto (single OCR pass)
                parsed_texts = await self.document_parser.parse_batch(documents)

                # 3. Persist parsed content → document_contents table
                contents = [
                    DocumentContent(
                        id=uuid4(),
                        extraction_job_id=job.id,
                        document_index=i,
                        document_key=job.document_keys[i],
                        parsed_text=text,
                    )
                    for i, text in enumerate(parsed_texts)
                ]
                contents = await self.document_content_repo.save_batch(contents)

            # 4. Classify parsed text (text-based, no vision)
            classifications = await self.document_classifier.classify(parsed_texts)

            # 5. Update document_contents with classification
            for clf in classifications:
                if 0 <= clf.index < len(contents):
                    await self.document_content_repo.update_classification(
                        contents[clf.index].id,
                        clf.category,
                        clf.document_subtype,
                    )

            # 6. Split into property texts / ID docs by category
            property_texts: list[str] = []
            id_docs: list[tuple[str, str]] = []  # (document_subtype, text)
            for clf in classifications:
                if clf.index < 0 or clf.index >= len(parsed_texts):
                    continue
                text = parsed_texts[clf.index]
                if clf.category == "property_document":
                    property_texts.append(text)
                elif clf.category == "personal_id":
                    id_docs.append((clf.document_subtype, text))
                else:
                    log.warning(
                        "batch_extraction.unknown_category",
                        index=clf.index,
                        category=clf.category,
                    )

            if not property_texts:
                raise ValueError("No property documents found — cannot create property")

            # 7. Extract property data from property texts (no OCR needed)
            property_result = await self.property_extractor.extract(property_texts)

            # 7b. Store extraction reasoning on property document contents
            if property_result.extraction_reasoning:
                for clf in classifications:
                    if clf.category == "property_document" and 0 <= clf.index < len(contents):
                        await self.document_content_repo.update_extraction_reasoning(
                            contents[clf.index].id,
                            property_result.extraction_reasoning,
                        )

            # 8. Extract owners from each ID doc text (no OCR, subtype-routed)
            id_owners: list[dict] = []
            for doc_subtype, text in id_docs:
                owner_data = await self.document_data_extractor.extract_property_owner_data(
                    text, doc_subtype
                )
                id_owners.append(owner_data)

            # 7c. Extract geolocation (non-fatal)
            latitude = None
            longitude = None
            try:
                geo = await self.property_extractor.extract_geolocation(property_result.address)
                latitude = geo.latitude
                longitude = geo.longitude
            except Exception:
                log.warning("batch_extraction.geolocation_failed", address=property_result.address)

            # 9. Collect owners from ID docs (dedup by NIF)
            owners_by_nif: dict[str, dict] = {}
            for owner_data in id_owners:
                nif = owner_data.get("nif")
                if nif and nif != "000000000":
                    owners_by_nif[nif] = owner_data
                elif nif != "000000000":
                    name = owner_data.get("full_name", "")
                    if name:
                        owners_by_nif[f"_no_nif_{name}"] = owner_data

            # 10. Create Property + PropertyOwner records
            if not job.listing_type or not job.typology:
                raise ValueError("listing_type and typology are required on the job")

            now = datetime.now(timezone.utc)
            characteristics = None
            if property_result.characteristics:
                characteristics = PropertyCharacteristics.from_dict(property_result.characteristics)

            prop = Property(
                id=uuid4(),
                organization_id=job.organization_id,
                address=property_result.address,
                listing_type=ListingType(job.listing_type),
                typology=Typology(job.typology),
                status=PropertyStatus.DRAFT,
                description=property_result.description,
                characteristics=characteristics,
                latitude=latitude,
                longitude=longitude,
                created_at=now,
                updated_at=now,
            )
            prop = await self.property_repo.save(prop)

            for owner_data in owners_by_nif.values():
                dob = owner_data.get("date_of_birth")
                if isinstance(dob, str) and dob:
                    dob = date.fromisoformat(dob)
                else:
                    dob = None

                nif = owner_data.get("nif")
                full_name = owner_data.get("full_name")
                if not nif or not full_name:
                    log.warning(
                        "batch_extraction.skipping_owner", reason="missing nif or full_name"
                    )
                    continue

                civil_status_raw = owner_data.get("civil_status")
                civil_status = CivilStatus(civil_status_raw) if civil_status_raw else None
                doc_type_raw = owner_data.get("document_type")
                document_type = DocumentType(doc_type_raw) if doc_type_raw else None

                owner = PropertyOwner(
                    id=uuid4(),
                    property_id=prop.id,
                    full_name=full_name,
                    civil_status=civil_status,
                    address=owner_data.get("address") or property_result.address,
                    nif=nif,
                    document_type=document_type,
                    document_id=owner_data.get("document_id"),
                    issued_by=owner_data.get("issued_by"),
                    issuing_district=owner_data.get("issuing_district"),
                    date_of_birth=dob,
                    created_at=now,
                    updated_at=now,
                )
                prop = await self.property_repo.save_owner(prop, owner)

            # 11. Mark job completed
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
            log.exception(
                "batch_extraction.failed",
                job_id=job_id,
                error=str(exc),
                exc_type=type(exc).__qualname__,
                duration_ms=duration_ms,
            )

        return job
