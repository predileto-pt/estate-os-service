"""Deterministic fake AddressSearcher for tests.

Implements `search(...)` for `country='Portugal'`. Splits the address
on `, ` and assigns the first three chunks to parish / municipality /
district. Raises if any of the three can't be synthesized (mirrors the
real PT searcher's failure semantics — null PT fields are an error).

For other countries: raises `NotImplementedError`.

Example:
    `"Arca, Ponte de Lima, Viana do Castelo"`
    -> ParsedAddress(country="Portugal", parish="Arca",
       municipality="Ponte de Lima", district="Viana do Castelo")

    `"Rua Augusta 1, Lisboa"`  (only 2 chunks)
    -> ValueError — district can't be synthesized.

Spec: `2026-05-property-address-enrichment-fix.md`
§Cross-cutting: in-memory test doubles.
"""

from __future__ import annotations

from listings.application.ports.address_searcher import AddressSearcher, ParsedAddress


class InMemoryAddressSearcher(AddressSearcher):
    async def search(
        self,
        *,
        address: str,
        postal_code: str | None,
        country: str,
    ) -> ParsedAddress:
        if country != "Portugal":
            raise NotImplementedError(
                f"InMemoryAddressSearcher only implements Portugal (got country={country!r})"
            )

        chunks = [c.strip() for c in address.split(",") if c.strip()]
        if len(chunks) < 3:
            raise ValueError(
                f"InMemoryAddressSearcher needs a "
                f"'Parish, Municipality, District' canonical address; "
                f"got {address!r}"
            )

        return ParsedAddress(
            country="Portugal",
            parish=chunks[0],
            municipality=chunks[1],
            district=chunks[2],
            postal_code=postal_code,
        )
