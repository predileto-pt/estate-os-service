from __future__ import annotations

import aioboto3


class S3FileStorage:
    def __init__(
        self,
        session: aioboto3.Session,
        *,
        bucket_name: str,
        endpoint_url: str | None = None,
    ) -> None:
        self._session = session
        self._bucket = bucket_name
        self._endpoint_url = endpoint_url

    async def upload(self, key: str, data: bytes, content_type: str) -> str:
        async with self._session.client("s3", endpoint_url=self._endpoint_url) as s3:
            await s3.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return f"s3://{self._bucket}/{key}"

    async def get_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        async with self._session.client("s3", endpoint_url=self._endpoint_url) as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=expires_in,
            )

    async def download(self, key: str) -> bytes:
        async with self._session.client("s3", endpoint_url=self._endpoint_url) as s3:
            response = await s3.get_object(Bucket=self._bucket, Key=key)
            return await response["Body"].read()
