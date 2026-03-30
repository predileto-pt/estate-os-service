from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import structlog

from properties.application.ports.document_storage import DocumentStorage
from properties.domain.exceptions import TooManyDocumentsError

log = structlog.get_logger()

MAX_DOCUMENTS = 5


@dataclass
class PresignedFile:
    s3_key: str
    upload_url: str


class GenerateUploadUrls:
    def __init__(self, document_storage: DocumentStorage) -> None:
        self.document_storage = document_storage

    async def execute(
        self,
        *,
        files: list[dict],
    ) -> tuple[str, list[PresignedFile]]:
        if len(files) > MAX_DOCUMENTS:
            raise TooManyDocumentsError(count=len(files), max_count=MAX_DOCUMENTS)
        if not files:
            raise TooManyDocumentsError(count=0, max_count=MAX_DOCUMENTS)

        job_id = str(uuid4())
        presigned_files = []

        for i, file_spec in enumerate(files):
            s3_key = f"extractions/{job_id}/{i}.pdf"
            content_type = file_spec.get("content_type", "application/pdf")
            upload_url = await self.document_storage.get_upload_url(
                key=s3_key,
                content_type=content_type,
            )
            presigned_files.append(PresignedFile(s3_key=s3_key, upload_url=upload_url))

        log.info("extraction.presign_generated", job_id=job_id, num_files=len(files))
        return job_id, presigned_files
