from __future__ import annotations

import structlog
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from property_management.application.ports.property_extractor import (
    PropertyExtractionResult,
    PropertyExtractorService,
)

log = structlog.get_logger()


# ── Classification schemas & prompt ──────────────────────────────────────────


class DocumentClassificationItem(BaseModel):
    index: int
    document_type: str  # "escritura", "caderneta_predial", "certidao", "cartao_cidadao", "passport", "titulo_residencia", "visto_residencia", "unknown"


class DocumentClassificationResult(BaseModel):
    documents: list[DocumentClassificationItem]


CLASSIFICATION_PROMPT = """\
You are an expert at classifying Portuguese legal and identity documents from their OCR text.

For each document below, determine its type. Return the document index and type.

Possible types:
- "escritura" — notarial deed (escritura pública de compra e venda). Contains property sale details, buyer/seller names, property description.
- "caderneta_predial" — property tax registration (caderneta predial urbana/rústica). Contains tax reference (artigo matricial), property area, location, tax value.
- "certidao" — land registry certificate (certidão de teor / certidão permanente). Contains property registration number, ownership chain, encumbrances.
- "cartao_cidadao" — Portuguese citizen card. Contains name, NIF, date of birth, document number, validity.
- "passport" — passport document. Contains name, nationality, date of birth, passport number, issuing country.
- "titulo_residencia" — residence permit (título de residência). Contains name, nationality, NIF, permit number, validity, issuing authority (SEF/AIMA).
- "visto_residencia" — residence visa (visto de residência). Contains name, nationality, visa number, validity.
- "unknown" — if the document does not match any of the above.
"""


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


# ── ID document extraction schemas & prompts ─────────────────────────────────


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

PROPERTY_DOC_TYPES = {"escritura", "caderneta_predial", "certidao"}
ID_DOC_TYPES = {"cartao_cidadao", "passport", "titulo_residencia", "visto_residencia"}


# ── Extractor ────────────────────────────────────────────────────────────────


class ReductoOpenAIPropertyExtractor(PropertyExtractorService):
    def __init__(
        self,
        reducto_api_key: str,
        openai_api_key: str,
        model: str = "gpt-5.4",
    ) -> None:
        self._reducto_api_key = reducto_api_key
        self._openai_api_key = openai_api_key
        self._model = model

    async def extract(self, documents: list[bytes]) -> PropertyExtractionResult:
        llm = ChatOpenAI(model=self._model, api_key=self._openai_api_key)

        # 1. OCR all documents with Reducto
        ocr_texts = await self._ocr_documents(documents)

        # 2. Classify each document
        classifications = await self._classify_documents(llm, ocr_texts)

        # 3. Split into property docs and ID docs
        property_texts: list[str] = []
        id_docs: list[tuple[str, str]] = []  # (doc_type, text)

        for clf in classifications.documents:
            if clf.index < 0 or clf.index >= len(ocr_texts):
                continue
            text = ocr_texts[clf.index]
            if clf.document_type in PROPERTY_DOC_TYPES:
                property_texts.append(text)
            elif clf.document_type in ID_DOC_TYPES:
                id_docs.append((clf.document_type, text))
            else:
                log.warning(
                    "extraction.unknown_doc_type",
                    index=clf.index,
                    document_type=clf.document_type,
                )

        # 4. Extract property data from property docs
        property_result = await self._extract_property(llm, property_texts)

        # 5. Extract owner data from each ID doc with type-specific prompt
        id_owners = []
        for doc_type, text in id_docs:
            owner = await self._extract_id_document(llm, doc_type, text)
            if owner:
                id_owners.append(owner)

        # 6. Merge owners: property extraction + ID docs (dedup by NIF, ID wins)
        all_owners = self._merge_owners(property_result.owners, id_owners)

        characteristics_dict = None
        if property_result.characteristics:
            characteristics_dict = property_result.characteristics.model_dump()

        return PropertyExtractionResult(
            address=property_result.address,
            description=property_result.description,
            characteristics=characteristics_dict,
            owners=all_owners,
        )

    async def _ocr_documents(self, documents: list[bytes]) -> list[str]:
        import reducto

        client = reducto.Reducto(api_key=self._reducto_api_key)

        ocr_texts = []
        for i, doc_bytes in enumerate(documents):
            log.info("extraction.reducto_ocr", doc_index=i)
            upload = client.upload(file=doc_bytes)
            result = client.parse.run(document_url=upload.url)
            text = "\n".join(chunk.content for chunk in result.result.chunks)
            ocr_texts.append(text)
        return ocr_texts

    async def _classify_documents(
        self, llm: ChatOpenAI, ocr_texts: list[str]
    ) -> DocumentClassificationResult:
        structured_llm = llm.with_structured_output(DocumentClassificationResult)

        labeled_texts = []
        for i, text in enumerate(ocr_texts):
            labeled_texts.append(f"--- Document {i} ---\n{text}")
        combined = "\n\n".join(labeled_texts)

        prompt = f"{CLASSIFICATION_PROMPT}\n\nDocuments:\n{combined}"

        log.info("extraction.classifying_documents", num_documents=len(ocr_texts))
        return await structured_llm.ainvoke(prompt)

    async def _extract_property(
        self, llm: ChatOpenAI, property_texts: list[str]
    ) -> PropertyExtractionSchema:
        structured_llm = llm.with_structured_output(PropertyExtractionSchema)

        labeled = []
        for i, text in enumerate(property_texts):
            labeled.append(f"--- Document {i + 1} ---\n{text}")
        documents_text = "\n\n".join(labeled)

        prompt = PROPERTY_EXTRACTION_PROMPT.format(documents_text=documents_text)

        log.info("extraction.property_extraction", num_documents=len(property_texts))
        return await structured_llm.ainvoke(prompt)

    async def _extract_id_document(self, llm: ChatOpenAI, doc_type: str, text: str) -> dict | None:
        prompt_template = ID_PROMPTS.get(doc_type)
        if not prompt_template:
            log.warning("extraction.no_prompt_for_doc_type", document_type=doc_type)
            return None

        structured_llm = llm.with_structured_output(IdOwnerSchema)

        prompt = prompt_template.format(document_text=text)

        log.info("extraction.id_extraction", document_type=doc_type)
        result = await structured_llm.ainvoke(prompt)
        return result.model_dump()

    @staticmethod
    def _merge_owners(property_owners: list[OwnerSchema], id_owners: list[dict]) -> list[dict]:
        owners_by_nif: dict[str, dict] = {}

        # Property extraction owners first (lower priority)
        for owner in property_owners:
            data = owner.model_dump()
            nif = data.get("nif")
            if nif:
                owners_by_nif[nif] = data

        # ID document owners overwrite (higher priority — more accurate)
        for owner_data in id_owners:
            nif = owner_data.get("nif")
            if nif and nif != "000000000":
                # Merge: keep property extraction fields as fallback for nulls
                existing = owners_by_nif.get(nif, {})
                merged = {**existing, **{k: v for k, v in owner_data.items() if v is not None}}
                owners_by_nif[nif] = merged
            elif nif != "000000000":
                # No NIF — add as separate owner if we have a name
                name = owner_data.get("full_name", "")
                if name:
                    owners_by_nif[f"_no_nif_{name}"] = owner_data

        return list(owners_by_nif.values())
