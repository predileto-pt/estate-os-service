from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class ExtractionStatus(StrEnum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


@dataclass
class ExtractedData:
    document_id: UUID
    extracted_content: dict[str, Any]
    extraction_status: ExtractionStatus = ExtractionStatus.PENDING
    id: UUID = field(default_factory=uuid4)
