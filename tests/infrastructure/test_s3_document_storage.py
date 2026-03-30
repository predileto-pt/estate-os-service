import uuid

from properties.adapters.storage.s3_document_storage import S3DocumentStorage


def _make_storage(localstack_url, s3_bucket) -> S3DocumentStorage:
    return S3DocumentStorage(
        bucket_name=s3_bucket,
        region="us-east-1",
        endpoint_url=localstack_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


async def test_upload_and_download(localstack_url, s3_bucket):
    storage = _make_storage(localstack_url, s3_bucket)
    key = f"test/{uuid.uuid4()}.pdf"
    data = b"fake pdf content"

    await storage.upload(key, data, "application/pdf")
    downloaded = await storage.download(key)

    assert downloaded == data


async def test_verify_exists_true(localstack_url, s3_bucket):
    storage = _make_storage(localstack_url, s3_bucket)
    key = f"test/{uuid.uuid4()}.pdf"

    await storage.upload(key, b"content", "application/pdf")
    assert await storage.verify_exists(key) is True


async def test_verify_exists_false(localstack_url, s3_bucket):
    storage = _make_storage(localstack_url, s3_bucket)
    key = f"test/{uuid.uuid4()}-nonexistent.pdf"

    assert await storage.verify_exists(key) is False


async def test_get_upload_url(localstack_url, s3_bucket):
    storage = _make_storage(localstack_url, s3_bucket)
    key = f"test/{uuid.uuid4()}.pdf"

    url = await storage.get_upload_url(key, "application/pdf")
    assert url is not None
    assert key in url
