import base64

from openai import AsyncOpenAI
from pydantic import BaseModel

from property_management.application.ports.document_data_extractor import DocumentDataExtractor
from property_management.domain.exceptions import DocumentExtractionError

EXTRACTION_PROMPT = """\
You are an expert at extracting personal data from Portuguese identity documents \
(cartão de cidadão, passport, visto de residência, título de residência).
Analyze the uploaded document image and extract the owner's personal information.
For document_type use: 'cartao_cidadao', 'passport', 'visto_residencia', or 'titulo_residencia'.\
"""


class PropertyOwnerExtraction(BaseModel):
    full_name: str
    civil_status: str
    address: str
    nif: str
    document_type: str
    document_id: str
    issued_by: str
    issuing_district: str | None
    date_of_birth: str


class OpenAIDocumentExtractor(DocumentDataExtractor):
    def __init__(self, api_key: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key)

    async def extract_property_owner_data(self, file_bytes: bytes, content_type: str) -> dict:
        b64 = base64.b64encode(file_bytes).decode("utf-8")
        data_url = f"data:{content_type};base64,{b64}"

        try:
            response = await self._client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": EXTRACTION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": data_url},
                            },
                        ],
                    }
                ],
                response_format=PropertyOwnerExtraction,
                max_tokens=1000,
            )
            parsed = response.choices[0].message.parsed
            if not parsed:
                raise DocumentExtractionError("Empty response from AI")
            return parsed.model_dump()
        except DocumentExtractionError:
            raise
        except Exception as e:
            raise DocumentExtractionError(f"AI extraction failed: {e}") from e
