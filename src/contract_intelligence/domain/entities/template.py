from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from contract_intelligence.domain.exceptions import InvalidStatusTransitionError


class TemplateStatus(StrEnum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class SectionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    HIDDEN = "hidden"


_TEMPLATE_TRANSITIONS: dict[TemplateStatus, set[TemplateStatus]] = {
    TemplateStatus.DRAFT: {TemplateStatus.REVIEW},
    TemplateStatus.REVIEW: {TemplateStatus.APPROVED, TemplateStatus.DRAFT},
    TemplateStatus.APPROVED: {TemplateStatus.DEPRECATED},
    TemplateStatus.DEPRECATED: {TemplateStatus.ARCHIVED},
    TemplateStatus.ARCHIVED: set(),
}

_SECTION_TRANSITIONS: dict[SectionStatus, set[SectionStatus]] = {
    SectionStatus.DRAFT: {SectionStatus.APPROVED, SectionStatus.HIDDEN},
    SectionStatus.APPROVED: {SectionStatus.DRAFT, SectionStatus.HIDDEN},
    SectionStatus.HIDDEN: {SectionStatus.DRAFT},
}


def _validate_transition(current: Any, target: Any, transitions: dict, entity_name: str) -> None:
    allowed = transitions.get(current, set())
    if target not in allowed:
        raise InvalidStatusTransitionError(
            f"{entity_name} cannot transition from {current} to {target}"
        )


@dataclass
class TemplateSection:
    template_version_id: UUID
    section_key: str
    title: str
    section_type: str
    sort_order: int
    render_template: str
    id: UUID = field(default_factory=uuid4)
    is_repeatable: bool = False
    is_optional: bool = False
    condition_expression: str | None = None
    source_text_snapshot: str | None = None
    status: SectionStatus = SectionStatus.DRAFT
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def approve(self) -> None:
        _validate_transition(
            self.status, SectionStatus.APPROVED, _SECTION_TRANSITIONS, "TemplateSection"
        )
        self.status = SectionStatus.APPROVED

    def hide(self) -> None:
        _validate_transition(
            self.status, SectionStatus.HIDDEN, _SECTION_TRANSITIONS, "TemplateSection"
        )
        self.status = SectionStatus.HIDDEN

    def revert_to_draft(self) -> None:
        _validate_transition(
            self.status, SectionStatus.DRAFT, _SECTION_TRANSITIONS, "TemplateSection"
        )
        self.status = SectionStatus.DRAFT


@dataclass
class TemplateFieldBinding:
    template_version_id: UUID
    field_key: str
    binding_type: str
    id: UUID = field(default_factory=uuid4)
    template_section_id: UUID | None = None
    required: bool = False
    placeholder_label: str | None = None
    description: str | None = None
    default_value_json: Any = None
    validation_rules_json: dict | None = None
    source_hint: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class TemplateCondition:
    template_version_id: UUID
    condition_key: str
    expression: str
    id: UUID = field(default_factory=uuid4)
    template_section_id: UUID | None = None
    description: str | None = None
    created_at: datetime | None = None


@dataclass
class TemplatePartySlot:
    template_version_id: UUID
    role_key: str
    display_label_singular: str
    display_label_plural: str
    id: UUID = field(default_factory=uuid4)
    min_count: int = 0
    max_count: int = 1
    alias_singular: str | None = None
    alias_plural: str | None = None
    section_intro_label: str | None = None
    sort_order: int = 0
    is_required: bool = False
    created_at: datetime | None = None


@dataclass
class TemplateVersion:
    contract_template_id: UUID
    version_number: int
    schema_json: dict
    id: UUID = field(default_factory=uuid4)
    source_document_id: UUID | None = None
    render_engine: str = "jinja"
    computed_rules_json: dict = field(default_factory=dict)
    status: TemplateStatus = TemplateStatus.DRAFT
    review_notes: str | None = None
    created_by: UUID | None = None
    approved_by: UUID | None = None
    created_at: datetime | None = None
    approved_at: datetime | None = None
    sections: list[TemplateSection] = field(default_factory=list)
    field_bindings: list[TemplateFieldBinding] = field(default_factory=list)
    conditions: list[TemplateCondition] = field(default_factory=list)
    party_slots: list[TemplatePartySlot] = field(default_factory=list)

    def submit_for_review(self) -> None:
        _validate_transition(
            self.status, TemplateStatus.REVIEW, _TEMPLATE_TRANSITIONS, "TemplateVersion"
        )
        self.status = TemplateStatus.REVIEW

    def approve(self, approved_by: UUID, approved_at: datetime) -> None:
        _validate_transition(
            self.status, TemplateStatus.APPROVED, _TEMPLATE_TRANSITIONS, "TemplateVersion"
        )
        self.status = TemplateStatus.APPROVED
        self.approved_by = approved_by
        self.approved_at = approved_at

    def reject_to_draft(self) -> None:
        _validate_transition(
            self.status, TemplateStatus.DRAFT, _TEMPLATE_TRANSITIONS, "TemplateVersion"
        )
        self.status = TemplateStatus.DRAFT

    def deprecate(self) -> None:
        _validate_transition(
            self.status, TemplateStatus.DEPRECATED, _TEMPLATE_TRANSITIONS, "TemplateVersion"
        )
        self.status = TemplateStatus.DEPRECATED

    def archive(self) -> None:
        _validate_transition(
            self.status, TemplateStatus.ARCHIVED, _TEMPLATE_TRANSITIONS, "TemplateVersion"
        )
        self.status = TemplateStatus.ARCHIVED


@dataclass
class ContractTemplate:
    key: str
    name: str
    contract_type: str
    jurisdiction: str
    language_code: str
    id: UUID = field(default_factory=uuid4)
    status: TemplateStatus = TemplateStatus.DRAFT
    current_version_id: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    versions: list[TemplateVersion] = field(default_factory=list)

    def submit_for_review(self) -> None:
        _validate_transition(
            self.status, TemplateStatus.REVIEW, _TEMPLATE_TRANSITIONS, "ContractTemplate"
        )
        self.status = TemplateStatus.REVIEW

    def approve(self) -> None:
        _validate_transition(
            self.status, TemplateStatus.APPROVED, _TEMPLATE_TRANSITIONS, "ContractTemplate"
        )
        self.status = TemplateStatus.APPROVED

    def deprecate(self) -> None:
        _validate_transition(
            self.status, TemplateStatus.DEPRECATED, _TEMPLATE_TRANSITIONS, "ContractTemplate"
        )
        self.status = TemplateStatus.DEPRECATED

    def archive(self) -> None:
        _validate_transition(
            self.status, TemplateStatus.ARCHIVED, _TEMPLATE_TRANSITIONS, "ContractTemplate"
        )
        self.status = TemplateStatus.ARCHIVED
