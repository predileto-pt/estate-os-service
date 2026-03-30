import tempfile
from pathlib import Path
from typing import Any

import structlog
from reducto import Reducto

logger = structlog.get_logger()


class ReductoDocumentExtractor:
    def __init__(self, api_key: str) -> None:
        self._client = Reducto(api_key=api_key)

    async def extract(self, document_source: str | bytes, filename: str = "document.pdf") -> dict[str, Any]:
        import asyncio

        if isinstance(document_source, bytes):
            suffix = Path(filename).suffix or ".pdf"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(document_source)
                tmp_path = Path(tmp.name)
            try:
                upload = await asyncio.to_thread(self._client.upload, file=tmp_path)
                result = await asyncio.to_thread(self._client.parse.run, input=upload)  # type: ignore[arg-type]
            finally:
                tmp_path.unlink(missing_ok=True)
        elif Path(document_source).is_file():
            upload = await asyncio.to_thread(self._client.upload, file=Path(document_source))
            result = await asyncio.to_thread(self._client.parse.run, input=upload)  # type: ignore[arg-type]
        else:
            result = await asyncio.to_thread(self._client.parse.run, input=document_source)  # type: ignore[arg-type]

        logger.info("reducto_extraction_complete", filename=filename)
        return {
            "document_id": result.job_id,  # type: ignore[union-attr]
            "content": [chunk.model_dump() for chunk in result.result.chunks],  # type: ignore[union-attr]
        }
