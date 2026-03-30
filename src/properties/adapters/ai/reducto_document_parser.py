from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import structlog
from reducto import Reducto

from properties.application.ports.document_parser import DocumentParser

log = structlog.get_logger()


class ReductoDocumentParser(DocumentParser):
    def __init__(self, reducto_api_key: str) -> None:
        self._client = Reducto(api_key=reducto_api_key)

    async def parse(self, document_bytes: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(document_bytes)
            tmp_path = Path(tmp.name)
        try:
            upload = await asyncio.to_thread(self._client.upload, file=tmp_path)
            result = await asyncio.to_thread(
                self._client.parse.run,
                input=upload,  # type: ignore[arg-type]
            )
        finally:
            tmp_path.unlink(missing_ok=True)
        return "\n".join(chunk.content for chunk in result.result.chunks)

    async def parse_batch(self, documents: list[bytes]) -> list[str]:
        texts = []
        for i, doc_bytes in enumerate(documents):
            log.info("parsing.reducto_ocr", doc_index=i)
            text = await self.parse(doc_bytes)
            texts.append(text)
        return texts
