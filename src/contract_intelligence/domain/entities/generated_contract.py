from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from contract_intelligence.domain.exceptions import InvalidStatusTransitionError


class GeneratedContractStatus(StrEnum):
    DRAFT = "draft"
    GENERATED = "generated"
    REVIEWED = "reviewed"
    SIGNED = "signed"
    ARCHIVED = "archived"


_CONTRACT_TRANSITIONS: dict[GeneratedContractStatus, set[GeneratedContractStatus]] = {
    GeneratedContractStatus.DRAFT: {GeneratedContractStatus.GENERATED},
    GeneratedContractStatus.GENERATED: {
        GeneratedContractStatus.REVIEWED,
        GeneratedContractStatus.ARCHIVED,
    },
    GeneratedContractStatus.REVIEWED: {
        GeneratedContractStatus.SIGNED,
        GeneratedContractStatus.ARCHIVED,
    },
    GeneratedContractStatus.SIGNED: {GeneratedContractStatus.ARCHIVED},
    GeneratedContractStatus.ARCHIVED: set(),
}


def _validate_transition(current: Any, target: Any, transitions: dict, entity_name: str) -> None:
    allowed = transitions.get(current, set())
    if target not in allowed:
        raise InvalidStatusTransitionError(
            f"{entity_name} cannot transition from {current} to {target}"
        )


@dataclass
class GeneratedContractParty:
    generated_contract_id: UUID
    role_key: str
    party_order: int
    full_name: str
    id: UUID = field(default_factory=uuid4)
    party_type: str = "individual"
    tax_id: str | None = None
    document_type: str | None = None
    document_number: str | None = None
    document_expiry: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country_code: str | None = None
    source_ref: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class GeneratedContractSection:
    generated_contract_id: UUID
    section_key: str
    sort_order: int
    rendered_text: str
    id: UUID = field(default_factory=uuid4)
    template_section_id: UUID | None = None
    render_state: str = "rendered"
    skip_reason: str | None = None
    created_at: datetime | None = None


@dataclass
class GeneratedContractArtifact:
    generated_contract_id: UUID
    artifact_type: str
    storage_url: str
    id: UUID = field(default_factory=uuid4)
    checksum: str | None = None
    created_at: datetime | None = None


@dataclass
class GeneratedContract:
    contract_template_id: UUID
    template_version_id: UUID
    input_payload_json: dict
    rendered_schema_json: dict
    id: UUID = field(default_factory=uuid4)
    organization_id: UUID | None = None
    crm_contact_id: str | None = None
    crm_property_id: str | None = None
    status: GeneratedContractStatus = GeneratedContractStatus.DRAFT
    created_at: datetime | None = None
    updated_at: datetime | None = None
    parties: list[GeneratedContractParty] = field(default_factory=list)
    sections: list[GeneratedContractSection] = field(default_factory=list)
    artifacts: list[GeneratedContractArtifact] = field(default_factory=list)

    def mark_generated(self) -> None:
        _validate_transition(
            self.status,
            GeneratedContractStatus.GENERATED,
            _CONTRACT_TRANSITIONS,
            "GeneratedContract",
        )
        self.status = GeneratedContractStatus.GENERATED

    def mark_reviewed(self) -> None:
        _validate_transition(
            self.status,
            GeneratedContractStatus.REVIEWED,
            _CONTRACT_TRANSITIONS,
            "GeneratedContract",
        )
        self.status = GeneratedContractStatus.REVIEWED

    def mark_signed(self) -> None:
        _validate_transition(
            self.status, GeneratedContractStatus.SIGNED, _CONTRACT_TRANSITIONS, "GeneratedContract"
        )
        self.status = GeneratedContractStatus.SIGNED

    def archive(self) -> None:
        _validate_transition(
            self.status,
            GeneratedContractStatus.ARCHIVED,
            _CONTRACT_TRANSITIONS,
            "GeneratedContract",
        )
        self.status = GeneratedContractStatus.ARCHIVED
