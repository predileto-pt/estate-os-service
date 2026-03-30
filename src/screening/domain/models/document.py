from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID, uuid4


class DocumentType(StrEnum):
    ID_DOCUMENT = "ID_DOCUMENT"
    PROOF_OF_INCOME = "PROOF_OF_INCOME"


class IdDocumentType(StrEnum):
    TITULO_RESIDENCIA = "TITULO_RESIDENCIA"
    CARTAO_CIDADAO = "CARTAO_CIDADAO"
    PASSAPORTE = "PASSAPORTE"


class DocumentStatus(StrEnum):
    PENDING = "PENDING"
    UPLOADED = "UPLOADED"
    EXTRACTING = "EXTRACTING"
    EXTRACTED = "EXTRACTED"


@dataclass
class Document:
    applicant_id: UUID
    s3_key: str
    original_filename: str
    content_type: str
    document_type: DocumentType
    status: DocumentStatus = DocumentStatus.PENDING
    reducto_document_id: str | None = None
    id: UUID = field(default_factory=uuid4)
