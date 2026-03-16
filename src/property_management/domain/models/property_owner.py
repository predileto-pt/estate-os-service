import enum
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from property_management.domain.exceptions import InvalidNIFError


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
    civil_status: CivilStatus
    address: str
    nif: str
    document_type: DocumentType
    document_id: str
    issued_by: str
    issuing_district: str | None
    date_of_birth: date
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if not self.nif.isdigit() or len(self.nif) != 9:
            raise InvalidNIFError(self.nif)
