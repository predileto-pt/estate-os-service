from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class CreateGeneratedContractFromCRMRequest(BaseModel):
    """Payload to generate a new contract from CRM records."""

    template_version_id: uuid.UUID = Field(description="Template version to use for generation.")
    crm_contact_id: str = Field(description="CRM identifier of the contact (buyer/tenant).")
    crm_property_id: str = Field(description="CRM identifier of the property.")
    organization_id: uuid.UUID | None = Field(
        default=None, description="Optional owning client ID."
    )


class GeneratedContractRead(BaseModel):
    """Full metadata of a generated contract."""

    id: uuid.UUID
    contract_template_id: uuid.UUID = Field(description="Parent contract template ID.")
    template_version_id: uuid.UUID = Field(description="Template version used for generation.")
    organization_id: uuid.UUID | None = None
    crm_contact_id: str | None = None
    crm_property_id: str | None = None
    status: str = Field(
        description="Lifecycle status: `draft`, `generated`, `reviewed`, `signed`, or `archived`."
    )
    input_payload_json: dict = Field(description="Resolved input payload used for rendering.")
    rendered_schema_json: dict = Field(description="Rendered schema snapshot at generation time.")
    created_at: datetime
    updated_at: datetime


class RenderGeneratedContractResponse(BaseModel):
    """Artifact metadata returned after rendering a contract to PDF."""

    id: uuid.UUID = Field(description="Artifact ID.")
    artifact_type: str = Field(description="Artifact format (e.g. `pdf`).")
    storage_url: str = Field(description="S3 URL of the rendered artifact.")
    created_at: datetime
