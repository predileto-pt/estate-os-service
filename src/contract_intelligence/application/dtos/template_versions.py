from __future__ import annotations

import uuid
import warnings
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Pydantic v2 warns when a field name shadows a deprecated BaseModel method.
# `schema_json` is an intentional DB-column-aligned field name, not a call to
# the legacy BaseModel.schema_json() classmethod.
warnings.filterwarnings(
    "ignore", message='Field name "schema_json" in .* shadows an attribute in parent "BaseModel"'
)


class CreateTemplateVersionFromSourceResponse(BaseModel):
    """Summary returned after promoting a source document into a template version."""

    id: uuid.UUID = Field(description="ID of the newly created template version.")
    contract_template_id: uuid.UUID = Field(description="Parent contract template ID.")
    version_number: int = Field(description="Sequential version number within the template.")
    status: str = Field(description="Initial status (always `draft`).")
    created_at: datetime


class TemplateVersionRead(BaseModel):
    """Full metadata of a template version."""

    model_config = ConfigDict(protected_namespaces=())

    id: uuid.UUID
    contract_template_id: uuid.UUID = Field(description="Parent contract template ID.")
    source_document_id: uuid.UUID | None = Field(
        default=None, description="Source document this version derives from."
    )
    version_number: int = Field(description="Sequential version number.")
    render_engine: str = Field(description="Template engine used for rendering (e.g. `jinja`).")
    schema_json: dict = Field(description="JSON schema describing the template's input fields.")
    computed_rules_json: dict = Field(
        description="Pre-computed conditional rules for section inclusion."
    )
    status: str = Field(
        description="Lifecycle status: `draft`, `review`, `approved`, `deprecated`, or `archived`."
    )
    review_notes: str | None = None
    created_by: uuid.UUID | None = None
    approved_by: uuid.UUID | None = None
    created_at: datetime
    approved_at: datetime | None = None


class UpdateTemplateVersionRequest(BaseModel):
    """Partial update payload for a template version."""

    model_config = ConfigDict(protected_namespaces=())

    review_notes: str | None = Field(default=None, description="Free-text review notes.")
    status: str | None = Field(default=None, description="New lifecycle status.")
    schema_json: dict | None = Field(default=None, description="Replacement input-field schema.")
    computed_rules_json: dict | None = Field(
        default=None, description="Replacement computed rules."
    )


class UpdateTemplateSectionRequest(BaseModel):
    """Partial update payload for a single template section."""

    title: str | None = Field(default=None, description="Section display title.")
    render_template: str | None = Field(
        default=None, description="Jinja template string for this section."
    )
    condition_expression: str | None = Field(
        default=None, description="Boolean expression that gates section inclusion."
    )
    is_optional: bool | None = Field(
        default=None, description="Whether the section can be omitted."
    )
    is_repeatable: bool | None = Field(
        default=None, description="Whether the section can repeat for multiple parties."
    )
    status: str | None = Field(
        default=None, description="Section status: `draft`, `approved`, or `hidden`."
    )
