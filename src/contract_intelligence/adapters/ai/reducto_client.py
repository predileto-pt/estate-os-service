from __future__ import annotations

import asyncio
from typing import Any

from reducto import AsyncReducto, Reducto

from contract_intelligence.application.ports.reducto import ParsedSection, PipelineResult

# Maximum time (seconds) to wait for a Reducto call
REDUCTO_TIMEOUT_SECONDS = 600


class ReductoClient:
    def __init__(self, api_key: str) -> None:
        self._sync_client = Reducto(api_key=api_key)
        self._async_client = AsyncReducto(api_key=api_key)

    async def upload_file(self, data: bytes, filename: str) -> str:
        upload = await asyncio.to_thread(self._sync_client.upload, file=(filename, data))
        file_id = upload.file_id
        if file_id.startswith("reducto://"):
            return file_id
        return f"reducto://{file_id}"

    async def run_pipeline(self, document_input: str, pipeline_id: str) -> PipelineResult:
        """Parse a document using Reducto's parse API (no pipeline required).

        The pipeline_id parameter is accepted for interface compatibility but
        ignored — we call the parse endpoint directly, which splits the
        document into chunks with titles, page ranges, and text content.
        """
        async with asyncio.timeout(REDUCTO_TIMEOUT_SECONDS):
            response = await self._async_client.parse.run(input=document_input)

        parse_response_json = _to_dict(response)
        job_id = getattr(response, "job_id", "") or ""

        sections = _build_sections_from_parse(response)

        return PipelineResult(
            job_id=job_id,
            parse_response_json=parse_response_json,
            extract_response_json={},
            split_response_json=None,
            sections=sections,
            extracted_fields=[],
        )


def _to_dict(obj: Any) -> dict:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    return {"raw": str(obj)}


def _build_sections_from_parse(result: Any) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    chunks = []

    # result may be a ParseResponse or dict
    if isinstance(result, dict):
        chunks = result.get("chunks", [])
    elif hasattr(result, "chunks"):
        chunks = result.chunks or []

    for idx, chunk in enumerate(chunks):
        if isinstance(chunk, dict):
            content = chunk.get("content", "")
            blocks = chunk.get("blocks", [])
        else:
            content = getattr(chunk, "content", "")
            blocks = getattr(chunk, "blocks", [])

        title = _detect_title(blocks)
        page_start, page_end = _detect_page_range(blocks)

        sections.append(
            ParsedSection(
                sort_order=idx,
                title=title,
                page_start=page_start,
                page_end=page_end,
                content=content,
            )
        )

    return sections


def _detect_title(blocks: list) -> str | None:
    for block in blocks:
        if isinstance(block, dict):
            block_type = block.get("type", "")
            text = block.get("content", "") or block.get("text", "")
        else:
            block_type = getattr(block, "type", "")
            text = getattr(block, "content", "") or getattr(block, "text", "")

        if block_type in ("Title", "Heading", "heading", "title") and text:
            return text.strip()

    return None


def _detect_page_range(blocks: list) -> tuple[int | None, int | None]:
    pages: list[int] = []
    for block in blocks:
        if isinstance(block, dict):
            bbox = block.get("bbox", {})
        else:
            bbox = getattr(block, "bbox", None)
            if bbox and hasattr(bbox, "model_dump"):
                bbox = bbox.model_dump()
            elif bbox and hasattr(bbox, "dict"):
                bbox = bbox.dict()
            else:
                bbox = bbox or {}

        if isinstance(bbox, dict):
            page = bbox.get("page")
            if page is not None:
                pages.append(int(page))

    if pages:
        return min(pages), max(pages)
    return None, None
