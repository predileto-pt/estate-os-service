from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class PropertyExtractionResult:
    address: str
    description: str | None = None
    characteristics: dict | None = None
    owners: list[dict] = field(default_factory=list)
    extraction_reasoning: str | None = None


class PropertyExtractorService(ABC):
    @abstractmethod
    async def extract(self, document_texts: list[str]) -> PropertyExtractionResult: ...
