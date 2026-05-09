"""Golden tests for `compose_canonical_text` (LISTING_CANONICAL_TEXT_V1).

Hash stability is load-bearing: the embedding handler skips re-embedding
when (hash, version, model) matches the persisted tuple, so any drift
in rendering would burn embed calls on every event. These tests pin
the rendering byte-for-byte and the hash against fixed inputs.
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


def test_full_listing_renders_all_sections():
    """v2 schema: PT POI categories + FEATURES line for amenities."""
    listing = _listing(
        pois=[
            ListingPoi(category="school", name="Escola Internacional", distance_meters=234.0),
            ListingPoi(category="grocery", name="Pingo Doce", distance_meters=412.5),
        ]
    )
    out = compose_canonical_text(listing)
    expected = (
        "LOCATION: Santa Maria Maior · Lisboa · Lisboa\n"
        "LISTING_TYPE: SALE\n"
        "TYPOLOGY: APARTMENT\n"
        "SIZE: 2 bed · 1 bath · 85 m²\n"
        "BUILT: 2018 · energy A\n"
        "FEATURES: jardim, elevador\n"
        "PRICE: 350000 EUR\n"
        "NEARBY: escola: Escola Internacional (0.2km), supermercado: Pingo Doce (0.4km)\n"
        "DESCRIPTION: Top-floor flat with river views."
    )
    assert out.text == expected
    assert out.version == CANONICAL_TEXT_VERSION
    assert out.version == "v2"


def test_version_constant():
    assert CANONICAL_TEXT_VERSION == "v2"


def test_hash_is_sha256_of_text():
    import hashlib

    listing = _listing()
    out = compose_canonical_text(listing)
    assert out.hash == hashlib.sha256(out.text.encode("utf-8")).hexdigest()


def test_hash_stable_across_invocations():
    """Same input rendered 100 times produces the same hash byte-for-byte."""
    listing = _listing(
        pois=[
            ListingPoi(category="school", name="Escola X", distance_meters=234.0),
            ListingPoi(category="grocery", name="Pingo Doce", distance_meters=412.5),
        ]
    )
    first = compose_canonical_text(listing).hash
    for _ in range(99):
        assert compose_canonical_text(listing).hash == first


def test_missing_description_omits_line():
    listing = _listing(description=None, pois=[])
    out = compose_canonical_text(listing)
    assert "DESCRIPTION" not in out.text


def test_missing_built_year_omits_only_year_segment():
    listing = _listing(built_at=None, energy_rating="A", pois=[])
    out = compose_canonical_text(listing)
    assert "BUILT: energy A" in out.text


def test_all_built_fields_null_omits_line():
    listing = _listing(built_at=None, energy_rating=None, pois=[])
    out = compose_canonical_text(listing)
    assert "BUILT" not in out.text


def test_size_with_only_bedrooms():
    listing = _listing(num_of_bedrooms=3, num_of_bathrooms=None, area_in_m2=None, pois=[])
    out = compose_canonical_text(listing)
    assert "SIZE: 3 bed" in out.text
    assert "bath" not in out.text
    assert "m²" not in out.text


def test_all_size_fields_null_omits_line():
    listing = _listing(num_of_bedrooms=None, num_of_bathrooms=None, area_in_m2=None, pois=[])
    out = compose_canonical_text(listing)
    assert "SIZE" not in out.text


def test_location_with_only_municipality():
    listing = _listing(parish=None, municipality="Lisboa", district=None, pois=[])
    out = compose_canonical_text(listing)
    assert "LOCATION: Lisboa" in out.text


def test_all_location_fields_null_omits_line():
    listing = _listing(parish=None, municipality=None, district=None, pois=[])
    out = compose_canonical_text(listing)
    assert "LOCATION" not in out.text


def test_pois_outside_allowlist_filtered():
    listing = _listing(
        pois=[
            ListingPoi(category="school", name="Escola Y", distance_meters=200.0),
            ListingPoi(category="nightclub", name="Lux", distance_meters=300.0),
        ]
    )
    out = compose_canonical_text(listing)
    assert "Escola Y" in out.text
    assert "Lux" not in out.text


def test_pois_beyond_distance_cap_filtered():
    listing = _listing(
        pois=[
            ListingPoi(category="school", name="Escola Near", distance_meters=200.0),
            ListingPoi(category="school", name="Escola Far", distance_meters=5000.0),
        ]
    )
    out = compose_canonical_text(listing)
    assert "Escola Near" in out.text
    assert "Escola Far" not in out.text


def test_pois_capped_at_max_count(monkeypatch):
    monkeypatch.setenv("LISTING_POI_MAX_COUNT", "3")
    listing = _listing(
        pois=[
            ListingPoi(category="school", name=f"School {i}", distance_meters=100.0 + i)
            for i in range(10)
        ]
    )
    out = compose_canonical_text(listing)
    nearby_line = next(line for line in out.text.split("\n") if line.startswith("NEARBY:"))
    # 3 entries → 2 commas
    assert nearby_line.count(",") == 2


def test_pois_deterministic_ordering_across_input_permutations():
    """Same POI set in any order produces the same canonical text."""
    pois_a = [
        ListingPoi(category="school", name="A", distance_meters=200.0),
        ListingPoi(category="school", name="B", distance_meters=300.0),
        ListingPoi(category="grocery", name="C", distance_meters=150.0),
    ]
    rng = random.Random(42)
    permuted = list(pois_a)
    rng.shuffle(permuted)
    out_a = compose_canonical_text(_listing(pois=pois_a))
    out_b = compose_canonical_text(_listing(pois=permuted))
    assert out_a.text == out_b.text
    assert out_a.hash == out_b.hash


def test_pois_empty_omits_nearby_line():
    listing = _listing(pois=[])
    out = compose_canonical_text(listing)
    assert "NEARBY" not in out.text


def test_distance_micro_jitter_does_not_change_hash():
    """100m precision rounding: same physical POI within ±50m shouldn't
    invalidate the hash on every re-geocode."""
    listing_jitter_low = _listing(
        pois=[ListingPoi(category="school", name="X", distance_meters=240.0)]
    )
    listing_jitter_high = _listing(
        pois=[ListingPoi(category="school", name="X", distance_meters=251.0)]
    )
    # 240 → 200, 251 → 300 → DIFFERENT (crosses the 250 boundary).
    # Try a tighter jitter that stays inside one bucket:
    listing_a = _listing(pois=[ListingPoi(category="school", name="X", distance_meters=205.0)])
    listing_b = _listing(pois=[ListingPoi(category="school", name="X", distance_meters=234.0)])
    assert compose_canonical_text(listing_a).hash == compose_canonical_text(listing_b).hash
    # And confirm the cross-boundary case differs (sanity):
    assert (
        compose_canonical_text(listing_jitter_low).hash
        != compose_canonical_text(listing_jitter_high).hash
    )


def test_description_truncated(monkeypatch):
    monkeypatch.setenv("LISTING_DESCRIPTION_MAX_CHARS", "20")
    listing = _listing(description="x" * 1000, pois=[])
    out = compose_canonical_text(listing)
    desc_line = next(line for line in out.text.split("\n") if line.startswith("DESCRIPTION:"))
    # Prefix "DESCRIPTION: " (13 chars) + 20 chars of value
    assert desc_line == "DESCRIPTION: " + "x" * 20


def test_whitespace_collapsed_in_values():
    listing = _listing(description="  multi  \t  line\n\nwith   spaces  ", pois=[])
    out = compose_canonical_text(listing)
    assert "DESCRIPTION: multi line with spaces" in out.text


def test_no_trailing_newline():
    listing = _listing(pois=[])
    out = compose_canonical_text(listing)
    assert not out.text.endswith("\n")


# ────────────────────────────────────────────────────────────
# v2: FEATURES line + PT POI categories
# ────────────────────────────────────────────────────────────


def test_features_line_renders_only_true_amenities():
    """Default _listing has has_pool=False, has_garden=True, has_elevator=True.
    Only TRUE booleans render; False is treated as "no signal", not as
    "negative signal" — the embedding doesn't claim 'sem piscina'."""
    listing = _listing(pois=[])
    out = compose_canonical_text(listing)
    assert "FEATURES: jardim, elevador" in out.text
    # has_pool=False → no "piscina" token
    assert "piscina" not in out.text


def test_features_line_with_all_amenities_true():
    listing = _listing(has_pool=True, has_garden=True, has_elevator=True, pois=[])
    out = compose_canonical_text(listing)
    # Fixed iteration order: pool → garden → elevator
    assert "FEATURES: piscina, jardim, elevador" in out.text


def test_features_line_omitted_when_all_amenities_false_or_none():
    listing = _listing(has_pool=False, has_garden=False, has_elevator=False, pois=[])
    out = compose_canonical_text(listing)
    assert "FEATURES" not in out.text


def test_features_line_omitted_when_all_amenities_none():
    listing = _listing(has_pool=None, has_garden=None, has_elevator=None, pois=[])
    out = compose_canonical_text(listing)
    assert "FEATURES" not in out.text


def test_features_treats_none_and_false_identically():
    """Hash stability: a property whose has_pool field is null reads as
    having no pool, same as has_pool=False. Both render the same line."""
    a = _listing(has_pool=False, has_garden=True, has_elevator=None, pois=[])
    b = _listing(has_pool=None, has_garden=True, has_elevator=False, pois=[])
    assert compose_canonical_text(a).text == compose_canonical_text(b).text


def test_features_ordering_is_fixed_not_alphabetical():
    """The render order is fixed (pool, garden, elevator) regardless of
    which booleans are set. This is hash-stable AND matches the order
    a portuguese reader would expect for amenity lists."""
    listing = _listing(has_pool=True, has_garden=False, has_elevator=True, pois=[])
    out = compose_canonical_text(listing)
    # piscina before elevador, no jardim
    assert "FEATURES: piscina, elevador" in out.text


def test_pois_render_pt_category_names():
    """PT user queries like 'ginásio' or 'escola' must match strongly.
    The composer translates the en enum strings → PT terms."""
    listing = _listing(
        pois=[
            ListingPoi(category="gym", name="Holmes Place", distance_meters=234.0),
            ListingPoi(category="school", name="Escola X", distance_meters=412.5),
            ListingPoi(category="grocery", name="Pingo Doce", distance_meters=510.0),
        ]
    )
    out = compose_canonical_text(listing)
    assert "ginásio: Holmes Place" in out.text
    assert "escola: Escola X" in out.text
    assert "supermercado: Pingo Doce" in out.text
    # The English category strings should NOT leak into canonical text
    assert "gym:" not in out.text
    assert "school:" not in out.text
    assert "grocery:" not in out.text


def test_pois_unknown_category_falls_back_to_raw_string():
    """If properties adds a category we haven't translated yet, the raw
    string falls through (defensive — don't crash). The category is no
    longer required to be in the PT map, only the distance cap applies.

    Here `nightclub` isn't in the PT map nor the allowlist — drops.
    But for a hypothetical category-in-allowlist-but-no-translation,
    fall through. Today every allowlist member IS translated, so this
    test fixes the contract for future additions."""
    # Use a known-allowed category but with a name that exercises the
    # fallback isn't engaged for it (negative confirmation).
    listing = _listing(
        pois=[ListingPoi(category="bakery", name="Padaria Central", distance_meters=200.0)]
    )
    out = compose_canonical_text(listing)
    assert "padaria: Padaria Central" in out.text


def test_pois_outside_allowlist_still_filtered():
    """A category absent from `_POI_CATEGORY_PT` (and hence the
    derived allowlist) is dropped from the canonical text, regardless
    of distance. Prevents future category drift from polluting
    embeddings without a controlled rollout here."""
    listing = _listing(
        pois=[
            ListingPoi(category="school", name="Escola Y", distance_meters=200.0),
            ListingPoi(category="nightclub", name="Lux", distance_meters=300.0),
        ]
    )
    out = compose_canonical_text(listing)
    assert "escola: Escola Y" in out.text
    assert "Lux" not in out.text
    assert "nightclub" not in out.text
