from __future__ import annotations

from abc import ABC, abstractmethod


class FileStoragePort(ABC):
    @abstractmethod
    async def upload(self, key: str, data: bytes, content_type: str) -> str: ...

    @abstractmethod
    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str: ...

    @abstractmethod
    async def download(self, key: str) -> bytes: ...
