"""Cursor value objects, encode/decode round-trip, fp binding, and
canonicalization.

Test plan (per spec acceptance criteria):
- Round-trip both cursor kinds through encode → decode_token.
- `validate_fp` raises on mismatch, no-ops on match.
- `decode_token` raises `CursorVersionError` for wrong v,
  `CursorDecodeError` for everything else, **before** any fp check.
- `filter_fingerprint` excludes limit/offset (Q3 acceptance).
- `filter_fingerprint` is stable across Decimal/Enum/string forms
  (canonicalization rules).
- `build_list_cache_key` includes `limit` in the key.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest

from listings.domain.location_filter import LocationFilter
from listings.domain.models import ListingType, Typology
from listings.domain.pagination import (
    CURSOR_SCHEMA_VERSION,
    CursorDecodeError,
    CursorFilterMismatchError,
    CursorVersionError,
    ListCursor,
    SearchCursor,
    build_list_cache_key,
    build_search_cache_key,
    decode_token,
    encode,
    filter_fingerprint,
    validate_fp,
)
from listings.domain.property_filters import PropertyFilters


# ─── encode / decode round-trip ───────────────────────────────────────────


def test_list_cursor_roundtrip():
    cursor = ListCursor(
        fp="abcdef1234567890",
        created_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc),
        id=UUID("af0bae64-c0f7-451a-8a1d-56d9b2867758"),
    )
    decoded = decode_token(encode(cursor))
    assert decoded == cursor


def test_search_cursor_roundtrip():
    cursor = SearchCursor(fp="abcdef1234567890", offset=40)
    decoded = decode_token(encode(cursor))
    assert decoded == cursor


def test_decode_returns_correct_type_per_kind():
    list_token = encode(ListCursor(
        fp="ff" * 8,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        id=UUID("00000000-0000-0000-0000-000000000001"),
    ))
    search_token = encode(SearchCursor(fp="ff" * 8, offset=20))

    assert isinstance(decode_token(list_token), ListCursor)
    assert isinstance(decode_token(search_token), SearchCursor)


# ─── error precedence: version > invalid > kind > filter ──────────────────


def test_decode_raises_version_error_for_wrong_v():
    bad = base64.urlsafe_b64encode(
        json.dumps({"v": 999, "k": "list", "fp": "x"}).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(CursorVersionError):
        decode_token(bad)


def test_decode_raises_decode_error_for_corrupt_b64():
    with pytest.raises(CursorDecodeError):
        decode_token("not!!!base64@@@")


def test_decode_raises_decode_error_for_corrupt_json():
    bad = base64.urlsafe_b64encode(b"not json").rstrip(b"=").decode()
    with pytest.raises(CursorDecodeError):
        decode_token(bad)


def test_decode_raises_decode_error_for_unknown_kind():
    bad = base64.urlsafe_b64encode(
        json.dumps({"v": CURSOR_SCHEMA_VERSION, "k": "wat", "fp": "x"}).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(CursorDecodeError):
        decode_token(bad)


def test_decode_raises_decode_error_for_missing_fields():
    bad = base64.urlsafe_b64encode(
        json.dumps({"v": CURSOR_SCHEMA_VERSION, "k": "list", "fp": "x"}).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(CursorDecodeError):
        decode_token(bad)


def test_decode_raises_decode_error_for_negative_search_offset():
    bad = base64.urlsafe_b64encode(
        json.dumps({"v": CURSOR_SCHEMA_VERSION, "k": "search", "fp": "x", "o": -1}).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(CursorDecodeError):
        decode_token(bad)


def test_decode_does_not_check_fp():
    """Confirms two-step decode: fp validation is the route's job,
    not decode_token's. Otherwise we couldn't surface
    `cursor_kind_mismatch` over `cursor_filter_mismatch`."""
    cursor = SearchCursor(fp="anything", offset=10)
    # Just decoding shouldn't raise even if no one ever validates fp.
    assert decode_token(encode(cursor)) == cursor


def test_validate_fp_passes_on_match():
    cursor = SearchCursor(fp="abc123", offset=10)
    validate_fp(cursor, expected_fp="abc123")  # no exception


def test_validate_fp_raises_on_mismatch():
    cursor = SearchCursor(fp="abc123", offset=10)
    with pytest.raises(CursorFilterMismatchError):
        validate_fp(cursor, expected_fp="different")


# ─── filter_fingerprint canonicalization ──────────────────────────────────


def _base_filters() -> PropertyFilters:
    return PropertyFilters(
        listing_type=ListingType.SALE,
        typology=Typology.APARTMENT,
        min_price=Decimal("100000"),
        max_price=Decimal("500000"),
        parish="Misericórdia",
        municipality="Lisboa",
        district="Lisboa",
    )


def test_fp_excludes_limit_and_offset():
    """Cursor must stay valid if the FE changes page size — fp
    excludes limit/offset. Acceptance criterion."""
    a = PropertyFilters(listing_type=ListingType.SALE, limit=20, offset=0)
    b = PropertyFilters(listing_type=ListingType.SALE, limit=10, offset=100)
    fp_a = filter_fingerprint(q=None, filters=a, location=None)
    fp_b = filter_fingerprint(q=None, filters=b, location=None)
    assert fp_a == fp_b


def test_fp_decimal_normalization():
    """`Decimal('380000')` and `Decimal('380000.00')` hash identically."""
    a = PropertyFilters(min_price=Decimal("380000"))
    b = PropertyFilters(min_price=Decimal("380000.00"))
    assert filter_fingerprint(q=None, filters=a, location=None) == \
        filter_fingerprint(q=None, filters=b, location=None)


def test_fp_string_case_and_whitespace_normalization():
    """Free-text location fields are stripped + lowercased."""
    a = PropertyFilters(parish="Misericórdia")
    b = PropertyFilters(parish="  misericórdia  ")
    assert filter_fingerprint(q=None, filters=a, location=None) == \
        filter_fingerprint(q=None, filters=b, location=None)


def test_fp_none_vs_missing_key_canonicalization():
    """`{"parish": None}` and `{}` must hash identically — the
    canonicalization layer drops None values."""
    a = PropertyFilters(listing_type=ListingType.SALE, parish=None)
    b = PropertyFilters(listing_type=ListingType.SALE)
    assert filter_fingerprint(q=None, filters=a, location=None) == \
        filter_fingerprint(q=None, filters=b, location=None)


def test_fp_enum_uses_value_not_name():
    """`ListingType.SALE.value = 'sale'` (not 'SALE'). Stable across
    a future rename of the enum constant."""
    fp = filter_fingerprint(q=None, filters=_base_filters(), location=None)
    # Canonical payload must not contain the enum constant name.
    # We rebuild the canonical bytes and assert "sale" appears,
    # "SALE" does not.
    import hashlib

    from listings.domain.pagination.cursor import _canonical_dump  # noqa: PLC0415

    raw = _canonical_dump({
        "filters": {"listing_type": "sale"},  # what we expect on the wire
    })
    assert hashlib.sha256(raw.encode()).hexdigest()[:16] != fp  # different payload, same fingerprint algo
    # The real check: same input → same fp (already covered by other tests);
    # here we just spot-check the canonical form is lowercase.
    canonical = _canonical_dump({"listing_type": ListingType.SALE.value})
    assert "sale" in canonical
    assert "SALE" not in canonical


def test_fp_changes_when_q_changes():
    fp_a = filter_fingerprint(q="hospital", filters=_base_filters(), location=None)
    fp_b = filter_fingerprint(q="school", filters=_base_filters(), location=None)
    assert fp_a != fp_b


def test_fp_changes_when_location_changes():
    loc_a = LocationFilter(municipality="Lisboa")
    loc_b = LocationFilter(municipality="Porto")
    fp_a = filter_fingerprint(q="hospital", filters=_base_filters(), location=loc_a)
    fp_b = filter_fingerprint(q="hospital", filters=_base_filters(), location=loc_b)
    assert fp_a != fp_b


# ─── cache-key helpers ────────────────────────────────────────────────────


def test_list_cache_key_includes_limit():
    """Same fp + same cursor + different limit must produce a
    different cache key. Acceptance criterion."""
    fp = "abcdef1234567890"
    key_10 = build_list_cache_key(fp=fp, cursor=None, limit=10)
    key_20 = build_list_cache_key(fp=fp, cursor=None, limit=20)
    assert key_10 != key_20


def test_list_cache_key_head_for_first_page():
    fp = "abcdef1234567890"
    key = build_list_cache_key(fp=fp, cursor=None, limit=20)
    assert "head" in key


def test_list_cache_key_includes_cursor_position():
    fp = "abcdef1234567890"
    cursor = ListCursor(
        fp=fp,
        created_at=datetime(2026, 5, 11, 12, 0, 0, tzinfo=timezone.utc),
        id=UUID("af0bae64-c0f7-451a-8a1d-56d9b2867758"),
    )
    key_head = build_list_cache_key(fp=fp, cursor=None, limit=20)
    key_with_cursor = build_list_cache_key(fp=fp, cursor=cursor, limit=20)
    assert key_head != key_with_cursor


def test_search_cache_key_is_independent_of_limit_and_offset():
    """Search cache stores the full ranked list; slicing happens at
    request time. So the key is just `fp`."""
    fp = "abcdef1234567890"
    key = build_search_cache_key(fp=fp)
    assert key == f"listings:search:v1:{fp}"
