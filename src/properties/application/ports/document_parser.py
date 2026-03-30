from __future__ import annotations

from abc import ABC, abstractmethod


class DocumentParser(ABC):
    @abstractmethod
    async def parse(self, document_bytes: bytes) -> str: ...

    @abstractmethod
    async def parse_batch(self, documents: list[bytes]) -> list[str]: ...
