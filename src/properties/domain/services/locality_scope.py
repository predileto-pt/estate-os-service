"""What counts as 'the same locality' as the property, by country.

Pure module. The POI sanitizer drops candidates whose address falls
outside the property's locality. Different countries use different
administrative units for the typical real-estate "neighborhood" buyer
question:

  - Portugal → `concelho` (municipality). Lisbon-the-municipality is
    the meaningful boundary; freguesia is too narrow, distrito too
    broad.
  - Brazil / United States / everyone else → city. PT's nested
    parish/municipality/district hierarchy doesn't translate
    elsewhere; falling back to "city" matches how addresses are
    actually written and how buyers ask "is this in the same city as
    my flat".

Only the kind ships in the value object — the human-readable label
(e.g. "concelho" / "city") lives in the OpenAI adapter's prompt.
"""

from __future__ import annotations

import enum


class LocalityKind(str, enum.Enum):
    """The administrative unit that delimits 'same locality'."""

    MUNICIPALITY = "municipality"  # PT-PT: concelho.
    CITY = "city"  # BR, US, and any country that doesn't carry a
    # PT-style parish/municipality/district triple.


_PORTUGAL = "Portugal"


def resolve_locality_scope(country: str | None) -> LocalityKind:
    """Pick the locality kind that should bound POI sanitization.

    Falls back to `CITY` when the country is unknown or missing — the
    safer default outside Portugal's administrative model.
    """
    if country and country.strip() == _PORTUGAL:
        return LocalityKind.MUNICIPALITY
    return LocalityKind.CITY
