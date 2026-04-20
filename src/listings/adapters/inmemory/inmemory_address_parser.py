"""Deterministic fake address parser for tests.

Splits on `, ` and assigns the first three chunks to parish /
municipality / district. No LLM, no external calls, no rate limits.

Example:
    `"Arca, Ponte de Lima, Viana do Castelo"`
    -> ParsedAddress(parish="Arca", municipality="Ponte de Lima",
       district="Viana do Castelo")

    `"Rua Augusta 1, Lisboa"`
    -> ParsedAddress(parish="Rua Augusta 1", municipality="Lisboa",
       district=None)
"""

from __future__ import annotations

from listings.application.ports.address_parser import AddressParser, ParsedAddress


class InMemoryAddressParser(AddressParser):
    async def parse(self, address: str) -> ParsedAddress:
        chunks = [c.strip() for c in address.split(",") if c.strip()]
        parish = chunks[0] if len(chunks) >= 1 else None
        municipality = chunks[1] if len(chunks) >= 2 else None
        district = chunks[2] if len(chunks) >= 3 else None
        return ParsedAddress(parish=parish, municipality=municipality, district=district)
