from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import structlog

from contract_intelligence.application.dtos.ingestion import IngestResult
from contract_intelligence.application.ports.reducto import ReductoPort
from contract_intelligence.application.ports.storage import FileStoragePort
from contract_intelligence.application.ports.unit_of_work import ContractUnitOfWork
from contract_intelligence.domain.entities.source_document import (
    SourceParseRun,
    SourceSection,
    UploadStatus,
)
from contract_intelligence.domain.exceptions import SourceDocumentNotFoundError
from shared.events.base import DomainEvent
from shared.events.ports import CommandPublisher
from shared.events.types import DOCUMENT_ANALYSIS_REQUESTED_V1

logger = structlog.get_logger()


class IngestionService:
    def __init__(
        self,
        uow: ContractUnitOfWork,
        storage: FileStoragePort,
        reducto: ReductoPort,
        *,
        sqs_analysis_queue_url: str,
        s3_bucket_name: str,
        aws_endpoint_url: str | None = None,
        command_publisher: CommandPublisher | None = None,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._reducto = reducto
        self._sqs_analysis_queue_url = sqs_analysis_queue_url
        self._s3_bucket_name = s3_bucket_name
        self._aws_endpoint_url = aws_endpoint_url
        self._command_publisher = command_publisher

    async def ingest(self, document_id: UUID) -> IngestResult:
        should_publish = False

        async with self._uow:
            document = await self._uow.source_documents.get_by_id(document_id)
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
                    sections_created=0,
                )

            # Create parse run
            parse_run = SourceParseRun.start(source_document_id=document.id)
            parse_run = await self._uow.source_documents.save_parse_run(parse_run)

            try:
                # Determine Reducto input based on environment
                storage_key = document.storage_url.replace(f"s3://{self._s3_bucket_name}/", "")
                if self._aws_endpoint_url:
                    # Dev: download from LocalStack S3, upload to Reducto
                    data = await self._storage.download(storage_key)
                    document_input = await self._reducto.upload_file(data, document.filename)
                    logger.info(
                        "reducto_file_uploaded", document_id=str(document_id), input=document_input
                    )
                else:
                    # Prod: generate presigned URL for Reducto to fetch directly
                    document_input = await self._storage.get_presigned_url(storage_key)

                # Parse document via Reducto (OCR + layout analysis)
                result = await self._reducto.run_pipeline(document_input, pipeline_id="")
                logger.info(
                    "reducto_parse_complete",
                    document_id=str(document_id),
                    job_id=result.job_id,
                    sections=len(result.sections),
                )

                # Update parse run
                now = datetime.now(UTC)
                parse_run.mark_succeeded(
                    completed_at=now,
                    provider_job_id=result.job_id,
                    response_json=result.parse_response_json,
                )
                await self._uow.source_documents.update_parse_run(parse_run)

                # Create sections from parsed chunks
                for parsed_section in result.sections:
                    section = SourceSection.from_parsed(document.id, parsed_section)
                    await self._uow.source_sections.save_section(section)

                # Backfill page count from Reducto response
                page_count = result.parse_response_json.get("usage", {}).get("num_pages")
                if page_count is not None:
                    document.record_page_count(page_count)
                    await self._uow.source_documents.update_page_count(document.id, page_count)

                # Mark document as parsed (UPLOADED → PARSED)
                document.mark_parsed()
                await self._uow.source_documents.update_status(document.id, document.upload_status)
                await self._uow.commit()

                should_publish = True

                logger.info("ingestion_complete", document_id=str(document_id))

                ingest_result = IngestResult(
                    parse_run_id=parse_run.id,
                    sections_created=len(result.sections),
                )

            except Exception:
                parse_run.mark_failed(completed_at=datetime.now(UTC))
                await self._uow.source_documents.update_parse_run(parse_run)
                document.mark_failed()
                await self._uow.source_documents.update_status(document.id, document.upload_status)
                await self._uow.commit()
                raise

        # Publish to analysis queue AFTER commit
        if should_publish and self._command_publisher and self._sqs_analysis_queue_url:
            await self._command_publisher.send(
                self._sqs_analysis_queue_url,
                DomainEvent(
                    event_type=DOCUMENT_ANALYSIS_REQUESTED_V1,
                    data={"document_id": str(document.id)},
                ),
            )

        return ingest_result
