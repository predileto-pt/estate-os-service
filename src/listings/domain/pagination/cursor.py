"""Cursor value objects, codec, and cache-key helpers.

The two cursor types share one base64url-encoded JSON envelope:

    ListCursor   → {"v":1,"k":"list",  "fp":"<16-hex>","c":"<iso>","i":"<uuid>"}
    SearchCursor → {"v":1,"k":"search","fp":"<16-hex>","o":<int>}

Decode is **two-step** on purpose: `decode_token` returns the typed
cursor without checking `fp`; the route checks cursor kind (list vs
search) and only then calls `validate_fp`. This gives error precedence
`version > invalid > kind > filter` so a list cursor presented in
search mode surfaces as `cursor_kind_mismatch` (mode changed — drop
cursor + retry) and not `cursor_filter_mismatch` (which would be
correct on the wire but misleading about *why*).

The `fp` field binds a cursor to the exact filter set that produced
it. `filter_fingerprint` is the sha256 of a canonical-JSON
serialization of (q, filters, location); see the canonicalization
rules at the bottom of this file.

Spec: `.claude/specs/active/2026-05-listings-cursor-pagination-and-page-cache.md`.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from listings.domain.location_filter import LocationFilter
from listings.domain.property_filters import PropertyFilters

CURSOR_SCHEMA_VERSION = 1


class CursorVersionError(Exception):
    """Cursor's `v` doesn't match `CURSOR_SCHEMA_VERSION`. FE must
    drop cursor state and re-fetch from head."""

    def __init__(self, version: Any) -> None:
        super().__init__(f"unsupported cursor schema version: {version!r}")
        self.version = version


class CursorDecodeError(Exception):
    """Corrupt base64 / JSON, missing fields, or unknown `k`. FE
    treats this the same as a missing cursor."""


class CursorFilterMismatchError(Exception):
    """Cursor's `fp` doesn't match the current request's fp — the
    user changed filters between requests. FE drops cursor + retries
    from head."""


@dataclass(frozen=True)
class ListCursor:
    fp: str
    created_at: datetime
    id: UUID


@dataclass(frozen=True)
class SearchCursor:
    fp: str
    offset: int


# ─── Encode / decode ──────────────────────────────────────────────────────


def encode(cursor: ListCursor | SearchCursor) -> str:
    """Serialize a cursor to its opaque base64url token."""
    if isinstance(cursor, ListCursor):
        payload: dict[str, Any] = {
            "v": CURSOR_SCHEMA_VERSION,
            "k": "list",
            "fp": cursor.fp,
            "c": cursor.created_at.isoformat(),
            "i": str(cursor.id),
        }
    else:
        payload = {
            "v": CURSOR_SCHEMA_VERSION,
            "k": "search",
            "fp": cursor.fp,
            "o": cursor.offset,
        }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def decode_token(token: str) -> ListCursor | SearchCursor:
    """Decode the envelope into the typed cursor. Does NOT validate
    `fp` — the caller validates that after the kind check.

    Raises `CursorVersionError` for a wrong `v`, `CursorDecodeError`
    for everything else (corrupt b64/JSON, missing required keys,
    unknown `k`, malformed datetime/UUID).
    """
    try:
        # base64url has no padding in our wire format; restore it.
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded)
        parsed = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise CursorDecodeError(f"corrupt cursor envelope: {exc}") from exc

    if not isinstance(parsed, dict):
        raise CursorDecodeError("cursor payload must be an object")

    version = parsed.get("v")
    if version != CURSOR_SCHEMA_VERSION:
        raise CursorVersionError(version)

    fp = parsed.get("fp")
    kind = parsed.get("k")
    if not isinstance(fp, str) or not isinstance(kind, str):
        raise CursorDecodeError("cursor missing fp/k")

    if kind == "list":
        try:
            created_at = datetime.fromisoformat(parsed["c"])
            cursor_id = UUID(parsed["i"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CursorDecodeError(f"malformed list cursor payload: {exc}") from exc
        return ListCursor(fp=fp, created_at=created_at, id=cursor_id)

    if kind == "search":
        try:
            offset = int(parsed["o"])
        except (KeyError, TypeError, ValueError) as exc:
            raise CursorDecodeError(f"malformed search cursor payload: {exc}") from exc
        if offset < 0:
            raise CursorDecodeError(f"search cursor offset must be ≥ 0, got {offset}")
        return SearchCursor(fp=fp, offset=offset)

    raise CursorDecodeError(f"unknown cursor kind: {kind!r}")


def validate_fp(cursor: ListCursor | SearchCursor, *, expected_fp: str) -> None:
    """Raise `CursorFilterMismatchError` if the cursor's fp differs
    from the request's. Caller runs this AFTER the kind check so the
    error precedence is version > invalid > kind > filter."""
    if cursor.fp != expected_fp:
        raise CursorFilterMismatchError(
            f"cursor fp {cursor.fp!r} != request fp {expected_fp!r}"
        )


# ─── Fingerprint ──────────────────────────────────────────────────────────


def filter_fingerprint(
    *,
    q: str | None,
    filters: PropertyFilters,
    location: LocationFilter | None,
) -> str:
    """sha256(canonical JSON of binding inputs)[:16].

    Binds the cursor to the (q, listing_type, typology, min_price,
    max_price, parish, municipality, district, location) tuple. The
    canonical-JSON rules below ensure the same logical filter set
    always produces the same hash across Python versions, library
    upgrades, and process boundaries. **Explicitly excludes `limit`
    and `offset`** — those are pagination concerns, not filter
    identity (cursor must stay valid if the FE changes page size).
    """
    payload = {
        "q": _canonicalize_str(q),
        "filters": {
            "listing_type": _canonicalize_enum(filters.listing_type),
            "typology": _canonicalize_enum(filters.typology),
            "min_price": _canonicalize_decimal(filters.min_price),
            "max_price": _canonicalize_decimal(filters.max_price),
            "parish": _canonicalize_str(filters.parish),
            "municipality": _canonicalize_str(filters.municipality),
            "district": _canonicalize_str(filters.district),
        },
        "location": _canonicalize_location(location),
    }
    canonical = _canonical_dump(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _canonicalize_str(value: str | None) -> str | None:
    """None stays None; non-empty strings are stripped + lowercased
    so case + whitespace differences from the FE don't fork the
    cache. `q` itself is already normalised upstream via
    `normalize_query`; re-running `.strip().lower()` here is a
    cheap idempotent safety net."""
    if value is None:
        return None
    stripped = value.strip().lower()
    return stripped or None


def _canonicalize_enum(value: Enum | None) -> str | None:
    return value.value if value is not None else None


def _canonicalize_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    # `Decimal("380000")` and `Decimal("380000.00")` normalize to the
    # same string here — strip trailing zeros so price representations
    # don't fork the cache.
    return str(value.normalize())


def _canonicalize_location(value: LocationFilter | None) -> dict | None:
    if value is None:
        return None
    return {
        "parish": _canonicalize_str(value.parish),
        "municipality": _canonicalize_str(value.municipality),
        "district": _canonicalize_str(value.district),
    }


def _canonical_dump(obj: Any) -> str:
    """Drop None values, sort keys, no whitespace. Single source of
    truth for the canonical-JSON encoding used by `filter_fingerprint`."""
    return json.dumps(
        _strip_nones(obj),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _strip_nones(obj: Any) -> Any:
    """Recursively drop keys whose value is None. `{"parish": null}`
    and `{}` would hash differently otherwise."""
    if isinstance(obj, dict):
        return {k: _strip_nones(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nones(v) for v in obj]
    return obj


# ─── Cache-key helpers ────────────────────────────────────────────────────


def build_list_cache_key(
    *,
    fp: str,
    cursor: ListCursor | None,
    limit: int,
) -> str:
    """`listings:list:v1:{fp}:{cursor_part}:{limit}`.

    `limit` is in the key — same fp + same cursor + different limit
    must be a different cached page. `cursor_part` is `"head"` for
    the first page so popular first pages share one cache entry per
    filter combo + limit.
    """
    if cursor is None:
        cursor_part = "head"
    else:
        cursor_part = f"{cursor.created_at.isoformat()}:{cursor.id}"
    return f"listings:list:v1:{fp}:{cursor_part}:{limit}"


def build_search_cache_key(*, fp: str) -> str:
    """`listings:search:v1:{fp}`.

    The cached value contains the full ranked id list + parsed
    query; `limit` and `offset` are applied at slice time, so they
    don't appear in the key.
    """
    return f"listings:search:v1:{fp}"
