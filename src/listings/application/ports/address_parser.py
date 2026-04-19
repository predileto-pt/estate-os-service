"""Address parser port for the listings read-model enrichment pipeline.

Called by the address-enrichment handler on every non-DELETED property
event. The handler takes the free-text `address` string carried in the
event payload and uses this port to resolve it to structured
parish/municipality/district columns. LLM-backed in prod; deterministic
fake in tests.
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class ParsedAddress(BaseModel):
    parish: str | None = None
    municipality: str | None = None
    district: str | None = None


class AddressParser(Protocol):
    async def parse(self, address: str) -> ParsedAddress: ...
