"""Per-(country, category) breadth policy for POI discovery.

A property's POI catalog uses different breadth depending on category
relevance. In Portugal, lifestyle anchors (restaurants, cafes, gyms)
and household-critical services (hospitals, pharmacies, schools) are
surfaced municipality-wide so a buyer can see every local option. The
remaining categories stay capped at a small proximity-ranked top-N to
keep the listing focused.

Pure module — depends only on `PoiCategory`. No I/O, no provider
imports. The discovery use case calls `resolve_discovery_policy` and
threads `radius_meters` / `result_limit` into the places adapter and
ranker. Adding a new country = add a `Country` member + a per-country
table; the use case doesn't change.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from properties.domain.models.property_poi import PoiCategory


class Country(str, enum.Enum):
    """Countries with a defined discovery policy.

    String values match the free-text `country` carried on the listings
    projection so callers can pass either the enum or the raw string.
    """

    PORTUGAL = "Portugal"


@dataclass(frozen=True)
class CategoryDiscoveryPolicy:
    """How widely to search for one POI category.

    `radius_meters` bounds the underlying provider call. `result_limit`
    is the hard cap applied after ranking — `None` means keep every
    result the provider returned within the radius (subject to the
    provider's own response cap).
    """

    radius_meters: int
    result_limit: int | None


# Default — focused proximity-ranked top-N around the property.
DEFAULT_POLICY = CategoryDiscoveryPolicy(radius_meters=1500, result_limit=5)

# Municipality-wide breadth. PT municipalities average ~10km radius;
# 15km comfortably contains every typical municipality. Provider's own
# cap (Google: 50_000m) still applies. Capped at 10 per category — a
# buyer evaluating an area needs 10 of the best/closest matches, not
# every one in the municipality. Without this cap, lifestyle anchors
# alone produced 300+ POIs per property, ballooning event payloads
# beyond SNS's 256 KB limit and making Phase-2 Place Details fan-out
# take minutes (see `2026-05-12` debug session).
MUNICIPALITY_WIDE_POLICY = CategoryDiscoveryPolicy(radius_meters=15000, result_limit=10)


# Categories surfaced municipality-wide for Portugal listings:
# lifestyle anchors (restaurants, cafes, gyms), household-critical
# services (hospitals, pharmacies, schools), and auto services
# (tire/repair shops are sparse — a buyer wants every option in town).
# Anything else falls through to `DEFAULT_POLICY`.
_PT_MUNICIPALITY_WIDE_CATEGORIES: frozenset[PoiCategory] = frozenset(
    {
        PoiCategory.RESTAURANT,
        PoiCategory.COFFEE_SHOP,
        PoiCategory.GYM,
        PoiCategory.HOSPITAL,
        PoiCategory.PHARMACY,
        PoiCategory.SCHOOL,
        PoiCategory.TIRE_SHOP,
        PoiCategory.AUTO_SHOP,
    }
)


def resolve_discovery_policy(
    country: Country | str | None, category: PoiCategory
) -> CategoryDiscoveryPolicy:
    """Pick the discovery policy for one `(country, category)` pair.

    Country is accepted as either a `Country` enum or a raw string —
    the upstream Property aggregate carries country only as free text
    today. Unknown / missing countries fall back to `DEFAULT_POLICY`.
    """
    if country is None:
        return DEFAULT_POLICY
    country_value = country.value if isinstance(country, Country) else country
    if country_value == Country.PORTUGAL.value and category in _PT_MUNICIPALITY_WIDE_CATEGORIES:
        return MUNICIPALITY_WIDE_POLICY
    return DEFAULT_POLICY
