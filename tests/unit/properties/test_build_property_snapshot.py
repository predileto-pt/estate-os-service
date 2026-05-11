"""Unit test for `properties.application.events.property_event.build_property_snapshot`.

Asserts the payload shape locked in the carried-state spec. Any change
to the shape that breaks a downstream consumer should break this test
first.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from properties.application.events.property_event import (
    build_deletion_payload,
    build_property_snapshot,
)
from properties.domain.models.property import (
    ListingType,
    Property,
    PropertyStatus,
    Typology,
)
from properties.domain.models.property_characteristics import PropertyCharacteristics
from properties.domain.models.property_image import PropertyImage
from properties.domain.models.property_poi import PoiCategory, PropertyPoi
from properties.domain.models.property_price import PropertyPrice


def _base_property() -> Property:
    now = datetime.now(timezone.utc)
    return Property(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        organization_id=UUID("00000000-0000-0000-0000-000000000010"),
        title="Test property",
        address="Rua Augusta 1, Lisboa",
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        status=PropertyStatus.ACTIVE,
        description="Top-floor flat",
        created_at=now,
        updated_at=now,
    )


def test_snapshot_shape_minimal():
    prop = _base_property()
    prop.bump_version()
    payload = build_property_snapshot(prop)

    assert payload["id"] == "00000000-0000-0000-0000-000000000001"
    assert payload["organization_id"] == "00000000-0000-0000-0000-000000000010"
    assert payload["aggregate_version"] == 1
    assert payload["address"] == "Rua Augusta 1, Lisboa"
    assert payload["listing_type"] == "sale"
    assert payload["typology"] == "apartment"
    assert payload["status"] == "active"
    assert payload["description"] == "Top-floor flat"
    assert payload["latitude"] is None
    assert payload["longitude"] is None
    assert payload["characteristics"] is None
    assert payload["prices"] == []
    assert payload["images"] == []


def test_snapshot_with_characteristics_prices_images():
    prop = _base_property()
    prop.characteristics = PropertyCharacteristics(
        area_in_m2=85.5,
        num_of_bedrooms=2,
        num_of_bathrooms=1,
        has_pool=False,
        has_garden=True,
    )
    prop.latitude = 38.7
    prop.longitude = -9.1
    prop.bump_version()

    now = datetime.now(timezone.utc)
    prop.add_price(
        PropertyPrice(
            id=uuid4(),
            property_id=prop.id,
            amount=Decimal("350000.00"),
            listing_type=ListingType.SALE,
            created_at=now,
            updated_at=now,
        )
    )
    img_id = UUID("00000000-0000-0000-0000-000000000aaa")
    prop.add_image(
        PropertyImage(
            id=img_id,
            property_id=prop.id,
            s3_key="photos/x.jpg",
            filename="x.jpg",
            content_type="image/jpeg",
            size_bytes=1024,
            display_order=0,
            created_at=now,
            updated_at=now,
        )
    )

    payload = build_property_snapshot(prop)
    assert payload["latitude"] == 38.7
    assert payload["longitude"] == -9.1
    assert payload["characteristics"]["area_in_m2"] == 85.5
    assert payload["characteristics"]["num_of_bedrooms"] == 2
    assert payload["characteristics"]["has_pool"] is False
    assert payload["characteristics"]["has_garden"] is True
    assert payload["prices"] == [{"amount": "350000.00", "listing_type": "sale"}]
    assert payload["images"] == [
        {
            "id": str(img_id),
            "s3_key": "photos/x.jpg",
            "display_order": 0,
        }
    ]


def test_snapshot_omits_pois_key_when_not_provided():
    """The `pois` arg defaults to None and the key is absent — listings
    projector treats this as 'preserve existing pois'. Backwards-compat
    with every emit site that doesn't pass POIs."""
    prop = _base_property()
    prop.bump_version()
    payload = build_property_snapshot(prop)
    assert "pois" not in payload


def test_snapshot_includes_pois_lean_shape_when_provided():
    """When the caller passes POIs, the snapshot serializes them in the
    rich shape `{category, name, distance_meters, address,
    image_urls, reviews}` consumed by the listings projection.

    Rich fields (ADR-014 §13) — `address`, `image_urls`, `reviews` —
    fall through from `PropertyPoi`. They surface as None/[] when
    the POI's domain instance doesn't carry them. The lean fields
    (the original three) remain in their original positions for
    back-compat with any consumer that doesn't yet read the new keys.
    See `tests/unit/properties/test_property_event_payload.py` for
    the contract."""
    prop = _base_property()
    prop.bump_version()
    now = datetime.now(timezone.utc)
    pois = [
        PropertyPoi(
            id=UUID("00000000-0000-0000-0000-000000000aa1"),
            property_id=prop.id,
            category=PoiCategory.SCHOOL,
            name="Escola Internacional",
            distance_meters=234.0,
            latitude=38.7,
            longitude=-9.1,
            created_at=now,
            updated_at=now,
        ),
        PropertyPoi(
            id=UUID("00000000-0000-0000-0000-000000000aa2"),
            property_id=prop.id,
            category=PoiCategory.GROCERY,
            name="Pingo Doce",
            distance_meters=412.5,
            latitude=38.7,
            longitude=-9.1,
            created_at=now,
            updated_at=now,
        ),
    ]
    payload = build_property_snapshot(prop, pois=pois)
    assert payload["pois"] == [
        {
            "category": "school",
            "name": "Escola Internacional",
            "distance_meters": 234.0,
            "address": None,
            "image_urls": [],
            "reviews": None,
        },
        {
            "category": "grocery",
            "name": "Pingo Doce",
            "distance_meters": 412.5,
            "address": None,
            "image_urls": [],
            "reviews": None,
        },
    ]


def test_snapshot_includes_empty_pois_list_when_explicitly_empty():
    """`pois=[]` is semantically distinct from `pois=None`. Empty list
    means 'authoritative: no POIs'; missing key means 'preserve'."""
    prop = _base_property()
    prop.bump_version()
    payload = build_property_snapshot(prop, pois=[])
    assert payload["pois"] == []


def test_deletion_payload_is_minimal():
    prop = _base_property()
    prop.bump_version()
    prop.bump_version()  # simulate a later version
    payload = build_deletion_payload(prop)
    assert payload == {
        "id": "00000000-0000-0000-0000-000000000001",
        "organization_id": "00000000-0000-0000-0000-000000000010",
        "aggregate_version": 2,
    }
    # Crucially nothing else — no address/status/prices/images.
    assert set(payload.keys()) == {"id", "organization_id", "aggregate_version"}
