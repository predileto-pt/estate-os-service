from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID


class ExtractionJobStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ExtractionJob:
    id: UUID
    user_id: UUID
    status: ExtractionJobStatus
    document_keys: list[str] = field(default_factory=list)
    listing_type: str | None = None
    typology: str | None = None
    property_id: UUID | None = None
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_processing(self) -> None:
        self.status = ExtractionJobStatus.PROCESSING
        self.updated_at = datetime.now(timezone.utc)

    def mark_completed(self, property_id: UUID) -> None:
        self.status = ExtractionJobStatus.COMPLETED
        self.property_id = property_id
        self.updated_at = datetime.now(timezone.utc)

    def mark_failed(self, error_message: str) -> None:
        self.status = ExtractionJobStatus.FAILED
        self.error_message = error_message
        self.updated_at = datetime.now(timezone.utc)
