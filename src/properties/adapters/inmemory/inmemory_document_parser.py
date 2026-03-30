from __future__ import annotations

from properties.application.ports.document_parser import DocumentParser


class InMemoryDocumentParser(DocumentParser):
    async def parse(self, document_bytes: bytes) -> str:
        return "Parsed document text content"

    async def parse_batch(self, documents: list[bytes]) -> list[str]:
        return [await self.parse(doc) for doc in documents]
