from properties.application.ports.document_data_extractor import DocumentDataExtractor


class InMemoryDocumentExtractor(DocumentDataExtractor):
    async def extract_property_owner_data(self, parsed_text: str, document_subtype: str) -> dict:
        return {
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
