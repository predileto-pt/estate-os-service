from abc import ABC, abstractmethod


class DocumentStorage(ABC):
    @abstractmethod
    async def upload(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    async def download(self, key: str) -> bytes: ...

    @abstractmethod
    async def get_upload_url(self, key: str, content_type: str, expires_in: int = 300) -> str: ...

    @abstractmethod
    async def verify_exists(self, key: str) -> bool: ...
