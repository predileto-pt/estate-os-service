from __future__ import annotations

import structlog
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from properties.adapters.ai import get_langfuse_handler

from properties.application.ports.property_extractor import (
    GeoLocationResult,
    PropertyExtractionResult,
    PropertyExtractorService,
)

log = structlog.get_logger()


# ── Property extraction schemas & prompt ─────────────────────────────────────


class CharacteristicsSchema(BaseModel):
    area_in_m2: float | None = None
    num_of_bedrooms: int | None = None
    num_of_bathrooms: int | None = None
    built_at: int | None = None
    energy_rating: str | None = None
    floor: int | None = None
    parking_spaces: int | None = None
    has_elevator: bool | None = None
    has_garden: bool | None = None
    has_pool: bool | None = None


class PropertyExtractionSchema(BaseModel):
    address: str
    description: str | None = None
    characteristics: CharacteristicsSchema | None = None
    extraction_reasoning: str


PROPERTY_EXTRACTION_PROMPT = """\
You are extracting structured data from Portuguese real estate documents \
(escrituras, cadernetas prediais, certidões).

Extract the property address, description, and physical characteristics.

In the extraction_reasoning field, explain in Portuguese your reasoning: which parts \
of the document(s) you used to extract each piece of data, any ambiguities you \
encountered, and how you resolved them. Be specific about page references or \
sections when possible.

Documents:
{documents_text}\
"""


# ── Geolocation schemas & prompt ─────────────────────────────────────────────


class GeoLocationSchema(BaseModel):
    latitude: float | None = None
    longitude: float | None = None


GEOLOCATION_EXTRACTION_PROMPT = """\
You are a geolocation assistant. Given a Portuguese property address, \
return the approximate latitude and longitude coordinates.

If you cannot determine the location, return null for both fields.

Address:
{address}\
"""


# ── Extractor ────────────────────────────────────────────────────────────────


class ReductoOpenAIPropertyExtractor(PropertyExtractorService):
    def __init__(self, openai_api_key: str, model: str = "gpt-5.4") -> None:
        self._openai_api_key = openai_api_key
        self._model = model

    async def extract(self, document_texts: list[str]) -> PropertyExtractionResult:
        llm = ChatOpenAI(model=self._model, api_key=self._openai_api_key)
        structured_llm = llm.with_structured_output(PropertyExtractionSchema)

        labeled = []
        for i, text in enumerate(document_texts):
            labeled.append(f"--- Document {i + 1} ---\n{text}")
        documents_text = "\n\n".join(labeled)

        prompt = PROPERTY_EXTRACTION_PROMPT.format(documents_text=documents_text)

        log.info("extraction.property_extraction", num_documents=len(document_texts))
        langfuse_handler = get_langfuse_handler()
        config = {
            "callbacks": [langfuse_handler] if langfuse_handler else [],
            "run_name": "property_extraction",
            "metadata": {"langfuse_tags": ["property-extraction"]},
        }
        result = await structured_llm.ainvoke(prompt, config=config)

        characteristics_dict = None
        if result.characteristics:
            characteristics_dict = result.characteristics.model_dump()

        return PropertyExtractionResult(
            address=result.address,
            description=result.description,
            characteristics=characteristics_dict,
            extraction_reasoning=result.extraction_reasoning,
        )

    async def extract_geolocation(self, address: str) -> GeoLocationResult:
        llm = ChatOpenAI(model=self._model, api_key=self._openai_api_key)
        structured_llm = llm.with_structured_output(GeoLocationSchema)

        prompt = GEOLOCATION_EXTRACTION_PROMPT.format(address=address)

        log.info("extraction.geolocation", address=address)
        langfuse_handler = get_langfuse_handler()
        config = {
            "callbacks": [langfuse_handler] if langfuse_handler else [],
            "run_name": "geolocation_extraction",
            "metadata": {"langfuse_tags": ["geolocation-extraction"]},
        }
        result = await structured_llm.ainvoke(prompt, config=config)

        return GeoLocationResult(
            latitude=result.latitude,
            longitude=result.longitude,
        )
