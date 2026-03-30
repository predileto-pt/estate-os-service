from __future__ import annotations

import structlog
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from properties.adapters.ai import get_langfuse_handler

from properties.application.ports.document_classifier import (
    ClassifiedDocument,
    DocumentClassifier,
)
from properties.domain.exceptions import DocumentExtractionError

log = structlog.get_logger()

CLASSIFICATION_PROMPT = """\
You are an expert at classifying Portuguese real estate and identity documents from their OCR text.

For each document below, determine:
1. **category**: either "property_document" or "personal_id"
2. **document_subtype**: the specific type of document

Property documents (category = "property_document"):
- "escritura" — notarial deed of purchase/sale
- "caderneta_predial" — property tax registration
- "certidao" — land registry certificate

Personal ID documents (category = "personal_id"):
- "cartao_cidadao" — Portuguese citizen card
- "passport" — passport
- "visto_residencia" — residence visa
- "titulo_residencia" — residence permit

Classify each document by its index (0-based).\
"""


class DocumentClassification(BaseModel):
    index: int
    category: str
    document_subtype: str


class ClassificationResponse(BaseModel):
    documents: list[DocumentClassification]


class OpenAITextDocumentClassifier(DocumentClassifier):
    def __init__(self, api_key: str, model: str = "gpt-5.4") -> None:
        self._api_key = api_key
        self._model = model

    async def classify(self, document_texts: list[str]) -> list[ClassifiedDocument]:
        llm = ChatOpenAI(model=self._model, api_key=self._api_key)
        structured_llm = llm.with_structured_output(ClassificationResponse)

        labeled_texts = []
        for i, text in enumerate(document_texts):
            labeled_texts.append(f"--- Document {i} ---\n{text}")
        combined = "\n\n".join(labeled_texts)

        prompt = f"{CLASSIFICATION_PROMPT}\n\nDocuments:\n{combined}"

        log.info("classification.text_based", num_documents=len(document_texts))
        langfuse_handler = get_langfuse_handler()
        config = {
            "callbacks": [langfuse_handler] if langfuse_handler else [],
            "run_name": "document_classification",
            "metadata": {"langfuse_tags": ["classification"]},
        }
        try:
            result = await structured_llm.ainvoke(prompt, config=config)
            return [
                ClassifiedDocument(
                    index=d.index,
                    category=d.category,
                    document_subtype=d.document_subtype,
                )
                for d in result.documents
            ]
        except Exception as e:
            raise DocumentExtractionError(f"AI classification failed: {e}") from e
