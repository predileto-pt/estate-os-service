import asyncio
import os
import subprocess

import boto3
import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy import text
from sqlalchemy.pool import NullPool
from testcontainers.localstack import LocalStackContainer
from testcontainers.postgres import PostgresContainer

from identity.adapters.database.user_repo import SqlAlchemyUserRepository
from organizations.adapters.database.repositories import (
    SqlAlchemyInvitationRepository,
    SqlAlchemyMembershipRepository,
    SqlAlchemyNotificationRepository,
    SqlAlchemyOrganizationRepository,
    SqlAlchemySubscriptionRepository,
)
from organizations.adapters.inmemory.inmemory_email_service import InMemoryEmailService
from organizations.container import Container
from properties.adapters.database.repositories import (
    SqlAlchemyDocumentContentRepository,
    SqlAlchemyExtractionJobRepository,
    SqlAlchemyPropertyRepository,
)
from properties.adapters.inmemory.inmemory_document_classifier import (
    InMemoryDocumentClassifier,
)
from properties.adapters.inmemory.inmemory_document_extractor import (
    InMemoryDocumentExtractor,
)
from properties.adapters.inmemory.inmemory_document_parser import InMemoryDocumentParser
from properties.adapters.inmemory.inmemory_places_service import InMemoryPlacesService
from properties.adapters.inmemory.inmemory_property_amenity_repo import (
    InMemoryPropertyAmenityRepository,
)
from properties.adapters.inmemory.inmemory_property_extractor import (
    InMemoryPropertyExtractor,
)
from properties.adapters.storage.s3_document_storage import S3DocumentStorage
from properties.container import Container as PropertyContainer
from shared.events.adapters.sqs_command_publisher import SQSCommandPublisher
from shared.main import create_app

TEST_JWT_SECRET = "e2e-test-jwt-secret"
TEST_SUPABASE_USER_ID = "00000000-0000-0000-0000-000000000099"


def make_test_token(sub: str = TEST_SUPABASE_USER_ID) -> str:
    return jwt.encode({"sub": sub, "aud": "authenticated"}, TEST_JWT_SECRET, algorithm="HS256")


# ── Postgres Container (session-scoped) ──────────────────────────────────────


@pytest.fixture(scope="session")
def postgres_url():
    with PostgresContainer("postgres:16") as pg:
        url = pg.get_connection_url()
        async_url = url.replace("psycopg2", "asyncpg")

        async def _create_auth_stubs():
            eng = create_async_engine(async_url, poolclass=NullPool)
            async with eng.begin() as conn:
                await conn.execute(text("CREATE SCHEMA IF NOT EXISTS auth;"))
                await conn.execute(
                    text(
                        "CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid "
                        "LANGUAGE sql STABLE AS $$ "
                        "SELECT '00000000-0000-0000-0000-000000000000'::uuid; $$;"
                    )
                )
                await conn.execute(
                    text(
                        "CREATE OR REPLACE FUNCTION auth.role() RETURNS text "
                        "LANGUAGE sql STABLE AS $$ "
                        "SELECT 'service_role'::text; $$;"
                    )
                )
            await eng.dispose()

        asyncio.run(_create_auth_stubs())

        env = {**os.environ, "DATABASE_URL": async_url}
        result = subprocess.run(
            ["uv", "run", "alembic", "upgrade", "head"],
            env=env,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Alembic migration failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )

        yield async_url


@pytest.fixture(scope="session")
def engine(postgres_url):
    eng = create_async_engine(postgres_url, poolclass=NullPool)
    yield eng
    asyncio.run(eng.dispose())


# ── LocalStack Container (session-scoped) ────────────────────────────────────


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
def s3_bucket(localstack_url):
    client = boto3.client(
        "s3",
        endpoint_url=localstack_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    bucket_name = "property-documents"
    client.create_bucket(Bucket=bucket_name)
    return bucket_name


@pytest.fixture(scope="session")
def sqs_queue_url(localstack_url):
    client = boto3.client(
        "sqs",
        endpoint_url=localstack_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    response = client.create_queue(QueueName="e2e-extraction-queue")
    return response["QueueUrl"]


@pytest.fixture(scope="session")
def sqs_client(localstack_url):
    return boto3.client(
        "sqs",
        endpoint_url=localstack_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )


# ── Session (function-scoped, rolled back after each test) ───────────────────


@pytest.fixture
async def session(engine):
    conn = await engine.connect()
    trans = await conn.begin()
    async_session = AsyncSession(bind=conn, expire_on_commit=False)
    try:
        yield async_session
    finally:
        await async_session.close()
        await trans.rollback()
        await conn.close()


# ── Containers wired with real repos ─────────────────────────────────────────


@pytest.fixture
def e2e_identity_container(session):
    from identity.container import Container as IdentityContainer

    return IdentityContainer(user_repo=SqlAlchemyUserRepository(session))


@pytest.fixture
def e2e_container(session, e2e_identity_container):
    return Container(
        user_repo=SqlAlchemyUserRepository(session),
        organization_repo=SqlAlchemyOrganizationRepository(session),
        subscription_repo=SqlAlchemySubscriptionRepository(session),
        notification_repo=SqlAlchemyNotificationRepository(session),
        membership_repo=SqlAlchemyMembershipRepository(session),
        invitation_repo=SqlAlchemyInvitationRepository(session),
        email_service=InMemoryEmailService(),
        register_user_port=e2e_identity_container.register_user_port,
    )


@pytest.fixture
def e2e_property_container(session, localstack_url, s3_bucket, sqs_queue_url):
    import aioboto3

    document_storage = S3DocumentStorage(
        bucket_name=s3_bucket,
        region="us-east-1",
        endpoint_url=localstack_url,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    boto_session = aioboto3.Session(
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )
    command_publisher = SQSCommandPublisher(
        session=boto_session,
        endpoint_url=localstack_url,
    )
    return PropertyContainer(
        property_repo=SqlAlchemyPropertyRepository(session),
        document_extractor=InMemoryDocumentExtractor(),
        document_storage=document_storage,
        property_extractor=InMemoryPropertyExtractor(),
        extraction_job_repo=SqlAlchemyExtractionJobRepository(session),
        command_publisher=command_publisher,
        extraction_queue_url=sqs_queue_url,
        document_classifier=InMemoryDocumentClassifier(),
        document_parser=InMemoryDocumentParser(),
        document_content_repo=SqlAlchemyDocumentContentRepository(session),
        places_service=InMemoryPlacesService(),
        amenity_repo=InMemoryPropertyAmenityRepository(),
    )


# ── App + Client ─────────────────────────────────────────────────────────────


@pytest.fixture
def app(e2e_container, e2e_property_container, monkeypatch):
    monkeypatch.setattr("shared.config.settings.supabase_jwt_secret", TEST_JWT_SECRET)
    return create_app(container=e2e_container, property_container=e2e_property_container)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers():
    token = make_test_token()
    return {"Authorization": f"Bearer {token}"}
