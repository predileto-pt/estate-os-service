from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class PropertyImage:
    id: UUID
    property_id: UUID
    s3_key: str
    filename: str
    content_type: str
    size_bytes: int
    display_order: int
    created_at: datetime
    updated_at: datetime
