from __future__ import annotations

from property_management.application.ports.property_extractor import (
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
            owners=[
                {
                    "full_name": "Maria Silva Santos",
                    "civil_status": "married",
                    "address": "Rua das Flores 123, 4000-001 Porto",
                    "nif": "123456789",
                    "document_type": "cartao_cidadao",
                    "document_id": "12345678",
                    "issued_by": "Servicos de Identificacao Civil de Porto",
                    "issuing_district": "Porto",
                    "date_of_birth": "1985-06-15",
                }
            ],
            extraction_reasoning="Dados extraídos da escritura de compra e venda.",
        )
