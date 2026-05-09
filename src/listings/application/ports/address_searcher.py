"""Country-aware address searcher port for the listings read-model.

Spec: `2026-05-property-address-enrichment-fix.md`. Replaces the old
`AddressParser` port. Each per-country implementation fills the fields
its country uses (PT: parish/municipality/district; US: city/state) and
leaves the rest None — see `ParsedAddress` below.

The handler dispatches to the right implementation via
`select_address_searcher(country, ...)`. In v1 only Portugal is
implemented; other countries raise NotImplementedError.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class ParsedAddress(BaseModel):
    """Universal location envelope returned by every per-country searcher.

    Each implementation fills the subset of fields its country uses:

    - Portugal: `parish`, `municipality`, `district` are required (the
      searcher raises if the LLM can't supply them); the others are
      None.
    - United States (future): `city`, `state` required; PT-shaped
      fields are None.

    `country` is always present.

    NOTE: no `postal_code` field. Postal code is an *input* to the
    searcher (passed via `search(..., postal_code=...)` kwarg, used
    by the LLM prompt to anchor the parish/municipality/district
    answer) but it's never persisted to `property_listings`. Once the
    searcher has used it, its job is done — see spec
    `2026-05-property-address-enrichment-fix` §Non-goals.
    """

    country: str
    parish: str | None = None
    municipality: str | None = None
    district: str | None = None
    city: str | None = None
    state: str | None = None
    region: str | None = None


class AddressSearcher(Protocol):
    """Country-specific address resolution.

    The handler picks an implementation by country (via
    `select_address_searcher`) and calls `search(...)`. On failure
    (LLM returns null on any required field for the country, or the
    underlying API errors), the implementation raises — the handler's
    existing redrive-then-DLQ path handles the failure.
    """

    async def search(
        self,
        *,
        address: str,
        postal_code: str | None,
        country: str,
    ) -> ParsedAddress: ...
