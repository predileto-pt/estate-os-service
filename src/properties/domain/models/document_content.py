from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class DocumentContent:
    id: UUID
    extraction_job_id: UUID
    document_index: int
    document_key: str
    parsed_text: str
    category: str | None = None  # "property_document" or "personal_id"
    document_subtype: str | None = None  # "escritura", "cartao_cidadao", etc.
    extraction_reasoning: str | None = None
    created_at: datetime | None = None
