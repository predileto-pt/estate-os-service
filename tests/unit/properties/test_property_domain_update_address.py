"""Unit tests for `Property.update_address()` — the domain-level address mutator.

Strips surrounding whitespace, rejects empty input, and never bumps
`aggregate_version` (the use case drives that via the repo port).
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from properties.domain.exceptions import PropertyAddressInvalidError
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)


def _property(address: str = "Original Addr") -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=uuid4(),
        organization_id=UUID("00000000-0000-0000-0000-000000000010"),
        address=address,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.DRAFT,
        description=None,
        created_at=now,
        updated_at=now,
    )


def test_update_address_replaces_value():
    prop = _property()
    prop.update_address("Rua Augusta 1, Lisboa")
    assert prop.address == "Rua Augusta 1, Lisboa"


def test_update_address_strips_surrounding_whitespace():
    prop = _property()
    prop.update_address("  Rua Augusta 1  ")
    assert prop.address == "Rua Augusta 1"


def test_update_address_empty_raises():
    prop = _property(address="Original")
    with pytest.raises(PropertyAddressInvalidError):
        prop.update_address("")
    # Failure must not mutate.
    assert prop.address == "Original"


def test_update_address_whitespace_only_raises():
    prop = _property(address="Original")
    with pytest.raises(PropertyAddressInvalidError):
        prop.update_address("   ")
    assert prop.address == "Original"


def test_update_address_does_not_bump_aggregate_version():
    prop = _property()
    before = prop.aggregate_version
    prop.update_address("Rua Nova")
    assert prop.aggregate_version == before


def test_update_address_does_not_change_status():
    prop = _property()
    prop.status = PropertyStatus.ACTIVE
    prop.update_address("Rua Nova")
    assert prop.status == PropertyStatus.ACTIVE
