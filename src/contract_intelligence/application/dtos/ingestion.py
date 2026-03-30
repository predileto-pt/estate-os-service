from __future__ import annotations

import uuid

from pydantic import BaseModel


class IngestResult(BaseModel):
    parse_run_id: uuid.UUID | None = None
    extraction_run_id: uuid.UUID | None = None
    sections_created: int
    fields_extracted: int
