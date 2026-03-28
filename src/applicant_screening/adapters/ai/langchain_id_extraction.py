import json
from typing import Any, TypedDict

import structlog
from langchain_openai import ChatOpenAI
from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from applicant_screening.application.dtos import (
    CartaoCidadaoExtraction,
    IdClassificationResult,
    PassaporteExtraction,
    TituloResidenciaExtraction,
)
from applicant_screening.domain.models import IdDocumentType

logger = structlog.get_logger()

CLASSIFIER_PROMPT = (
    "You are an expert at classifying Portuguese identity documents from OCR-extracted content.\n\n"
    "Analyze the following raw OCR content and determine which type of Portuguese identity document it is.\n\n"
    "The possible document types are:\n"
    "- TITULO_RESIDENCIA: Titulo de Residencia (Portuguese Residence Permit). "
    'Look for terms like "TITULO DE RESIDENCIA", "SEF", residence permit numbers.\n'
    "- CARTAO_CIDADAO: Cartao de Cidadao (Portuguese Citizen Card). "
    'Look for terms like "CARTAO DE CIDADAO", "REPUBLICA PORTUGUESA", '
    'citizen card numbers (format: 00000000 0 ZZ0), "BI" references.\n'
    "- PASSAPORTE: Passaporte (Passport). "
    'Look for terms like "PASSAPORTE", "PASSPORT", MRZ lines, passport numbers.\n\n'
    "Raw OCR content:\n{raw_content}\n\n"
    "Classify this document. Provide the document_type "
    "(one of: TITULO_RESIDENCIA, CARTAO_CIDADAO, PASSAPORTE), "
    "your confidence (0.0 to 1.0), and your reasoning."
)

TITULO_EXTRACTION_PROMPT = (
    "You are an expert at extracting structured data from "
    "Portuguese Titulo de Residencia (Residence Permit) documents.\n\n"
    "Extract the following fields from this OCR content of a Titulo de Residencia:\n\n"
    "- full_name: The full name of the holder as it appears on the document\n"
    "- birth_date: Date of birth (format: YYYY-MM-DD if possible, otherwise as shown)\n"
    "- expiry_date: Expiry/validity date of the permit (YYYY-MM-DD if possible)\n"
    "- tax_id_number: The NIF (Numero de Identificacao Fiscal) if present\n\n"
    "For each field, assess your confidence in the extraction accuracy. "
    "Include the confidence as a float (0.0-1.0) in confidence_scores "
    "with the field name as key.\n\n"
    "If a field cannot be found or is illegible, set it to null and add a warning.\n"
    "Set document_type_match to true if the content is consistent with "
    "a Titulo de Residencia, false otherwise.\n\n"
    "Raw OCR content:\n{raw_content}"
)

CARTAO_EXTRACTION_PROMPT = (
    "You are an expert at extracting structured data from "
    "Portuguese Cartao de Cidadao (Citizen Card) documents.\n\n"
    "Extract the following fields from this OCR content of a Cartao de Cidadao:\n\n"
    "- full_name: The full name of the holder as it appears on the document\n"
    "- birth_date: Date of birth (format: YYYY-MM-DD if possible, otherwise as shown)\n"
    "- expiry_date: Expiry/validity date of the card (YYYY-MM-DD if possible)\n"
    "- document_number: The citizen card number\n\n"
    "For each field, assess your confidence in the extraction accuracy. "
    "Include the confidence as a float (0.0-1.0) in confidence_scores "
    "with the field name as key.\n\n"
    "If a field cannot be found or is illegible, set it to null and add a warning.\n"
    "Set document_type_match to true if the content is consistent with "
    "a Cartao de Cidadao, false otherwise.\n\n"
    "Raw OCR content:\n{raw_content}"
)

PASSAPORTE_EXTRACTION_PROMPT = (
    "You are an expert at extracting structured data from "
    "Portuguese Passaporte (Passport) documents.\n\n"
    "Extract the following fields from this OCR content of a Passaporte:\n\n"
    "- first_name: The first/given name of the holder\n"
    "- last_name: The last/family name of the holder\n"
    "- passport_number: The passport number\n"
    "- issue_date: Date of issue (YYYY-MM-DD if possible, otherwise as shown)\n"
    "- expiry_date: Expiry/validity date (YYYY-MM-DD if possible, otherwise as shown)\n\n"
    "For each field, assess your confidence in the extraction accuracy. "
    "Include the confidence as a float (0.0-1.0) in confidence_scores "
    "with the field name as key.\n\n"
    "If a field cannot be found or is illegible, set it to null and add a warning.\n"
    "Set document_type_match to true if the content is consistent with "
    "a Passaporte, false otherwise.\n\n"
    "Raw OCR content:\n{raw_content}"
)


class IdExtractionState(TypedDict):
    raw_content: dict[str, Any]
    classification: dict[str, Any] | None
    extraction: dict[str, Any] | None


_EXTRACTION_MODELS = {
    IdDocumentType.TITULO_RESIDENCIA: (TITULO_EXTRACTION_PROMPT, TituloResidenciaExtraction),
    IdDocumentType.CARTAO_CIDADAO: (CARTAO_EXTRACTION_PROMPT, CartaoCidadaoExtraction),
    IdDocumentType.PASSAPORTE: (PASSAPORTE_EXTRACTION_PROMPT, PassaporteExtraction),
}


class LangChainIdDocumentExtractor:
    def __init__(self, openai_api_key: str) -> None:
        self._llm = ChatOpenAI(model="gpt-5.4", api_key=openai_api_key)  # type: ignore[arg-type]
        self._graph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        graph = StateGraph(IdExtractionState)
        graph.add_node("classify", self._classify)
        graph.add_node("extract_titulo", self._extract_titulo)
        graph.add_node("extract_cartao", self._extract_cartao)
        graph.add_node("extract_passaporte", self._extract_passaporte)

        graph.set_entry_point("classify")
        graph.add_conditional_edges("classify", self._route_by_type)
        graph.add_edge("extract_titulo", END)
        graph.add_edge("extract_cartao", END)
        graph.add_edge("extract_passaporte", END)

        return graph.compile()

    @staticmethod
    def _langfuse_config(*, step_name: str) -> dict[str, Any]:
        handler = LangfuseCallbackHandler()
        metadata = {"langfuse_tags": ["id-extraction", step_name]}
        return {"callbacks": [handler], "run_name": step_name, "metadata": metadata}

    async def _classify(self, state: IdExtractionState) -> dict[str, Any]:
        chain = self._llm.with_structured_output(IdClassificationResult, method="function_calling")
        raw = json.dumps(state["raw_content"], default=str)
        config = self._langfuse_config(step_name="classify_id_document")
        result = await chain.ainvoke(CLASSIFIER_PROMPT.format(raw_content=raw), config=config)  # type: ignore[arg-type]
        return {"classification": result.model_dump() if hasattr(result, "model_dump") else result}  # type: ignore[union-attr]

    @staticmethod
    def _route_by_type(state: IdExtractionState) -> str:
        doc_type = state["classification"]["document_type"]  # type: ignore[index]
        routes = {
            IdDocumentType.TITULO_RESIDENCIA: "extract_titulo",
            IdDocumentType.CARTAO_CIDADAO: "extract_cartao",
            IdDocumentType.PASSAPORTE: "extract_passaporte",
        }
        if doc_type not in routes:
            raise ValueError(f"Unknown ID document type: {doc_type}")
        return routes[doc_type]

    async def _extract_titulo(self, state: IdExtractionState) -> dict[str, Any]:
        return await self._extract(state, IdDocumentType.TITULO_RESIDENCIA)

    async def _extract_cartao(self, state: IdExtractionState) -> dict[str, Any]:
        return await self._extract(state, IdDocumentType.CARTAO_CIDADAO)

    async def _extract_passaporte(self, state: IdExtractionState) -> dict[str, Any]:
        return await self._extract(state, IdDocumentType.PASSAPORTE)

    async def _extract(self, state: IdExtractionState, doc_type: IdDocumentType) -> dict[str, Any]:
        prompt_template, model_cls = _EXTRACTION_MODELS[doc_type]
        chain = self._llm.with_structured_output(model_cls, method="function_calling")
        raw = json.dumps(state["raw_content"], default=str)
        config = self._langfuse_config(step_name=f"extract_{doc_type.value.lower()}")
        result = await chain.ainvoke(prompt_template.format(raw_content=raw), config=config)  # type: ignore[arg-type]
        return {"extraction": result.model_dump() if hasattr(result, "model_dump") else result}  # type: ignore[union-attr]

    async def classify_and_extract(self, raw_content: dict[str, Any]) -> dict[str, Any]:
        initial_state: IdExtractionState = {
            "raw_content": raw_content,
            "classification": None,
            "extraction": None,
        }

        langfuse_handler = LangfuseCallbackHandler()
        pipeline_metadata = {"langfuse_tags": ["id-extraction", "pipeline"]}

        result = await self._graph.ainvoke(
            initial_state,
            config={
                "callbacks": [langfuse_handler],
                "run_name": "id_extraction_pipeline",
                "metadata": pipeline_metadata,
            },
        )
        logger.info(
            "id_document_classified",
            document_type=result["classification"]["document_type"],
            confidence=result["classification"]["confidence"],
        )
        return {
            "classification": result["classification"],
            "extraction": result["extraction"],
        }
