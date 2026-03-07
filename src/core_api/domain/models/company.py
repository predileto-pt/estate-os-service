from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class Company:
    id: UUID
    user_id: UUID
    name: str
    nif: str
    address: str
    created_at: datetime
    updated_at: datetime
