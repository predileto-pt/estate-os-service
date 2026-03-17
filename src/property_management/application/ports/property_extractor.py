from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class PropertyExtractionResult:
    address: str
    description: str | None = None
    characteristics: dict | None = None
    extraction_reasoning: str | None = None


@dataclass
class GeoLocationResult:
    latitude: float | None = None
    longitude: float | None = None


class PropertyExtractorService(ABC):
    @abstractmethod
    async def extract(self, document_texts: list[str]) -> PropertyExtractionResult: ...

    @abstractmethod
    async def extract_geolocation(self, address: str) -> GeoLocationResult: ...
