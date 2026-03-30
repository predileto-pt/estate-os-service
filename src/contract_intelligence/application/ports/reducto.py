from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParsedSection:
    sort_order: int
    title: str | None
    page_start: int | None
    page_end: int | None
    content: str


@dataclass
class ExtractedField:
    field_key: str
    field_value: Any
    source_text: str | None = None
    page_number: int | None = None
    confidence: float | None = None


@dataclass
class PipelineResult:
    job_id: str
    parse_response_json: dict
    extract_response_json: dict
    split_response_json: dict | None
    sections: list[ParsedSection] = field(default_factory=list)
    extracted_fields: list[ExtractedField] = field(default_factory=list)


class ReductoPort(ABC):
    @abstractmethod
    async def run_pipeline(self, document_input: str, pipeline_id: str) -> PipelineResult: ...

    @abstractmethod
    async def upload_file(self, data: bytes, filename: str) -> str: ...
