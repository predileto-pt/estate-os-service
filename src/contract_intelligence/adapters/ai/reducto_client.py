from __future__ import annotations

import asyncio
from typing import Any

from reducto import AsyncReducto, Reducto

from contract_intelligence.domain.ports.reducto import ExtractedField, ParsedSection, PipelineResult

# Maximum time (seconds) to wait for a Reducto pipeline run
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
        async with asyncio.timeout(REDUCTO_TIMEOUT_SECONDS):
            response = await self._async_client.pipeline.run(
                input=document_input, pipeline_id=pipeline_id
            )

        parse_response_json: dict[str, Any] = {}
        extract_response_json: dict[str, Any] = {}
        split_response_json: dict[str, Any] | None = None
        job_id = getattr(response, "job_id", "") or ""

        sections: list[ParsedSection] = []
        extracted_fields: list[ExtractedField] = []

        # Walk pipeline steps to find parse and extract results
        for step in getattr(response, "steps", []):
            step_type = getattr(step, "type", "")
            result = getattr(step, "result", None)

            if step_type == "parse" and result is not None:
                parse_response_json = _to_dict(result)
                sections = _build_sections_from_parse(result)

            elif step_type == "extract" and result is not None:
                extract_response_json = _to_dict(result)
                extracted_fields = _build_fields_from_extract(result)

            elif step_type == "split" and result is not None:
                split_response_json = _to_dict(result)

        return PipelineResult(
            job_id=job_id,
            parse_response_json=parse_response_json,
            extract_response_json=extract_response_json,
            split_response_json=split_response_json,
            sections=sections,
            extracted_fields=extracted_fields,
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


def _build_fields_from_extract(result: Any) -> list[ExtractedField]:
    fields: list[ExtractedField] = []

    # Extract result is typically a list of dicts or objects
    items: list = []
    if isinstance(result, list):
        items = result
    elif isinstance(result, dict):
        items = result.get("result", result.get("fields", [result]))
    elif hasattr(result, "result"):
        items = result.result if isinstance(result.result, list) else [result.result]
    else:
        items = [result]

    for item in items:
        if isinstance(item, dict):
            _flatten_extracted_dict(item, fields, prefix="")
        elif hasattr(item, "model_dump"):
            _flatten_extracted_dict(item.model_dump(), fields, prefix="")

    return fields


def _flatten_extracted_dict(
    d: dict[str, Any],
    fields: list[ExtractedField],
    prefix: str,
) -> None:
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict) and not _looks_like_leaf_value(value):
            _flatten_extracted_dict(value, fields, prefix=full_key)
        else:
            fields.append(
                ExtractedField(
                    field_key=full_key,
                    field_value=value,
                )
            )


def _looks_like_leaf_value(d: dict) -> bool:
    return "value" in d or "confidence" in d or "source_text" in d
