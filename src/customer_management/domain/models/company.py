from dataclasses import dataclass
from datetime import datetime, timezone
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

    def update(
        self, *, name: str | None = None, nif: str | None = None, address: str | None = None
    ) -> None:
        if name is not None:
            self.name = name
        if nif is not None:
            self.nif = nif
        if address is not None:
            self.address = address
        self.updated_at = datetime.now(timezone.utc)
