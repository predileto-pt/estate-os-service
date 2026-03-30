from __future__ import annotations

from properties.application.ports.property_extractor import (
    GeoLocationResult,
    PropertyExtractionResult,
    PropertyExtractorService,
)


class InMemoryPropertyExtractor(PropertyExtractorService):
    async def extract(self, document_texts: list[str]) -> PropertyExtractionResult:
        return PropertyExtractionResult(
            address="Rua das Flores 123, 4000-001 Porto",
            description="Apartamento T2 com varanda no centro do Porto",
            characteristics={
                "area_in_m2": 85.0,
                "num_of_bedrooms": 2,
                "num_of_bathrooms": 1,
                "built_at": 2005,
                "energy_rating": "B",
                "floor": 3,
                "parking_spaces": 1,
                "has_elevator": True,
                "has_garden": False,
                "has_pool": False,
            },
            extraction_reasoning="Dados extraídos da escritura de compra e venda.",
        )

    async def extract_geolocation(self, address: str) -> GeoLocationResult:
        return GeoLocationResult(latitude=41.1579, longitude=-8.6291)
