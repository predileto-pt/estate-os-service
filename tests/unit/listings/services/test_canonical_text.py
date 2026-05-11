"""Golden tests for `compose_canonical_text` (LISTING_CANONICAL_TEXT_V3).

Hash stability is load-bearing: the embedding handler skips re-embedding
when (hash, version, model) matches the persisted tuple, so any drift
in rendering would burn embed calls on every event. These tests pin
the rendering byte-for-byte and the hash against fixed inputs.

ADR-014 §9 — sectional layout aligned with the query extractor's
`_render_query_for_embed` (TYPOLOGY/CHARACTERISTICS/FEATURES/NEARBY/
DESCRIPTION/LOCATION/PRICE), raw `PoiCategory.value` strings on the
NEARBY line, distance rounded to 100m as `<category>@<rounded>m`.
"""

from __future__ import annotations

import random
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from listings.application.services.canonical_text import (
    CANONICAL_TEXT_VERSION,
    compose_canonical_text,
)
from listings.domain.models import ListingType, PropertyStatus, Typology
from listings.domain.property_listing import ListingPoi, PropertyListing


def _now() -> datetime:
    return datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc)


def _listing(**overrides) -> PropertyListing:
    """Build a PropertyListing with sensible defaults; override by name."""
    base = dict(
        id=UUID("00000000-0000-0000-0000-000000000001"),
        organization_id=UUID("00000000-0000-0000-0000-000000000010"),
        title="Test property",
        status=PropertyStatus.ACTIVE,
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        parish="Santa Maria Maior",
        municipality="Lisboa",
        district="Lisboa",
        location_enriched_at=_now(),
        location_enrichment_attempts=1,
        num_of_bedrooms=2,
        num_of_bathrooms=1,
        area_in_m2=85,
        has_pool=False,
        has_garden=True,
        has_elevator=True,
        parking_spaces=0,
        min_price=Decimal("350000.00"),
        first_image_s3_key="photos/x.jpg",
        description="Top-floor flat with river views.",
        latitude=38.7,
        longitude=-9.1,
        source_aggregate_version=1,
        source_occurred_at=_now(),
        created_at=_now(),
        updated_at=_now(),
        built_at=2018,
        energy_rating="A",
        pois=[],
        embedding_text_hash=None,
        canonical_text_version=None,
        embedding_model_version=None,
        embedded_at=None,
        embedding_status="PENDING",
    )
    base.update(overrides)
    return PropertyListing(**base)


def test_version_constant():
    assert CANONICAL_TEXT_VERSION == "v3"


def test_full_listing_renders_all_sections():
    """v3 layout: TYPOLOGY → CHARACTERISTICS → FEATURES → NEARBY →
    DESCRIPTION → LOCATION → PRICE. Aligned with the query
    extractor's sectional render so cosine compares like-with-like."""
    listing = _listing(
        pois=[
            ListingPoi(category="school", name="Escola Internacional", distance_meters=234.0),
            ListingPoi(category="grocery", name="Pingo Doce", distance_meters=412.5),
        ]
    )
    out = compose_canonical_text(listing)
    expected = (
        "TYPOLOGY: apartment\n"
        "CHARACTERISTICS: T2, 85m², 1 casas de banho\n"
        "FEATURES: jardim, elevador\n"
        "NEARBY: school@200m, grocery@400m\n"
        "DESCRIPTION: Top-floor flat with river views.\n"
        "LOCATION: Santa Maria Maior, Lisboa, Lisboa\n"
        "PRICE: 350000 EUR"
    )
    assert out.text == expected
    assert out.version == "v3"


def test_hash_is_sha256_of_text():
    import hashlib

    listing = _listing(pois=[])
    out = compose_canonical_text(listing)
    assert out.hash == hashlib.sha256(out.text.encode("utf-8")).hexdigest()


def test_hash_stable_across_invocations():
    """Determinism — same input twice = same hash byte-for-byte."""
    pois = [
        ListingPoi(category="school", name="X", distance_meters=300.0),
        ListingPoi(category="gym", name="Y", distance_meters=500.0),
    ]
    a = compose_canonical_text(_listing(pois=pois))
    b = compose_canonical_text(_listing(pois=pois))
    assert a.hash == b.hash
    assert a.text == b.text


def test_no_trailing_newline():
    listing = _listing()
    out = compose_canonical_text(listing)
    assert not out.text.endswith("\n")


def test_whitespace_collapsed_in_values():
    listing = _listing(description="  Multi   space   description  ")
    out = compose_canonical_text(listing)
    assert "DESCRIPTION: Multi space description" in out.text


# ──────────── TYPOLOGY ────────────


def test_typology_uses_lowercase_enum_value():
    """v3 uses `.value` directly, matching the query extractor's
    `_render_query_for_embed`. v2 used `.value.upper()` — that
    no longer holds."""
    out = compose_canonical_text(_listing(typology=Typology.HOUSE))
    assert "TYPOLOGY: house" in out.text


def test_typology_apartment():
    out = compose_canonical_text(_listing(typology=Typology.APARTMENT))
    assert "TYPOLOGY: apartment" in out.text


# ──────────── CHARACTERISTICS ────────────


def test_characteristics_all_three_fields():
    out = compose_canonical_text(
        _listing(num_of_bedrooms=3, num_of_bathrooms=2, area_in_m2=120)
    )
    assert "CHARACTERISTICS: T3, 120m², 2 casas de banho" in out.text


def test_characteristics_only_bedrooms():
    out = compose_canonical_text(
        _listing(num_of_bedrooms=2, num_of_bathrooms=None, area_in_m2=None)
    )
    assert "CHARACTERISTICS: T2\n" in out.text or "CHARACTERISTICS: T2" == out.text.split("\n")[1]


def test_characteristics_all_null_omits_line():
    out = compose_canonical_text(
        _listing(num_of_bedrooms=None, num_of_bathrooms=None, area_in_m2=None)
    )
    assert "CHARACTERISTICS:" not in out.text


def test_characteristics_only_area():
    out = compose_canonical_text(
        _listing(num_of_bedrooms=None, num_of_bathrooms=None, area_in_m2=100)
    )
    assert "CHARACTERISTICS: 100m²" in out.text


# ──────────── FEATURES ────────────


def test_features_renders_only_true_amenities():
    out = compose_canonical_text(
        _listing(has_pool=True, has_garden=False, has_elevator=True, parking_spaces=0)
    )
    assert "FEATURES: piscina, elevador" in out.text


def test_features_garagem_from_parking_spaces():
    """has_parking is derived: parking_spaces > 0 → 'garagem'."""
    out = compose_canonical_text(
        _listing(
            has_pool=False, has_garden=False, has_elevator=False, parking_spaces=2
        )
    )
    assert "FEATURES: garagem" in out.text


def test_features_zero_parking_spaces_omits_garagem():
    out = compose_canonical_text(
        _listing(
            has_pool=True, has_garden=False, has_elevator=False, parking_spaces=0
        )
    )
    assert "FEATURES: piscina" in out.text
    assert "garagem" not in out.text


def test_features_null_parking_omits_garagem():
    out = compose_canonical_text(
        _listing(
            has_pool=True, has_garden=False, has_elevator=False, parking_spaces=None
        )
    )
    assert "garagem" not in out.text


def test_features_all_omitted_when_no_amenities():
    out = compose_canonical_text(
        _listing(
            has_pool=False, has_garden=False, has_elevator=False, parking_spaces=0
        )
    )
    assert "FEATURES:" not in out.text


def test_features_all_null_omitted():
    out = compose_canonical_text(
        _listing(
            has_pool=None, has_garden=None, has_elevator=None, parking_spaces=None
        )
    )
    assert "FEATURES:" not in out.text


def test_features_full_set():
    out = compose_canonical_text(
        _listing(has_pool=True, has_garden=True, has_elevator=True, parking_spaces=1)
    )
    # Order is locked: piscina, jardim, elevador, garagem.
    assert "FEATURES: piscina, jardim, elevador, garagem" in out.text


# ──────────── NEARBY ────────────


def test_nearby_uses_raw_category_value_not_pt():
    """v3 uses `PoiCategory.value` strings (closed vocab) — same as
    the extractor. v2 used PT translations; that no longer holds."""
    out = compose_canonical_text(
        _listing(
            pois=[
                ListingPoi(category="school", name="X", distance_meters=300.0),
            ]
        )
    )
    assert "NEARBY: school@300m" in out.text
    # Confirm the v2 PT translation is GONE.
    assert "escola" not in out.text


def test_nearby_sorted_by_distance_ascending():
    out = compose_canonical_text(
        _listing(
            pois=[
                ListingPoi(category="school", name="A", distance_meters=1500.0),
                ListingPoi(category="gym", name="B", distance_meters=200.0),
                ListingPoi(category="grocery", name="C", distance_meters=800.0),
            ]
        )
    )
    nearby_line = [line for line in out.text.split("\n") if line.startswith("NEARBY:")][0]
    # Ascending: gym@200m, grocery@800m, school@1500m
    assert nearby_line == "NEARBY: gym@200m, grocery@800m, school@1500m"


def test_nearby_distance_rounded_to_100m():
    out = compose_canonical_text(
        _listing(
            pois=[
                ListingPoi(category="school", name="X", distance_meters=234.0),
                ListingPoi(category="gym", name="Y", distance_meters=476.0),
            ]
        )
    )
    # 234 → 200, 476 → 500.
    assert "school@200m" in out.text
    assert "gym@500m" in out.text


def test_nearby_jitter_below_100m_does_not_change_hash():
    """Same physical POI distances within ±50m round to the same
    100m bucket → identical hash."""
    a = compose_canonical_text(
        _listing(pois=[ListingPoi(category="school", name="X", distance_meters=230.0)])
    )
    b = compose_canonical_text(
        _listing(pois=[ListingPoi(category="school", name="X", distance_meters=249.0)])
    )
    assert a.hash == b.hash


def test_nearby_beyond_distance_cap_filtered(monkeypatch):
    monkeypatch.setenv("LISTING_POI_MAX_DISTANCE_M", "1000")
    out = compose_canonical_text(
        _listing(
            pois=[
                ListingPoi(category="school", name="Close", distance_meters=500.0),
                ListingPoi(category="gym", name="Far", distance_meters=2000.0),
            ]
        )
    )
    assert "school@500m" in out.text
    assert "Far" not in out.text


def test_nearby_capped_at_max_count(monkeypatch):
    monkeypatch.setenv("LISTING_POI_MAX_COUNT", "2")
    out = compose_canonical_text(
        _listing(
            pois=[
                ListingPoi(category=f"c{i}", name=f"P{i}", distance_meters=100.0 * i)
                for i in range(1, 6)
            ]
        )
    )
    # Only the closest 2 surface.
    nearby_line = [line for line in out.text.split("\n") if line.startswith("NEARBY:")][0]
    assert nearby_line.count(",") == 1  # 2 entries → 1 comma


def test_nearby_empty_omits_line():
    out = compose_canonical_text(_listing(pois=[]))
    assert "NEARBY:" not in out.text


def test_nearby_deterministic_across_input_permutations():
    pois_a = [
        ListingPoi(category="school", name="A", distance_meters=200.0),
        ListingPoi(category="gym", name="B", distance_meters=500.0),
        ListingPoi(category="grocery", name="C", distance_meters=300.0),
    ]
    pois_b = list(pois_a)
    random.shuffle(pois_b)
    a = compose_canonical_text(_listing(pois=pois_a))
    b = compose_canonical_text(_listing(pois=pois_b))
    assert a.hash == b.hash


# ──────────── DESCRIPTION ────────────


def test_description_truncated(monkeypatch):
    monkeypatch.setenv("LISTING_DESCRIPTION_MAX_CHARS", "20")
    out = compose_canonical_text(_listing(description="a" * 100))
    desc_line = [line for line in out.text.split("\n") if line.startswith("DESCRIPTION:")][0]
    assert desc_line == "DESCRIPTION: " + "a" * 20


def test_description_omitted_when_null():
    out = compose_canonical_text(_listing(description=None))
    assert "DESCRIPTION:" not in out.text


# ──────────── LOCATION ────────────


def test_location_all_three_levels():
    out = compose_canonical_text(
        _listing(parish="Santa Maria Maior", municipality="Lisboa", district="Lisboa")
    )
    assert "LOCATION: Santa Maria Maior, Lisboa, Lisboa" in out.text


def test_location_only_municipality():
    out = compose_canonical_text(_listing(parish=None, municipality="Lisboa", district=None))
    assert "LOCATION: Lisboa" in out.text


def test_location_all_null_omits_line():
    out = compose_canonical_text(_listing(parish=None, municipality=None, district=None))
    assert "LOCATION:" not in out.text


# ──────────── PRICE ────────────


def test_price_renders_as_whole_eur_integer():
    out = compose_canonical_text(_listing(min_price=Decimal("450000.55")))
    # Integer EUR — hash stability over cents.
    assert "PRICE: 450000 EUR" in out.text


def test_price_omitted_when_null():
    out = compose_canonical_text(_listing(min_price=None))
    assert "PRICE:" not in out.text


# ──────────── Layout order ────────────


def test_section_order_is_locked():
    """v3 order: TYPOLOGY → CHARACTERISTICS → FEATURES → NEARBY →
    DESCRIPTION → LOCATION → PRICE. Any reordering invalidates the
    hash and demands a V4 bump."""
    out = compose_canonical_text(
        _listing(
            pois=[ListingPoi(category="school", name="X", distance_meters=100.0)],
            has_pool=True,
        )
    )
    lines = [line.split(":", 1)[0] for line in out.text.split("\n")]
    expected_order = [
        "TYPOLOGY",
        "CHARACTERISTICS",
        "FEATURES",
        "NEARBY",
        "DESCRIPTION",
        "LOCATION",
        "PRICE",
    ]
    assert lines == expected_order
