from abc import ABC, abstractmethod


class DocumentStorage(ABC):
    @abstractmethod
    async def upload(self, key: str, data: bytes, content_type: str) -> None: ...

    @abstractmethod
    async def download(self, key: str) -> bytes: ...

    @abstractmethod
    async def get_upload_url(self, key: str, content_type: str, expires_in: int = 300) -> str: ...

    @abstractmethod
    async def get_download_url(self, key: str, expires_in: int = 3600) -> str: ...

    @abstractmethod
    def get_public_url(self, key: str) -> str:
        """Return the **public, non-presigned** URL for a key.

        For property images the bucket is public, so we serve the raw S3 URL
        and skip the presign step entirely (zero network/auth cost per image).
        Sync because it's pure string construction — no I/O. Callers that
        need an expiring/authenticated URL keep using `get_download_url`.
        """
        ...

    @abstractmethod
    async def verify_exists(self, key: str) -> bool: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...
