from __future__ import annotations

from typing import Protocol


class FileStoragePort(Protocol):
    async def upload(self, key: str, data: bytes, content_type: str) -> str: ...

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str: ...

    async def download(self, key: str) -> bytes: ...
