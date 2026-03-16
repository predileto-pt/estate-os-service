import base64

from openai import AsyncOpenAI
from pydantic import BaseModel

from property_management.application.ports.document_classifier import (
    ClassifiedDocument,
    DocumentClassifier,
)
from property_management.domain.exceptions import DocumentExtractionError

CLASSIFICATION_PROMPT = """\
You are an expert at classifying Portuguese real estate and identity documents.

For each uploaded document image, determine:
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


class OpenAIDocumentClassifier(DocumentClassifier):
    def __init__(self, api_key: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)

    async def classify(self, documents: list[bytes]) -> list[ClassifiedDocument]:
        content: list[dict] = [{"type": "text", "text": CLASSIFICATION_PROMPT}]

        for i, doc_bytes in enumerate(documents):
            b64 = base64.b64encode(doc_bytes).decode("utf-8")
            content.append({"type": "text", "text": f"Document {i}:"})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:application/pdf;base64,{b64}"},
                }
            )

        try:
            response = await self._client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=[{"role": "user", "content": content}],
                response_format=ClassificationResponse,
                max_tokens=1000,
            )
            parsed = response.choices[0].message.parsed
            if not parsed:
                raise DocumentExtractionError("Empty classification response from AI")
            return [
                ClassifiedDocument(
                    index=d.index,
                    category=d.category,
                    document_subtype=d.document_subtype,
                )
                for d in parsed.documents
            ]
        except DocumentExtractionError:
            raise
        except Exception as e:
            raise DocumentExtractionError(f"AI classification failed: {e}") from e
