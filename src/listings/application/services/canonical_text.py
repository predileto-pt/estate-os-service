"""Canonical-text composer for the listings semantic-search index.

Pure function `compose_canonical_text(listing) -> CanonicalText`. The
output is a deterministic, labeled, line-oriented string fed to the
embedder; same input ⇒ same output, byte-for-byte. Hash stability is
load-bearing: the embedding handler skips re-embedding when the
`(hash, version, model)` tuple matches the persisted one, so any
non-deterministic rendering would burn embed calls on every event.

Schema is `LISTING_CANONICAL_TEXT_V3` (ADR-014 §9). Any change to
the rendering — new fields, reordered lines, different separators,
different POI format — is a V4 bump, not an in-place edit.

**v3 changes** (over v2):

- Sectional layout aligned with the query-extractor's
  `_render_query_for_embed`: TYPOLOGY → CHARACTERISTICS →
  FEATURES → NEARBY → DESCRIPTION → LOCATION → PRICE. Cosine
  aligns the two sides implicitly when both speak the same
  structure.
- TYPOLOGY uses `Typology.value` (lowercase string), not
  `.value.upper()`. The query extractor outputs the same case.
- New `CHARACTERISTICS:` line replaces v2's SIZE+BUILT lines.
  Format: `T<bedrooms>, <area>m², <bathrooms> casas de banho`.
- FEATURES line gains `garagem` (from `parking_spaces > 0`).
  All four amenities (piscina, jardim, elevador, garagem)
  render as PT terms — same set the query extractor maps to.
- NEARBY uses **raw `PoiCategory` value strings** (`school`,
  `gym`, `supermarket`, …) NOT PT translations. The query
  extractor produces the same closed-vocab strings, so cosine
  has the cleanest possible match. Format:
  `<category>@<distance_m>m, …` sorted ascending by distance.
  Distance rounded to the nearest 100m for hash stability.

Rendering rules (locked at v3; any change is v4):

- Fields render in fixed order: TYPOLOGY, CHARACTERISTICS,
  FEATURES, NEARBY, DESCRIPTION, LOCATION, PRICE.
- Single-value lines: omit the whole `LABEL: ...` line if the
  value is null/empty.
- Composite lines (CHARACTERISTICS, FEATURES, NEARBY, LOCATION):
  omit null sub-fields. Drop the line entirely if all sub-fields
  null.
- Whitespace inside any value is collapsed to single spaces and
  trimmed.
- Description is suffix-clipped to LISTING_DESCRIPTION_MAX_CHARS
  (default 2000).
- POI rendering invariants:
    - Filter-before-render: POIs beyond LISTING_POI_MAX_DISTANCE_M
      are dropped. No category allowlist — `PoiCategory` IS the
      vocabulary; unknown categories from a properties-side
      addition would surface as-is (forward-compat).
    - Sort key: (distance_m_rounded, category, name.lower()) —
      ascending by distance first (matches the FE rendering of
      `<category>@<distance>m` chips), then category/name for
      total order on ties.
    - Distance rounded to nearest 100m; render as
      `<category>@<rounded_m>m`. Geocoder jitter <100m
      can't invalidate the hash.
    - Hard cap at LISTING_POI_MAX_COUNT (default 20).
- Line separator is a single LF. No trailing newline.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Iterable

from listings.domain.property_listing import ListingPoi, PropertyListing

CANONICAL_TEXT_VERSION = "v3"


# Boolean amenity fields and their PT render terms. Only TRUE
# values render. Order is fixed (iteration order over this list) so
# the canonical text is byte-stable across runs. `garagem` derives
# from `parking_spaces > 0`, handled separately because the source
# isn't a `bool` column.
_AMENITY_FIELDS: tuple[tuple[str, str], ...] = (
    ("has_pool", "piscina"),
    ("has_garden", "jardim"),
    ("has_elevator", "elevador"),
)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_WHITESPACE_RE = re.compile(r"\s+")


def _clean(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value).strip()


def _round_distance_m(distance_meters: float) -> int:
    """Round to nearest 100m. Locks distance precision against
    geocoder jitter so the same physical POI distance always renders
    the same."""
    return int(round(distance_meters / 100.0)) * 100


def _render_pois(pois: Iterable[ListingPoi]) -> str:
    max_count = _int_env("LISTING_POI_MAX_COUNT", 20)
    max_distance_m = _int_env("LISTING_POI_MAX_DISTANCE_M", 3000)
    filtered = [p for p in pois if p.distance_meters <= max_distance_m]
    # Sort ascending by rounded distance, then category, then name
    # for total order (locale-independent).
    sorted_pois = sorted(
        filtered,
        key=lambda p: (
            _round_distance_m(p.distance_meters),
            p.category,
            p.name.lower(),
        ),
    )
    capped = sorted_pois[:max_count]
    return ", ".join(
        f"{p.category}@{_round_distance_m(p.distance_meters)}m" for p in capped
    )


def _render_features(listing: PropertyListing) -> str:
    """Build the PT amenity list. Only TRUE booleans render — None
    (unknown) and False are both omitted so a property without a pool
    doesn't carry a "no pool" signal in its embedding.
    """
    parts: list[str] = []
    for attr, term in _AMENITY_FIELDS:
        value = getattr(listing, attr, None)
        if value is True:
            parts.append(term)
    # has_parking derives from parking_spaces > 0 (not a bool column).
    parking_spaces = getattr(listing, "parking_spaces", None)
    if parking_spaces is not None and parking_spaces > 0:
        parts.append("garagem")
    return ", ".join(parts)


def _render_characteristics(listing: PropertyListing) -> str:
    """`T<bedrooms>, <area>m², <bathrooms> casas de banho`. Omit any
    null sub-field; return empty string if all three are null."""
    parts: list[str] = []
    if listing.num_of_bedrooms is not None:
        parts.append(f"T{listing.num_of_bedrooms}")
    if listing.area_in_m2 is not None:
        parts.append(f"{listing.area_in_m2}m²")
    if listing.num_of_bathrooms is not None:
        parts.append(f"{listing.num_of_bathrooms} casas de banho")
    return ", ".join(parts)


@dataclass(frozen=True)
class CanonicalText:
    text: str
    version: str
    hash: str  # SHA-256 hex


def compose_canonical_text(listing: PropertyListing) -> CanonicalText:
    """Render `LISTING_CANONICAL_TEXT_V3` for a listing.

    Pure / deterministic. Reads no I/O.
    """
    lines: list[str] = []

    # TYPOLOGY (single, lowercase enum value)
    if listing.typology:
        lines.append(f"TYPOLOGY: {listing.typology.value}")

    # CHARACTERISTICS (composite: T<beds>, <area>m², <baths> casas de banho)
    characteristics_text = _render_characteristics(listing)
    if characteristics_text:
        lines.append(f"CHARACTERISTICS: {characteristics_text}")

    # FEATURES (composite, PT amenity list). Only TRUE values render.
    features_text = _render_features(listing)
    if features_text:
        lines.append(f"FEATURES: {features_text}")

    # NEARBY (composite, derived from POIs). Raw PoiCategory.value
    # strings — same closed vocab the extractor uses.
    poi_summary = _render_pois(listing.pois)
    if poi_summary:
        lines.append(f"NEARBY: {poi_summary}")

    # DESCRIPTION (single, suffix-truncated)
    if listing.description:
        cleaned = _clean(listing.description)
        max_chars = _int_env("LISTING_DESCRIPTION_MAX_CHARS", 2000)
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars]
        if cleaned:
            lines.append(f"DESCRIPTION: {cleaned}")

    # LOCATION (composite: parish, municipality, district)
    location_parts = [
        _clean(part)
        for part in (listing.parish, listing.municipality, listing.district)
        if part and _clean(part)
    ]
    if location_parts:
        lines.append("LOCATION: " + ", ".join(location_parts))

    # PRICE (single, EUR)
    if listing.min_price is not None:
        lines.append(f"PRICE: {int(listing.min_price)} EUR")

    text = "\n".join(lines)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return CanonicalText(text=text, version=CANONICAL_TEXT_VERSION, hash=digest)
