"""Route-side validation for the search read path.

Extracted from the route handler so the 422 guard can be
unit-tested independently. The acceptance criterion at the spec
level requires a machine-readable error code on the 422 — this
helper produces that shape.

Spec: `2026-05-listing-semantic-search-read-path` §"Required-
location validation".
"""

from __future__ import annotations

from fastapi import HTTPException


def normalize_query(q: str | None) -> str | None:
    """Whitespace-only `q` is equivalent to no `q` — falls through to
    the existing structured-filter path. Returns the stripped string
    or None."""
    if q is None:
        return None
    stripped = q.strip()
    return stripped or None


def validate_location_for_search(
    *,
    normalized_q: str | None,
    parish: str | None,
    municipality: str | None,
    district: str | None,
) -> None:
    """Raise 422 with a machine-readable error code when `q` is set
    but no location level was provided.

    The FE should never get here (the selector forces a location
    pick before allowing free-text search), but defense in depth.
    """
    if normalized_q is None:
        return
    if not (parish or municipality or district):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "location_required_for_search",
                "message": (
                    "When 'q' is provided, at least one of "
                    "'parish', 'municipality', 'district' is required."
                ),
            },
        )
