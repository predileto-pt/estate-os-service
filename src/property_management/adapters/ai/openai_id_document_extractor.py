from __future__ import annotations

import structlog
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from property_management.adapters.ai import get_langfuse_handler

from property_management.application.ports.document_data_extractor import DocumentDataExtractor
from property_management.domain.exceptions import DocumentExtractionError

log = structlog.get_logger()


class IdOwnerSchema(BaseModel):
    full_name: str
    civil_status: str | None = None
    address: str | None = None
    nif: str
    document_type: str
    document_id: str
    issued_by: str
    issuing_district: str | None = None
    date_of_birth: str


CARTAO_CIDADAO_PROMPT = """\
You are extracting personal data from a Portuguese Cartão de Cidadão (citizen card).

Extract the following fields from the OCR text:
- full_name: the holder's full name
- civil_status: if mentioned, use 'single', 'married', 'divorced', 'widowed', 'civil_union', or 'separated'. If not present, use null.
- address: the holder's address if present, otherwise null
- nif: the NIF (número de identificação fiscal), 9 digits
- document_type: always 'cartao_cidadao'
- document_id: the document number (número do documento)
- issued_by: 'República Portuguesa'
- issuing_district: the issuing district if present
- date_of_birth: in ISO format YYYY-MM-DD

Document text:
{document_text}\
"""

TITULO_RESIDENCIA_PROMPT = """\
You are extracting personal data from a Portuguese Título de Residência (residence permit).

Extract the following fields from the OCR text:
- full_name: the holder's full name
- civil_status: if mentioned, use 'single', 'married', 'divorced', 'widowed', 'civil_union', or 'separated'. If not present, use null.
- address: the holder's address if present, otherwise null
- nif: the NIF (número de identificação fiscal), 9 digits
- document_type: always 'titulo_residencia'
- document_id: the permit number (número do título)
- issued_by: the issuing authority (e.g. 'SEF', 'AIMA')
- issuing_district: null (not applicable)
- date_of_birth: in ISO format YYYY-MM-DD

Document text:
{document_text}\
"""

VISTO_RESIDENCIA_PROMPT = """\
You are extracting personal data from a Portuguese Visto de Residência (residence visa).

Extract the following fields from the OCR text:
- full_name: the holder's full name
- civil_status: if mentioned, use 'single', 'married', 'divorced', 'widowed', 'civil_union', or 'separated'. If not present, use null.
- address: the holder's address if present, otherwise null
- nif: the NIF (número de identificação fiscal), 9 digits. If not present on the visa, use '000000000'.
- document_type: always 'visto_residencia'
- document_id: the visa number
- issued_by: the issuing authority (e.g. 'SEF', 'AIMA', or the consulate)
- issuing_district: null (not applicable)
- date_of_birth: in ISO format YYYY-MM-DD

Document text:
{document_text}\
"""

PASSPORT_PROMPT = """\
You are extracting personal data from a passport document.

Extract the following fields from the OCR text:
- full_name: the holder's full name
- civil_status: null (passports do not contain civil status)
- address: null (passports do not contain address)
- nif: the NIF if present (Portuguese passports may include it), otherwise '000000000'
- document_type: always 'passport'
- document_id: the passport number
- issued_by: the issuing authority or country
- issuing_district: null (not applicable)
- date_of_birth: in ISO format YYYY-MM-DD

Document text:
{document_text}\
"""

ID_PROMPTS: dict[str, str] = {
    "cartao_cidadao": CARTAO_CIDADAO_PROMPT,
    "titulo_residencia": TITULO_RESIDENCIA_PROMPT,
    "visto_residencia": VISTO_RESIDENCIA_PROMPT,
    "passport": PASSPORT_PROMPT,
}


class OpenAIIdDocumentExtractor(DocumentDataExtractor):
    def __init__(self, api_key: str, model: str = "gpt-5.4") -> None:
        self._api_key = api_key
        self._model = model

    async def extract_property_owner_data(self, parsed_text: str, document_subtype: str) -> dict:
        prompt_template = ID_PROMPTS.get(document_subtype)
        if not prompt_template:
            raise DocumentExtractionError(
                f"No extraction prompt for document subtype: {document_subtype}"
            )

        llm = ChatOpenAI(model=self._model, api_key=self._api_key)
        structured_llm = llm.with_structured_output(IdOwnerSchema)

        prompt = prompt_template.format(document_text=parsed_text)

        log.info("id_extraction.text_based", document_subtype=document_subtype)
        langfuse_handler = get_langfuse_handler()
        config = {
            "callbacks": [langfuse_handler] if langfuse_handler else [],
            "run_name": f"id_extraction_{document_subtype}",
            "metadata": {"langfuse_tags": ["id-extraction", document_subtype]},
        }
        try:
            result = await structured_llm.ainvoke(prompt, config=config)
            return result.model_dump()
        except Exception as e:
            raise DocumentExtractionError(f"AI ID extraction failed: {e}") from e
