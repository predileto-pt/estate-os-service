from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field


class SourceSectionRead(BaseModel):
    """A parsed section of a source document."""

    id: uuid.UUID
    section_key: str | None = Field(
        default=None, description="Machine-readable section identifier."
    )
    title: str | None = Field(default=None, description="Human-readable section title.")
    page_start: int | None = Field(default=None, description="First page of the section (1-based).")
    page_end: int | None = Field(default=None, description="Last page of the section (1-based).")
    sort_order: int = Field(description="Display order within the document.")
    extracted_text: str | None = Field(
        default=None, description="Raw text extracted by the parser."
    )
    normalized_text: str | None = Field(
        default=None, description="Reviewer-corrected or normalized text."
    )
    classification_confidence: Decimal | None = Field(
        default=None, description="Model confidence for section classification (0-1)."
    )
    review_status: str = Field(
        description="Review status: `pending`, `accepted`, `corrected`, `rejected`, `merged`, or `split`."
    )


class FieldEvidenceRead(BaseModel):
    """A single extracted field value with its provenance."""

    id: uuid.UUID
    source_section_id: uuid.UUID | None = Field(
        default=None, description="Section this evidence was extracted from."
    )
    field_key: str = Field(description="Canonical field key (e.g. `rent_amount`, `start_date`).")
    field_value_json: Any = Field(default=None, description="Extracted value (JSON-typed).")
    source_text: str | None = Field(
        default=None, description="Original text span the value was extracted from."
    )
    page_number: int | None = Field(default=None, description="Page where the evidence was found.")
    confidence: Decimal | None = Field(default=None, description="Extraction confidence (0-1).")
    review_status: str = Field(
        description="Review status: `pending`, `accepted`, `corrected`, or `rejected`."
    )
    corrected_value_json: Any = Field(default=None, description="Reviewer-corrected value, if any.")


class SourceReviewBundleRead(BaseModel):
    """Aggregated review data for a source document -- sections plus field evidence."""

    source_document_id: uuid.UUID
    filename: str
    upload_status: str
    sections: list[SourceSectionRead] = Field(description="Parsed sections in display order.")
    field_evidence: list[FieldEvidenceRead] = Field(
        description="All extracted field evidence across sections."
    )


class UpdateSourceSectionReviewRequest(BaseModel):
    """Payload to update the review status of a parsed section."""

    review_status: str = Field(
        description="New review status (e.g. `accepted`, `corrected`, `rejected`)."
    )
    normalized_text: str | None = Field(
        default=None, description="Corrected text to replace the extracted text."
    )


class UpdateFieldEvidenceReviewRequest(BaseModel):
    """Payload to update the review status of an extracted field."""

    review_status: str = Field(description="New review status (e.g. `accepted`, `corrected`).")
    corrected_value_json: Any = Field(
        default=None, description="Corrected value to replace the extracted value."
    )
