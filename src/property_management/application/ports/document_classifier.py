from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ClassifiedDocument:
    index: int
    category: str  # "property_document" or "personal_id"
    document_subtype: str  # e.g. "escritura", "caderneta_predial", "cartao_cidadao", etc.


class DocumentClassifier(ABC):
    @abstractmethod
    async def classify(self, documents: list[bytes]) -> list[ClassifiedDocument]: ...
