"""Unit tests for `build_property_snapshot`'s postal-code extraction.

Spec 2026-05-property-address-enrichment-fix §Postal-code extraction.
"""

from datetime import datetime, timezone
from uuid import uuid4

from properties.application.events.property_event import (
    _extract_postal_code,
    build_property_snapshot,
)
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)


def _prop(address: str) -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=uuid4(),
        organization_id=uuid4(),
        address=address,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.DRAFT,
        description=None,
        characteristics=None,
        latitude=None,
        longitude=None,
        created_at=now,
        updated_at=now,
    )


def test_extract_postal_code_canonical_pt_format():
    assert _extract_postal_code("Av. da Liberdade 12, 1250-147 Lisboa") == "1250-147"


def test_extract_postal_code_at_start():
    assert _extract_postal_code("4000-001 Porto") == "4000-001"


def test_extract_postal_code_at_end():
    assert _extract_postal_code("Rua das Flores 45, Coimbra 3000-100") == "3000-100"


def test_extract_postal_code_returns_none_when_absent():
    assert _extract_postal_code("Rua A, Lisboa") is None


def test_extract_postal_code_rejects_wrong_format():
    # Only 3 digits, only 2 digits after the dash, stuck in long sequences, etc.
    assert _extract_postal_code("12345-67890") is None
    assert _extract_postal_code("1234-12") is None
    assert _extract_postal_code("Rua 12345-678") is None


def test_extract_postal_code_handles_empty_address():
    assert _extract_postal_code("") is None


def test_build_property_snapshot_carries_postal_code():
    prop = _prop("Av. da Liberdade 12, 1250-147 Lisboa")
    payload = build_property_snapshot(prop)
    assert payload["postal_code"] == "1250-147"
    assert payload["address"] == "Av. da Liberdade 12, 1250-147 Lisboa"


def test_build_property_snapshot_postal_code_null_when_absent():
    prop = _prop("Rua A, Lisboa")
    payload = build_property_snapshot(prop)
    assert payload["postal_code"] is None
