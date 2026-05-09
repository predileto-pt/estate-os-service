"""Canonical-text composer for the listings semantic-search index.

Pure function `compose_canonical_text(listing) -> CanonicalText`. The
output is a deterministic, labeled, line-oriented string fed to the
embedder; same input ⇒ same output, byte-for-byte. Hash stability is
load-bearing: the embedding handler skips re-embedding when the
`(hash, version, model)` tuple matches the persisted one, so any
non-deterministic rendering would burn embed calls on every event.

Schema is `LISTING_CANONICAL_TEXT_V2` (ADR-013 §3a, amended). Any
change to the rendering — new fields, reordered lines, different
separators, different POI format — is a `V3` bump, not an in-place
edit.

**v2 changes** (over v1):

- POI categories rendered with PT-PT terms instead of the underlying
  enum string, so PT user queries match strongly. `gym` → `ginásio`,
  `school` → `escola`, etc. Multilingual embedders match across
  languages but PT-PT is strictly stronger than PT-EN.
- New `FEATURES:` line for boolean amenities (`has_pool`,
  `has_garden`, `has_elevator`). Only TRUE features render — no
  `sem piscina` for absent amenities. PT terms.
- Migration impact: every listing's persisted `embedding_text_hash`
  becomes invalid, so the embedding handler re-embeds on the next
  event. Stagnant listings (no further events) need a backfill —
  see follow-up spec.

Rendering rules (locked at v2; any change is v3):

- Fields render in fixed order: LOCATION, LISTING_TYPE, TYPOLOGY,
  SIZE, BUILT, FEATURES, PRICE, NEARBY, DESCRIPTION.
- Single-value lines: omit the whole `LABEL: ...` line if the value is
  null/empty.
- Composite lines (LOCATION, SIZE, BUILT, FEATURES): omit null
  sub-fields with their preceding separator. Drop the line entirely
  if all sub-fields null.
- Whitespace inside any value is collapsed to single spaces and
  trimmed.
- Description is suffix-clipped to MAX_DESCRIPTION_CHARS (default 2000).
- POI rendering invariants (spec §3a):
    - Filter-before-render: POIs outside the category allowlist or
      beyond LISTING_POI_MAX_DISTANCE_M are dropped.
    - Sort key: (category, distance_m_rounded, name.lower()) — total
      order, locale-independent.
    - Distance rounded to nearest 100m, formatted as `<n.n>km` (one
      decimal). Re-geocoding jitter <100m can't invalidate the hash.
    - Hard cap at LISTING_POI_MAX_COUNT (default 20).
    - Categories rendered in PT (see `_POI_CATEGORY_PT`); fall back
      to the raw category string for unknown categories so a future
      properties-side addition doesn't crash.
- Line separator is a single LF. No trailing newline.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Iterable

from listings.domain.property_listing import ListingPoi, PropertyListing

CANONICAL_TEXT_VERSION = "v2"

# PT-PT translation of POI category strings. The properties context
# uses English enum values (`gym`, `school`, …) for portability; the
# canonical text renders the PT term so PT user queries hit strongly.
# Sort order is alphabetical-by-en-key for stable iteration / review;
# the actual canonical-text ordering is by `(category, distance, name)`
# so the dict iteration order doesn't matter at render time.
_POI_CATEGORY_PT: dict[str, str] = {
    "bakery": "padaria",
    "bank": "banco",
    "coffee_shop": "café",
    "gas_station": "posto de combustível",
    "grocery": "supermercado",
    "gym": "ginásio",
    "hospital": "hospital",
    "kindergarten": "infantário",
    "laundry": "lavandaria",
    "library": "biblioteca",
    "park": "parque",
    "pharmacy": "farmácia",
    "police_station": "esquadra",
    "post_office": "correios",
    "public_transit": "transportes públicos",
    "restaurant": "restaurante",
    "school": "escola",
    "shopping_mall": "centro comercial",
}

# The category allowlist is implicit in the keys of `_POI_CATEGORY_PT` —
# unknown categories fall back to the raw string so a future
# properties-side addition (new category) renders harmlessly until it
# lands here. The filter-before-render rule still applies to the
# distance cap; categories are no longer filtered by allowlist.
_POI_CATEGORY_ALLOWLIST: frozenset[str] = frozenset(_POI_CATEGORY_PT.keys())

# Boolean amenity fields and their PT render terms. Only TRUE values
# render. Order is fixed (iteration order over this list) so the
# canonical text is byte-stable across runs.
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
    """Round to nearest 100m. Locks distance precision against geocoder
    jitter so the same physical POI distance always renders the same."""
    return int(round(distance_meters / 100.0)) * 100


def _format_km(distance_meters: float) -> str:
    """Render rounded distance as `<n.n>km`."""
    rounded_m = _round_distance_m(distance_meters)
    return f"{rounded_m / 1000:.1f}km"


def _render_pois(pois: Iterable[ListingPoi]) -> str:
    max_count = _int_env("LISTING_POI_MAX_COUNT", 20)
    max_distance_m = _int_env("LISTING_POI_MAX_DISTANCE_M", 3000)
    filtered = [
        p
        for p in pois
        if p.category in _POI_CATEGORY_ALLOWLIST and p.distance_meters <= max_distance_m
    ]
    # Sort by the PT-rendered category so the resulting text is
    # locally consistent (e.g. all `escola:` entries adjacent in the
    # rendered list, regardless of how the en-key sorted them). Tie-
    # break on rounded distance and lowercased name for total order.
    sorted_pois = sorted(
        filtered,
        key=lambda p: (
            _POI_CATEGORY_PT.get(p.category, p.category),
            _round_distance_m(p.distance_meters),
            p.name.lower(),
        ),
    )
    capped = sorted_pois[:max_count]
    return ", ".join(
        f"{_POI_CATEGORY_PT.get(p.category, p.category)}: {_clean(p.name)} ({_format_km(p.distance_meters)})"
        for p in capped
    )


def _render_features(listing: PropertyListing) -> str:
    """Build the PT amenity list. Only TRUE booleans render — None
    (unknown) and False are both omitted so a property without a pool
    doesn't carry a "no pool" signal in its embedding.

    Returns an empty string when the property has no amenities to
    declare; the caller drops the FEATURES line entirely in that case
    (per single-value-line null rule).
    """
    parts: list[str] = []
    for attr, term in _AMENITY_FIELDS:
        value = getattr(listing, attr, None)
        if value is True:
            parts.append(term)
    return ", ".join(parts)


@dataclass(frozen=True)
class CanonicalText:
    text: str
    version: str
    hash: str  # SHA-256 hex


def compose_canonical_text(listing: PropertyListing) -> CanonicalText:
    """Render `LISTING_CANONICAL_TEXT_V1` for a listing.

    Pure / deterministic. Reads no I/O.
    """
    lines: list[str] = []

    # LOCATION (composite)
    location_parts = [
        _clean(part)
        for part in (listing.parish, listing.municipality, listing.district)
        if part and _clean(part)
    ]
    if location_parts:
        lines.append("LOCATION: " + " · ".join(location_parts))

    # LISTING_TYPE (single)
    if listing.listing_type:
        lines.append(f"LISTING_TYPE: {listing.listing_type.value.upper()}")

    # TYPOLOGY (single)
    if listing.typology:
        lines.append(f"TYPOLOGY: {listing.typology.value.upper()}")

    # SIZE (composite: bedrooms · bathrooms · area)
    size_parts: list[str] = []
    if listing.num_of_bedrooms is not None:
        size_parts.append(f"{listing.num_of_bedrooms} bed")
    if listing.num_of_bathrooms is not None:
        size_parts.append(f"{listing.num_of_bathrooms} bath")
    if listing.area_in_m2 is not None:
        size_parts.append(f"{listing.area_in_m2} m²")
    if size_parts:
        lines.append("SIZE: " + " · ".join(size_parts))

    # BUILT (composite: year_built · energy <energy_rating>)
    built_parts: list[str] = []
    if listing.built_at is not None:
        built_parts.append(str(listing.built_at))
    if listing.energy_rating:
        built_parts.append(f"energy {_clean(listing.energy_rating)}")
    if built_parts:
        lines.append("BUILT: " + " · ".join(built_parts))

    # FEATURES (single, PT amenity list — v2). Only renders TRUE
    # booleans; the line is omitted if no amenities are claimed.
    features_text = _render_features(listing)
    if features_text:
        lines.append(f"FEATURES: {features_text}")

    # PRICE (single, EUR)
    if listing.min_price is not None:
        # Render whole-EUR integer for hash stability — listings carry
        # `Decimal(12, 2)` but the embedding doesn't need the cents.
        lines.append(f"PRICE: {int(listing.min_price)} EUR")

    # NEARBY (single, derived from POIs)
    poi_summary = _render_pois(listing.pois)
    if poi_summary:
        lines.append(f"NEARBY: {poi_summary}")

    # DESCRIPTION (single, truncated)
    if listing.description:
        cleaned = _clean(listing.description)
        max_chars = _int_env("LISTING_DESCRIPTION_MAX_CHARS", 2000)
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars]
        if cleaned:
            lines.append(f"DESCRIPTION: {cleaned}")

    text = "\n".join(lines)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return CanonicalText(text=text, version=CANONICAL_TEXT_VERSION, hash=digest)
