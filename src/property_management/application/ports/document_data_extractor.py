from abc import ABC, abstractmethod


class DocumentDataExtractor(ABC):
    @abstractmethod
    async def extract_property_owner_data(
        self, parsed_text: str, document_subtype: str
    ) -> dict: ...
