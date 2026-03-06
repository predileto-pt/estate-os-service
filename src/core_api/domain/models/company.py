from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from core_api.domain.models.value_objects import Address


@dataclass
class Company:
    id: UUID
    name: str
    tax_id_number: str  # NIF (PT) or CIF (ES)
    address: Address
    stripe_customer_id: str | None
    created_at: datetime
    updated_at: datetime
