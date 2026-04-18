from __future__ import annotations

import hashlib
import uuid

from fastapi import UploadFile

from contract_intelligence.application.dtos.source_documents import (
    SourceDocumentDetail,
    SourceDocumentListItem,
    SourceDocumentRead,
    UploadSourceDocumentResponse,
)
from contract_intelligence.application.ports.storage import FileStoragePort
from contract_intelligence.application.ports.unit_of_work import ContractUnitOfWork
from contract_intelligence.domain.entities.source_document import (
    SourceDocument,
)
from contract_intelligence.domain.exceptions import (
    DuplicateDocumentHashError,
    SourceDocumentNotFoundError,
)
from shared.events.base import DomainEvent
from shared.events.ports import CommandPublisher
from shared.events.types import DOCUMENT_INGESTION_REQUESTED_V1


class SourceDocumentService:
    def __init__(
        self,
        uow: ContractUnitOfWork,
        storage: FileStoragePort,
        command_publisher: CommandPublisher,
        *,
        sqs_ingestion_queue_url: str,
        s3_bucket_name: str,
    ) -> None:
        self._uow = uow
        self._storage = storage
        self._command_publisher = command_publisher
        self._sqs_ingestion_queue_url = sqs_ingestion_queue_url
        self._s3_bucket_name = s3_bucket_name

    async def upload_source_document(
        self, file: UploadFile, organization_id: uuid.UUID
    ) -> UploadSourceDocumentResponse:
        data = await file.read()
        document_hash = hashlib.sha256(data).hexdigest()

        doc_id = uuid.uuid4()
        filename = file.filename or "untitled.pdf"
        content_type = file.content_type or "application/pdf"
        storage_key = f"source-documents/{organization_id}/{doc_id}/{filename}"

        storage_url = await self._storage.upload(storage_key, data, content_type)

        async with self._uow:
            existing = await self._uow.source_documents.get_by_hash(document_hash)
            if existing:
                raise DuplicateDocumentHashError(document_hash)

            document = SourceDocument.create(
                filename=filename,
                storage_url=storage_url,
                mime_type=content_type,
                document_hash=document_hash,
                id=doc_id,
                organization_id=organization_id,
            )
            document = await self._uow.source_documents.save(document)
            await self._uow.commit()

        # Publish SQS message AFTER commit so the DB record exists when the
        # worker picks up the message.
        await self._command_publisher.send(
            self._sqs_ingestion_queue_url,
            DomainEvent(
                event_type=DOCUMENT_INGESTION_REQUESTED_V1,
                data={"document_id": str(document.id)},
            ),
        )

        return UploadSourceDocumentResponse(
            id=document.id,
            filename=document.filename,
            storage_url=document.storage_url,
            mime_type=document.mime_type,
            upload_status=document.upload_status.value,
            created_at=document.created_at,
        )

    async def get_source_document(self, document_id: uuid.UUID) -> SourceDocumentRead:
        async with self._uow:
            document = await self._uow.source_documents.get_by_id(document_id)
            if not document:
                raise SourceDocumentNotFoundError(document_id)

        return SourceDocumentRead(
            id=document.id,
            organization_id=document.organization_id,
            filename=document.filename,
            storage_url=document.storage_url,
            mime_type=document.mime_type,
            page_count=document.page_count,
            language_code=document.language_code,
            document_hash=document.document_hash,
            upload_status=document.upload_status.value,
            created_at=document.created_at,
        )

    def _storage_key_from_url(self, storage_url: str) -> str:
        return storage_url.replace(f"s3://{self._s3_bucket_name}/", "")

    async def list_source_documents(
        self, organization_id: uuid.UUID | None = None
    ) -> list[SourceDocumentListItem]:
        async with self._uow:
            if organization_id:
                documents = await self._uow.source_documents.list_by_organization(organization_id)
            else:
                documents = await self._uow.source_documents.list_all()

        items = []
        for doc in documents:
            key = self._storage_key_from_url(doc.storage_url)
            file_url = await self._storage.get_presigned_url(key)
            items.append(
                SourceDocumentListItem(
                    id=doc.id,
                    filename=doc.filename,
                    contract_name=doc.contract_name,
                    file_url=file_url,
                    page_count=doc.page_count,
                    sections_count=len(doc.sections),
                    upload_status=doc.upload_status.value,
                    created_at=doc.created_at,
                )
            )
        return items

    async def get_source_document_detail(self, document_id: uuid.UUID) -> SourceDocumentDetail:
        async with self._uow:
            document = await self._uow.source_documents.get_by_id(document_id)
            if not document:
                raise SourceDocumentNotFoundError(document_id)

        key = self._storage_key_from_url(document.storage_url)
        file_url = await self._storage.get_presigned_url(key)

        # Get parse response from latest succeeded parse run
        latest_run = document.latest_succeeded_parse_run
        parse_response_json = latest_run.response_json if latest_run else None

        return SourceDocumentDetail(
            id=document.id,
            filename=document.filename,
            contract_name=document.contract_name,
            file_url=file_url,
            page_count=document.page_count,
            upload_status=document.upload_status.value,
            created_at=document.created_at,
            parse_response_json=parse_response_json,
        )

    async def retry_document(self, document_id: uuid.UUID) -> UploadSourceDocumentResponse:
        """Reset a FAILED document back to UPLOADED and re-queue for ingestion."""
        async with self._uow:
            document = await self._uow.source_documents.get_by_id(document_id)
            if not document:
                raise SourceDocumentNotFoundError(document_id)

            document.retry()
            await self._uow.source_documents.update_status(document.id, document.upload_status)
            await self._uow.commit()

        # Publish SQS message AFTER commit. Same event type as the fresh-upload
        # path — the ingestion worker treats retry and first-time identically.
        await self._command_publisher.send(
            self._sqs_ingestion_queue_url,
            DomainEvent(
                event_type=DOCUMENT_INGESTION_REQUESTED_V1,
                data={"document_id": str(document.id)},
            ),
        )

        return UploadSourceDocumentResponse(
            id=document.id,
            filename=document.filename,
            storage_url=document.storage_url,
            mime_type=document.mime_type,
            upload_status=document.upload_status.value,
            created_at=document.created_at,
        )
