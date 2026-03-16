from abc import ABC, abstractmethod


class DocumentDataExtractor(ABC):
    @abstractmethod
    async def extract_property_owner_data(self, file_bytes: bytes, content_type: str) -> dict: ...
