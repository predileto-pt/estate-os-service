"""Filter dataclass for the listings read API.

Lives on the domain side so both the route layer and the
`PropertyListingRepository` port reference it without crossing
adapter boundaries.

Note: `district` here is now an **exact match** against the
`property_listings.district` column (populated by the address
enrichment handler), not the legacy ILIKE on the raw address that
the dropped `ListingRepository` did. The new `parish` and
`municipality` fields are likewise exact-match.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from listings.domain.models import ListingType, Typology


@dataclass(frozen=True)
class PropertyFilters:
    listing_type: ListingType | None = None
    typology: Typology | None = None
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    parish: str | None = None
    municipality: str | None = None
    district: str | None = None
    # `limit` / `offset` are admin-path only — the cursor path
    # (public /listings/properties) passes `limit` to the use case
    # directly and uses keyset positioning instead of offset. Admin
    # callers MUST set both; the repos dereference them in
    # `list_active` / `list_active_for_organization`.
    limit: int | None = 50
    offset: int | None = 0
