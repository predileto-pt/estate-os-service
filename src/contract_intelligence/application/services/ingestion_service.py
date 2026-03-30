from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog

from contract_intelligence.application.dtos.ingestion import IngestResult
from contract_intelligence.application.ports.messaging import MessagePublisherPort
from contract_intelligence.application.ports.reducto import ReductoPort
from contract_intelligence.application.ports.repositories import (
    SourceDocumentRepository,
    SourceSectionRepository,
)
from contract_intelligence.application.ports.storage import FileStoragePort
from contract_intelligence.domain.entities.source_document import (
    SourceExtractionRun,
    SourceFieldEvidence,
    SourceParseRun,
    SourceSection,
    UploadStatus,
)
from contract_intelligence.domain.exceptions import SourceDocumentNotFoundError

logger = structlog.get_logger()


class IngestionService:
    def __init__(
        self,
        repo: SourceDocumentRepository,
        section_repo: SourceSectionRepository,
        storage: FileStoragePort,
        reducto: ReductoPort,
        *,
        reducto_pipeline_id: str,
        sqs_analysis_queue_url: str,
        s3_bucket_name: str,
        aws_endpoint_url: str | None = None,
        publisher: MessagePublisherPort | None = None,
    ) -> None:
        self._repo = repo
        self._section_repo = section_repo
        self._storage = storage
        self._reducto = reducto
        self._reducto_pipeline_id = reducto_pipeline_id
        self._sqs_analysis_queue_url = sqs_analysis_queue_url
        self._s3_bucket_name = s3_bucket_name
        self._aws_endpoint_url = aws_endpoint_url
        self._publisher = publisher

    async def ingest(self, document_id: UUID) -> IngestResult:
        document = await self._repo.get_by_id(document_id)
        if not document:
            raise SourceDocumentNotFoundError(document_id)

        # Idempotency guard: only process documents in UPLOADED state
        if document.upload_status != UploadStatus.UPLOADED:
            logger.info(
                "ingestion_skipped_not_uploaded",
                document_id=str(document_id),
                current_status=document.upload_status.value,
            )
            return IngestResult(
                parse_run_id=None,
                extraction_run_id=None,
                sections_created=0,
                fields_extracted=0,
            )

        # Create parse run
        parse_run = SourceParseRun.start(source_document_id=document.id)
        parse_run = await self._repo.save_parse_run(parse_run)

        try:
            # Determine Reducto input based on environment
            if self._aws_endpoint_url:
                # Dev: download from LocalStack S3, upload to Reducto
                storage_key = document.storage_url.replace(f"s3://{self._s3_bucket_name}/", "")
                data = await self._storage.download(storage_key)
                document_input = await self._reducto.upload_file(data, document.filename)
                logger.info(
                    "reducto_file_uploaded", document_id=str(document_id), input=document_input
                )
            else:
                # Prod: generate presigned URL
                storage_key = document.storage_url.replace(f"s3://{self._s3_bucket_name}/", "")
                document_input = await self._storage.get_presigned_url(storage_key)

            # Run Reducto pipeline
            result = await self._reducto.run_pipeline(document_input, self._reducto_pipeline_id)
            logger.info(
                "reducto_pipeline_complete",
                document_id=str(document_id),
                job_id=result.job_id,
                sections=len(result.sections),
                fields=len(result.extracted_fields),
            )

            # Update parse run
            now = datetime.now(UTC)
            parse_run.mark_succeeded(
                completed_at=now,
                provider_job_id=result.job_id,
                response_json=result.parse_response_json,
            )
            await self._repo.update_parse_run(parse_run)

            # Mark document as parsed
            document.mark_parsed()
            await self._repo.update_status(document.id, document.upload_status)

            # Create extraction run
            extraction_run = SourceExtractionRun.create_succeeded(
                source_document_id=document.id,
                schema_version="pipeline-v1",
                extraction_schema_json={"pipeline_id": self._reducto_pipeline_id},
                completed_at=now,
                provider_job_id=result.job_id,
                result_json=result.extract_response_json,
            )
            extraction_run = await self._repo.save_extraction_run(extraction_run)

            # Create sections
            for parsed_section in result.sections:
                section = SourceSection.from_parsed(document.id, parsed_section)
                await self._section_repo.save_section(section)

            # Create field evidence
            for extracted_field in result.extracted_fields:
                evidence = SourceFieldEvidence.from_extracted(extraction_run.id, extracted_field)
                await self._repo.save_field_evidence(evidence)

            # Backfill page count from Reducto response
            page_count = result.parse_response_json.get("usage", {}).get("num_pages")
            if page_count is not None:
                document.record_page_count(page_count)
                await self._repo.update_page_count(document.id, page_count)

            # Update document status
            document.mark_extracted()
            await self._repo.update_status(document.id, document.upload_status)

            # Publish analysis event
            if self._publisher and self._sqs_analysis_queue_url:
                await self._publisher.publish(
                    self._sqs_analysis_queue_url,
                    {"document_id": str(document.id)},
                )

            logger.info("ingestion_complete", document_id=str(document_id))

            return IngestResult(
                parse_run_id=parse_run.id,
                extraction_run_id=extraction_run.id,
                sections_created=len(result.sections),
                fields_extracted=len(result.extracted_fields),
            )

        except Exception:
            # Mark parse run as failed for tracking, but keep document in
            # UPLOADED state so SQS redelivery can retry automatically.
            parse_run.mark_failed(completed_at=datetime.now(UTC))
            await self._repo.update_parse_run(parse_run)
            raise
