from __future__ import annotations

import structlog
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from property_management.application.ports.property_extractor import (
    PropertyExtractionResult,
    PropertyExtractorService,
)

log = structlog.get_logger()


# ── Property extraction schemas & prompt ─────────────────────────────────────


class OwnerSchema(BaseModel):
    full_name: str
    civil_status: str
    address: str
    nif: str
    document_type: str
    document_id: str
    issued_by: str
    issuing_district: str | None = None
    date_of_birth: str


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
    owners: list[OwnerSchema]


PROPERTY_EXTRACTION_PROMPT = """\
You are extracting structured data from Portuguese real estate documents \
(escrituras, cadernetas prediais, certidões).

Extract the property address, description, physical characteristics, \
and all property owners mentioned in the documents.

For civil_status use: 'single', 'married', 'divorced', 'widowed', 'civil_union', or 'separated'
For document_type use: 'cartao_cidadao' or 'passport' (based on what is referenced in the deed)
For date_of_birth use ISO format: YYYY-MM-DD

Documents:
{documents_text}\
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
        result = await structured_llm.ainvoke(prompt)

        characteristics_dict = None
        if result.characteristics:
            characteristics_dict = result.characteristics.model_dump()

        return PropertyExtractionResult(
            address=result.address,
            description=result.description,
            characteristics=characteristics_dict,
            owners=[owner.model_dump() for owner in result.owners],
        )
