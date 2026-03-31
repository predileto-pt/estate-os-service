from abc import ABC, abstractmethod
from typing import Any


class DocumentExtractor(ABC):
    @abstractmethod
    async def extract(
        self, document_source: str | bytes, filename: str = "document.pdf"
    ) -> dict[str, Any]: ...
