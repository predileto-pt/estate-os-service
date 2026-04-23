"""Unit tests for `Property.publish()` — the domain-level state transition.

The method flips DRAFT or WITHDRAWN to ACTIVE when the aggregate is
complete, otherwise raises `PropertyNotPublishableError` with a list
of machine-readable reason codes. It does NOT bump `aggregate_version`
— that's driven by the use case via the repo port, matching every
other update-style use case in this context.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from properties.domain.exceptions import PropertyNotPublishableError
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_image import PropertyImage
from properties.domain.models.property_owner import PropertyOwner
from properties.domain.models.property_price import PropertyPrice


def _complete_property(status: PropertyStatus = PropertyStatus.DRAFT) -> Property:
    """A property that satisfies every publishability precondition."""
    now = datetime.now(timezone.utc)
    pid = uuid4()
    prop = Property(
        id=pid,
        organization_id=UUID("00000000-0000-0000-0000-000000000010"),
        address="Rua Augusta 1, Lisboa",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=status,
        description=None,
        created_at=now,
        updated_at=now,
    )
    prop.add_owner(
        PropertyOwner(
            id=uuid4(),
            property_id=pid,
            full_name="Maria Silva",
            civil_status=None,
            address="Rua Augusta 1",
            nif="123456789",
            document_type=None,
            document_id=None,
            issued_by=None,
            issuing_district=None,
            date_of_birth=None,
            created_at=now,
            updated_at=now,
        )
    )
    prop.add_price(
        PropertyPrice(
            id=uuid4(),
            property_id=pid,
            amount=Decimal("350000.00"),
            listing_type=ListingType.SALE,
            created_at=now,
            updated_at=now,
        )
    )
    prop.add_image(
        PropertyImage(
            id=uuid4(),
            property_id=pid,
            s3_key="photos/x.jpg",
            filename="x.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            display_order=0,
            created_at=now,
            updated_at=now,
        )
    )
    return prop


def test_publish_from_draft_flips_status_to_active():
    prop = _complete_property(status=PropertyStatus.DRAFT)
    prop.publish()
    assert prop.status == PropertyStatus.ACTIVE


def test_publish_from_withdrawn_flips_status_to_active():
    prop = _complete_property(status=PropertyStatus.WITHDRAWN)
    prop.publish()
    assert prop.status == PropertyStatus.ACTIVE


def test_publish_does_not_bump_aggregate_version():
    prop = _complete_property()
    before = prop.aggregate_version
    prop.publish()
    assert prop.aggregate_version == before


def test_publish_from_active_raises_with_status_reason():
    prop = _complete_property(status=PropertyStatus.ACTIVE)
    with pytest.raises(PropertyNotPublishableError) as exc:
        prop.publish()
    assert exc.value.reasons == ["cannot_publish_from_status:active"]


def test_publish_from_sold_raises_with_status_reason():
    prop = _complete_property(status=PropertyStatus.SOLD)
    with pytest.raises(PropertyNotPublishableError) as exc:
        prop.publish()
    assert exc.value.reasons == ["cannot_publish_from_status:sold"]


def test_publish_from_rented_raises_with_status_reason():
    prop = _complete_property(status=PropertyStatus.RENTED)
    with pytest.raises(PropertyNotPublishableError) as exc:
        prop.publish()
    assert exc.value.reasons == ["cannot_publish_from_status:rented"]


def test_missing_address_raises():
    prop = _complete_property()
    prop.address = "   "
    with pytest.raises(PropertyNotPublishableError) as exc:
        prop.publish()
    assert "missing_address" in exc.value.reasons


def test_missing_price_raises():
    prop = _complete_property()
    prop.prices = []
    with pytest.raises(PropertyNotPublishableError) as exc:
        prop.publish()
    assert "missing_price" in exc.value.reasons


def test_missing_owner_raises():
    prop = _complete_property()
    prop.owners = []
    with pytest.raises(PropertyNotPublishableError) as exc:
        prop.publish()
    assert "missing_owner" in exc.value.reasons


def test_missing_image_raises():
    prop = _complete_property()
    prop.images = []
    with pytest.raises(PropertyNotPublishableError) as exc:
        prop.publish()
    assert "missing_image" in exc.value.reasons


def test_multiple_gaps_accumulate_in_reasons():
    prop = _complete_property()
    prop.prices = []
    prop.owners = []
    prop.images = []
    with pytest.raises(PropertyNotPublishableError) as exc:
        prop.publish()
    assert set(exc.value.reasons) == {"missing_price", "missing_owner", "missing_image"}


def test_failure_does_not_mutate_status():
    prop = _complete_property()
    prop.images = []
    with pytest.raises(PropertyNotPublishableError):
        prop.publish()
    assert prop.status == PropertyStatus.DRAFT
