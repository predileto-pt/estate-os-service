from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class UploadSourceDocumentResponse(BaseModel):
    """Metadata returned after a successful source document upload."""

    id: uuid.UUID = Field(description="Unique identifier of the source document.")
    filename: str = Field(description="Original filename as provided during upload.")
    storage_url: str = Field(description="S3 object URL where the file is stored.")
    mime_type: str = Field(description="MIME type of the uploaded file (e.g. `application/pdf`).")
    upload_status: str = Field(
        description="Current status: `uploaded`, `parsed`, `extracted`, or `failed`."
    )
    created_at: datetime = Field(description="Timestamp when the document was uploaded.")


class SourceDocumentRead(BaseModel):
    """Full metadata of a source document."""

    id: uuid.UUID = Field(description="Unique identifier of the source document.")
    organization_id: uuid.UUID = Field(
        description="ID of the organization that owns this document."
    )
    filename: str = Field(description="Original filename.")
    storage_url: str = Field(description="S3 object URL.")
    mime_type: str = Field(description="MIME type.")
    page_count: int | None = Field(
        default=None, description="Number of pages detected after parsing."
    )
    language_code: str | None = Field(
        default=None, description="ISO 639-1 language code detected after parsing."
    )
    document_hash: str = Field(description="SHA-256 content hash used for deduplication.")
    upload_status: str = Field(
        description="Current status: `uploaded`, `parsed`, `extracted`, or `failed`."
    )
    created_at: datetime = Field(description="Timestamp when the document was uploaded.")


class SourceDocumentListItem(BaseModel):
    """Summary info for a source document in a listing."""

    id: uuid.UUID
    filename: str
    contract_name: str | None = None
    file_url: str
    page_count: int | None = None
    sections_count: int
    upload_status: str
    created_at: datetime


class SourceDocumentDetail(BaseModel):
    """Detail view of a source document with raw parse data."""

    id: uuid.UUID
    filename: str
    contract_name: str | None = None
    file_url: str
    page_count: int | None = None
    upload_status: str
    created_at: datetime
    parse_response_json: dict | None = None
