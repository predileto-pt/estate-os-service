import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from customer_management.adapters.inmemory.inmemory_email_service import InMemoryEmailService
from customer_management.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from customer_management.adapters.inmemory.inmemory_invitation_repo import (
    InMemoryInvitationRepository,
)
from customer_management.adapters.inmemory.inmemory_membership_repo import (
    InMemoryMembershipRepository,
)
from customer_management.adapters.inmemory.inmemory_notification_repo import (
    InMemoryNotificationRepository,
)
from customer_management.adapters.inmemory.inmemory_organization_repo import (
    InMemoryOrganizationRepository,
)
from customer_management.adapters.inmemory.inmemory_subscription_repo import (
    InMemorySubscriptionRepository,
)
from customer_management.adapters.inmemory.inmemory_user_repo import InMemoryUserRepository
from customer_management.container import Container
from shared.main import create_app
from property_management.adapters.inmemory.inmemory_document_extractor import (
    InMemoryDocumentExtractor,
)
from property_management.adapters.inmemory.inmemory_document_storage import InMemoryDocumentStorage
from property_management.adapters.inmemory.inmemory_event_bus import (
    InMemoryEventBus as PropertyInMemoryEventBus,
)
from property_management.adapters.inmemory.inmemory_extraction_job_repo import (
    InMemoryExtractionJobRepository,
)
from property_management.adapters.inmemory.inmemory_property_extractor import (
    InMemoryPropertyExtractor,
)
from property_management.adapters.inmemory.inmemory_document_classifier import (
    InMemoryDocumentClassifier,
)
from property_management.adapters.inmemory.inmemory_document_content_repo import (
    InMemoryDocumentContentRepository,
)
from property_management.adapters.inmemory.inmemory_document_parser import InMemoryDocumentParser
from property_management.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from property_management.container import Container as PropertyContainer

TEST_JWT_SECRET = "test-jwt-secret-for-testing-only"
TEST_SUPABASE_USER_ID = "00000000-0000-0000-0000-000000000001"
TEST_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000010"


def make_test_token(sub: str = TEST_SUPABASE_USER_ID) -> str:
    return jwt.encode({"sub": sub, "aud": "authenticated"}, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def user_repo():
    return InMemoryUserRepository()


@pytest.fixture
def organization_repo():
    return InMemoryOrganizationRepository()


@pytest.fixture
def subscription_repo():
    return InMemorySubscriptionRepository()


@pytest.fixture
def notification_repo():
    return InMemoryNotificationRepository()


@pytest.fixture
def membership_repo():
    return InMemoryMembershipRepository()


@pytest.fixture
def invitation_repo():
    return InMemoryInvitationRepository()


@pytest.fixture
def email_service():
    return InMemoryEmailService()


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def property_repo():
    return InMemoryPropertyRepository()


@pytest.fixture
def document_extractor():
    return InMemoryDocumentExtractor()


@pytest.fixture
def container(
    user_repo,
    organization_repo,
    subscription_repo,
    notification_repo,
    membership_repo,
    invitation_repo,
    email_service,
    event_bus,
):
    return Container(
        user_repo=user_repo,
        organization_repo=organization_repo,
        subscription_repo=subscription_repo,
        notification_repo=notification_repo,
        membership_repo=membership_repo,
        invitation_repo=invitation_repo,
        email_service=email_service,
        event_bus=event_bus,
    )


@pytest.fixture
def document_storage():
    return InMemoryDocumentStorage()


@pytest.fixture
def extraction_job_repo():
    return InMemoryExtractionJobRepository()


@pytest.fixture
def property_extractor_service():
    return InMemoryPropertyExtractor()


@pytest.fixture
def property_event_bus():
    return PropertyInMemoryEventBus()


@pytest.fixture
def document_classifier():
    return InMemoryDocumentClassifier()


@pytest.fixture
def document_parser():
    return InMemoryDocumentParser()


@pytest.fixture
def document_content_repo():
    return InMemoryDocumentContentRepository()


@pytest.fixture
def property_container(
    property_repo,
    document_extractor,
    document_storage,
    extraction_job_repo,
    property_extractor_service,
    property_event_bus,
    document_classifier,
    document_parser,
    document_content_repo,
):
    return PropertyContainer(
        property_repo=property_repo,
        document_extractor=document_extractor,
        document_storage=document_storage,
        property_extractor=property_extractor_service,
        extraction_job_repo=extraction_job_repo,
        event_bus=property_event_bus,
        document_classifier=document_classifier,
        document_parser=document_parser,
        document_content_repo=document_content_repo,
    )


@pytest.fixture
def app(container, property_container, monkeypatch):
    monkeypatch.setattr("shared.config.settings.supabase_jwt_secret", TEST_JWT_SECRET)
    return create_app(container=container, property_container=property_container)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers():
    token = make_test_token()
    return {"Authorization": f"Bearer {token}"}
