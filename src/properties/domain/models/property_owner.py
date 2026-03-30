import enum
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from properties.domain.exceptions import InvalidNIFError


class CivilStatus(str, enum.Enum):
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"
    CIVIL_UNION = "civil_union"
    SEPARATED = "separated"


class DocumentType(str, enum.Enum):
    CARTAO_CIDADAO = "cartao_cidadao"
    PASSPORT = "passport"
    VISTO_RESIDENCIA = "visto_residencia"
    TITULO_RESIDENCIA = "titulo_residencia"


@dataclass
class PropertyOwner:
    id: UUID
    property_id: UUID
    full_name: str
    civil_status: CivilStatus | None
    address: str
    nif: str
    document_type: DocumentType | None
    document_id: str | None
    issued_by: str | None
    issuing_district: str | None
    date_of_birth: date | None
    created_at: datetime
    updated_at: datetime
    email: str | None = None
    phone_number: str | None = None
    email_verified: bool = False
    phone_verified: bool = False

    def __post_init__(self) -> None:
        if not self.nif.isdigit() or len(self.nif) != 9:
            raise InvalidNIFError(self.nif)
