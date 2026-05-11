"""Cursor pagination primitives for the public listings read path.

Two cursor shapes share one opaque base64url envelope:

- `ListCursor` — keyset position `(created_at, id)` for the
  structured-filter list path.
- `SearchCursor` — `offset` into a cached ranked-id-list for the
  semantic-search path.

The cursor is bound to the request's filter set via a `fp` field —
sha256 of the canonical-JSON of (q, filters, location). The route
recomputes `fp` per request and rejects cursors that don't match.

See `.claude/specs/active/2026-05-listings-cursor-pagination-and-page-cache.md`
and ADR-016.
"""

from listings.domain.pagination.cursor import (
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

__all__ = [
    "CURSOR_SCHEMA_VERSION",
    "CursorDecodeError",
    "CursorFilterMismatchError",
    "CursorVersionError",
    "ListCursor",
    "SearchCursor",
    "build_list_cache_key",
    "build_search_cache_key",
    "decode_token",
    "encode",
    "filter_fingerprint",
    "validate_fp",
]
