import boto3
import pytest
from testcontainers.localstack import LocalStackContainer


@pytest.fixture(scope="session")
def localstack_container():
    with LocalStackContainer("localstack/localstack:latest") as container:
        yield container


@pytest.fixture(scope="session")
def localstack_url(localstack_container):
    host = localstack_container.get_container_host_ip()
    port = localstack_container.get_exposed_port(4566)
    return f"http://{host}:{port}"


@pytest.fixture(scope="session")
def aws_credentials():
    return {
        "aws_access_key_id": "test",
        "aws_secret_access_key": "test",
        "region_name": "us-east-1",
    }


@pytest.fixture(scope="session")
def s3_client(localstack_url, aws_credentials):
    return boto3.client("s3", endpoint_url=localstack_url, **aws_credentials)


@pytest.fixture(scope="session")
def sqs_client(localstack_url, aws_credentials):
    return boto3.client("sqs", endpoint_url=localstack_url, **aws_credentials)


@pytest.fixture(scope="session")
def s3_bucket(s3_client):
    bucket_name = "property-documents"
    s3_client.create_bucket(Bucket=bucket_name)
    return bucket_name


@pytest.fixture
def sqs_queue_url(sqs_client):
    import uuid

    queue_name = f"test-queue-{uuid.uuid4().hex[:8]}"
    response = sqs_client.create_queue(QueueName=queue_name)
    return response["QueueUrl"]
