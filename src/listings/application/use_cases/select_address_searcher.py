"""Country-keyed dispatcher for `AddressSearcher` implementations.

Spec: `2026-05-property-address-enrichment-fix.md` §AddressSearcher.
v1 implements only Portugal; non-PT raises `NotImplementedError`.
"""

from __future__ import annotations

from listings.application.ports.address_searcher import AddressSearcher


def select_address_searcher(
    country: str,
    *,
    portugal: AddressSearcher,
) -> AddressSearcher:
    """Return the right `AddressSearcher` for the given country.

    The handler holds the concrete `portugal` searcher (built at
    container construction) and passes it via kwarg here. When future
    countries land, this function gains additional keyword args (one
    per country) and additional case branches.

    Raises `NotImplementedError` for any country other than Portugal
    in v1 — callers should let it propagate so the failure surfaces in
    Logfire and the SQS message redrives → DLQs.
    """
    if country == "Portugal":
        return portugal
    raise NotImplementedError(f"AddressSearcher not implemented for country={country!r}")
