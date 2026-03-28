from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from uuid import UUID, uuid4


class ListingType(StrEnum):
    ARRENDAMENTO = "ARRENDAMENTO"
    VENDA = "VENDA"


class PropertyType(StrEnum):
    APARTAMENTO = "APARTAMENTO"
    MORADIA = "MORADIA"
    TERRENO = "TERRENO"


@dataclass
class Applicant:
    nif: str
    name: str
    date_of_birth: date
    email: str
    organization_id: UUID
    form_request_id: UUID
    listing_type: ListingType
    phone: str | None = None
    property_type: PropertyType | None = None
    property_value: float | None = None
    monthly_rent: float | None = None
    property_title: str = "n/a"
    property_address: str = "n/a"
    id: UUID = field(default_factory=uuid4)
