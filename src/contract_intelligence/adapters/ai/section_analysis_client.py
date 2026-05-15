from __future__ import annotations

import asyncio
import functools
from uuid import UUID

import structlog
from langchain.chat_models import init_chat_model
from langfuse import propagate_attributes

from contract_intelligence.application.dtos.section_analysis import SourceSectionAnalysisBatchOutput
from contract_intelligence.domain.entities.source_document import (
    SourceFieldEvidence,
    SourceSection,
)

# Maximum time (seconds) to wait for an LLM response
LLM_TIMEOUT_SECONDS = 300

logger = structlog.get_logger()

SYSTEM_PROMPT = """\
You are an expert analyst of Portuguese real-estate contracts.
You receive a list of sections extracted from a source contract document,
together with structured field evidence already extracted from that document.

For each section you must determine:
1. **section_type** – classify the section content:
   - `static`: boilerplate that rarely changes across contracts of the same type.
   - `parameterized`: contains placeholders that vary per contract (names, dates, amounts …).
   - `conditional`: included only when certain conditions apply (e.g. guarantor clause).
   - `generative`: needs AI drafting because the language varies significantly.
2. **reasoning** – a short explanation of why you chose this classification.
3. **risk_level** – how risky it would be to render this section incorrectly:
   - `low`, `medium`, or `high`.
4. **recommended_strategy** – how the template engine should handle this section:
   - `literal`: copy verbatim.
   - `template`: use a Jinja template with field placeholders.
   - `template_variant`: like `template` but with conditional blocks.
   - `ai_draft`: let an LLM draft the section from context.
5. **references** – which extracted fields or conditions this section depends on.

Return **one analysis per section**, keyed by `source_section_id`.
"""


def _build_human_message(
    sections: list[SourceSection],
    field_evidence: list[SourceFieldEvidence],
) -> str:
    parts: list[str] = ["## Sections\n"]
    for s in sections:
        parts.append(f"### Section {s.id}")
        if s.title:
            parts.append(f"**Title:** {s.title}")
        if s.extracted_text:
            parts.append(f"**Text:**\n{s.extracted_text}")
        parts.append("")

    parts.append("## Extracted Fields\n")
    for fe in field_evidence:
        parts.append(f"- **{fe.field_key}**: {fe.field_value_json}")

    return "\n".join(parts)


@functools.cache
def _get_langfuse_handler():
    """Lazily build and cache a single Langfuse CallbackHandler."""
    try:
        from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler

        return LangfuseCallbackHandler()
    except Exception:
        logger.warning("langfuse_init_failed", exc_info=True)
        return None


class SectionAnalysisLLMClient:
    def __init__(self, *, openai_api_key: str, model: str = "openai:gpt-5.4") -> None:
        self._model = model
        self._openai_api_key = openai_api_key

    async def analyze_sections(
        self,
        sections: list[SourceSection],
        field_evidence: list[SourceFieldEvidence],
        *,
        document_id: UUID | None = None,
    ) -> SourceSectionAnalysisBatchOutput:
        langfuse_handler = _get_langfuse_handler()
        callbacks = [langfuse_handler] if langfuse_handler else []

        llm = init_chat_model(
            model=self._model,
            api_key=self._openai_api_key,
        )
        structured_llm = llm.with_structured_output(SourceSectionAnalysisBatchOutput)

        human_message = _build_human_message(sections, field_evidence)

        logger.info(
            "llm_section_analysis_request",
            model=self._model,
            section_count=len(sections),
            field_count=len(field_evidence),
            document_id=str(document_id) if document_id else None,
            langfuse_enabled=langfuse_handler is not None,
        )

        metadata = {
            "section_count": len(sections),
            "field_count": len(field_evidence),
            "model": self._model,
        }
        if document_id:
            metadata["document_id"] = str(document_id)

        with propagate_attributes(
            trace_name="section-analysis",
            tags=["section-analysis", "contract-intelligence"],
            metadata=metadata,
        ):
            async with asyncio.timeout(LLM_TIMEOUT_SECONDS):
                result = await structured_llm.ainvoke(
                    [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "human", "content": human_message},
                    ],
                    config={"callbacks": callbacks} if callbacks else {},
                )

        logger.info(
            "llm_section_analysis_response",
            document_id=str(document_id) if document_id else None,
            analyses_count=len(result.analyses),
        )

        return result
