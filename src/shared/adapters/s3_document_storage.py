import structlog
from aioboto3 import Session

from shared.ports.document_storage import DocumentStorage

log = structlog.get_logger()


class S3DocumentStorage(DocumentStorage):
    def __init__(
        self,
        bucket_name: str,
        region: str = "eu-west-1",
        endpoint_url: str | None = None,
        aws_access_key_id: str = "",
        aws_secret_access_key: str = "",
    ) -> None:
        self._bucket_name = bucket_name
        self._session = Session()
        self._config = {
            "region_name": region,
            "endpoint_url": endpoint_url,
            "aws_access_key_id": aws_access_key_id,
            "aws_secret_access_key": aws_secret_access_key,
        }

    async def upload(self, key: str, data: bytes, content_type: str) -> None:
        async with self._session.client("s3", **self._config) as s3:
            await s3.put_object(
                Bucket=self._bucket_name,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        log.info("s3.upload", key=key, size_bytes=len(data))

    async def download(self, key: str) -> bytes:
        async with self._session.client("s3", **self._config) as s3:
            response = await s3.get_object(Bucket=self._bucket_name, Key=key)
            data = await response["Body"].read()
        log.info("s3.download", key=key, size_bytes=len(data))
        return data

    async def get_upload_url(self, key: str, content_type: str, expires_in: int = 300) -> str:
        async with self._session.client("s3", **self._config) as s3:
            url = await s3.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket_name,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
        log.info("s3.presign", key=key)
        return url

    async def get_download_url(self, key: str, expires_in: int = 3600) -> str:
        async with self._session.client("s3", **self._config) as s3:
            url = await s3.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self._bucket_name,
                    "Key": key,
                },
                ExpiresIn=expires_in,
            )
        log.info("s3.presign_download", key=key)
        return url

    def get_public_url(self, key: str) -> str:
        """Return the **public**, non-presigned URL for a key.

        Pure string construction — no S3 round-trip. Bucket policy must allow
        public read for this to actually resolve in a browser (the property
        images bucket is configured that way). For private buckets / other
        contexts that want auth-gated downloads, use `get_download_url`.
        """
        endpoint = self._config.get("endpoint_url")
        if endpoint:
            # LocalStack / custom S3-compatible: path-style URL.
            return f"{endpoint.rstrip('/')}/{self._bucket_name}/{key}"
        # AWS: virtual-hosted-style URL.
        region = self._config.get("region_name") or "us-east-1"
        return f"https://{self._bucket_name}.s3.{region}.amazonaws.com/{key}"

    async def verify_exists(self, key: str) -> bool:
        async with self._session.client("s3", **self._config) as s3:
            try:
                await s3.head_object(Bucket=self._bucket_name, Key=key)
                return True
            except Exception:
                return False

    async def delete(self, key: str) -> None:
        async with self._session.client("s3", **self._config) as s3:
            try:
                await s3.delete_object(Bucket=self._bucket_name, Key=key)
                log.info("s3.delete", key=key)
            except Exception as exc:
                # Best-effort: missing objects are fine, but log other errors
                log.warning("s3.delete_failed", key=key, error=str(exc))
