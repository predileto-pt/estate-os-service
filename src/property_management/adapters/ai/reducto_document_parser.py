from __future__ import annotations

import structlog

from property_management.application.ports.document_parser import DocumentParser

log = structlog.get_logger()


class ReductoDocumentParser(DocumentParser):
    def __init__(self, reducto_api_key: str) -> None:
        self._reducto_api_key = reducto_api_key

    async def parse(self, document_bytes: bytes) -> str:
        import reducto

        client = reducto.Reducto(api_key=self._reducto_api_key)
        upload = client.upload(file=document_bytes)
        result = client.parse.run(document_url=upload.url)
        return "\n".join(chunk.content for chunk in result.result.chunks)

    async def parse_batch(self, documents: list[bytes]) -> list[str]:
        texts = []
        for i, doc_bytes in enumerate(documents):
            log.info("parsing.reducto_ocr", doc_index=i)
            text = await self.parse(doc_bytes)
            texts.append(text)
        return texts
