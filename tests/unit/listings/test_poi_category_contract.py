"""Contract test pinning `listings.PoiCategory` value-for-value to
`properties.domain.models.property_poi.PoiCategory`.

The two enums carry the same string values because POI categories
are part of the `PROPERTY_*.v1` event payload contract — the
listings projector consumes them as strings and the
canonical-text composer renders them via `PoiCategory.value`. If
properties bumps its enum, this test fails and BOTH sides update
in the same commit. Without this guard a properties-side
extension would silently break listings' closed-vocabulary
extraction (the LLM prompt lists the listings enum).

Spec: `2026-05-listing-search-structured-extraction` §3.
"""

from __future__ import annotations

from listings.domain.poi_category import PoiCategory as ListingsPoiCategory
from properties.domain.models.property_poi import PoiCategory as PropertiesPoiCategory


def test_values_match_properties():
    listings_values = {c.value for c in ListingsPoiCategory}
    properties_values = {c.value for c in PropertiesPoiCategory}
    assert listings_values == properties_values, (
        f"PoiCategory mismatch.\n"
        f"In listings but not properties: {listings_values - properties_values}\n"
        f"In properties but not listings: {properties_values - listings_values}\n"
        f"Both sides must stay in lockstep — they're part of the event payload contract."
    )


def test_listings_has_all_members():
    """Defense in depth — at the time of writing both sides carry
    20 categories. If this number changes, the values-match
    assertion above already covers it, but the count is a quick
    smoke test."""
    assert len(list(ListingsPoiCategory)) == 20
