from properties.application.ports.document_storage import DocumentStorage


class InMemoryDocumentStorage(DocumentStorage):
    def __init__(self) -> None:
        self._files: dict[str, bytes] = {}

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        self._files[key] = data

    async def download(self, key: str) -> bytes:
        if key not in self._files:
            raise FileNotFoundError(f"File not found: {key}")
        return self._files[key]

    async def get_upload_url(self, key: str, content_type: str, expires_in: int = 300) -> str:
        return f"https://fake-presigned-url.test/{key}"

    async def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        return f"https://fake-download-url.test/{key}"

    def get_public_url(self, key: str) -> str:
        return f"https://fake-public-url.test/{key}"

    async def verify_exists(self, key: str) -> bool:
        return key in self._files

    async def delete(self, key: str) -> None:
        self._files.pop(key, None)
