"""Closed POI category vocabulary for the listings search read path.

Inlined in `listings` rather than imported from `properties` — review
settled on "inline + contract-test" to keep the cross-context
boundary clean. The members MUST stay value-for-value in sync with
`properties.domain.models.property_poi.PoiCategory`; a contract
test (`tests/unit/listings/test_poi_category_contract.py`) asserts
the value-set equivalence.

If `properties` bumps its enum (adds/removes a category), the
contract test fails and we update this enum in the same commit —
the values are part of the carried-state `PROPERTY_*.v1` event
payload contract, which both contexts depend on.

Spec: `2026-05-listing-search-structured-extraction` §3.
"""

from __future__ import annotations

from enum import StrEnum


class PoiCategory(StrEnum):
    HOSPITAL = "hospital"
    BANK = "bank"
    GROCERY = "grocery"
    SCHOOL = "school"
    PHARMACY = "pharmacy"
    GYM = "gym"
    RESTAURANT = "restaurant"
    COFFEE_SHOP = "coffee_shop"
    LAUNDRY = "laundry"
    GAS_STATION = "gas_station"
    PUBLIC_TRANSIT = "public_transit"
    KINDERGARTEN = "kindergarten"
    PARK = "park"
    POST_OFFICE = "post_office"
    LIBRARY = "library"
    SHOPPING_MALL = "shopping_mall"
    BAKERY = "bakery"
    POLICE_STATION = "police_station"
    TIRE_SHOP = "tire_shop"
    AUTO_SHOP = "auto_shop"
