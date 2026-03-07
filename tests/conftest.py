import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from core_api.adapters.inmemory.inmemory_company_repo import InMemoryCompanyRepository
from core_api.adapters.inmemory.inmemory_email_service import InMemoryEmailService
from core_api.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from core_api.adapters.inmemory.inmemory_notification_repo import InMemoryNotificationRepository
from core_api.adapters.inmemory.inmemory_subscription_repo import InMemorySubscriptionRepository
from core_api.adapters.inmemory.inmemory_user_repo import InMemoryUserRepository
from core_api.container import Container
from core_api.main import create_app

TEST_JWT_SECRET = "test-jwt-secret-for-testing-only"
TEST_SUPABASE_USER_ID = "00000000-0000-0000-0000-000000000001"


def make_test_token(sub: str = TEST_SUPABASE_USER_ID) -> str:
    return jwt.encode({"sub": sub, "aud": "authenticated"}, TEST_JWT_SECRET, algorithm="HS256")


@pytest.fixture
def user_repo():
    return InMemoryUserRepository()


@pytest.fixture
def company_repo():
    return InMemoryCompanyRepository()


@pytest.fixture
def subscription_repo():
    return InMemorySubscriptionRepository()


@pytest.fixture
def notification_repo():
    return InMemoryNotificationRepository()


@pytest.fixture
def email_service():
    return InMemoryEmailService()


@pytest.fixture
def event_bus():
    return InMemoryEventBus()


@pytest.fixture
def container(user_repo, company_repo, subscription_repo, notification_repo, email_service, event_bus):
    return Container(
        user_repo=user_repo,
        company_repo=company_repo,
        subscription_repo=subscription_repo,
        notification_repo=notification_repo,
        email_service=email_service,
        event_bus=event_bus,
    )


@pytest.fixture
def app(container, monkeypatch):
    monkeypatch.setattr("core_api.config.settings.supabase_jwt_secret", TEST_JWT_SECRET)
    return create_app(container=container)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers():
    token = make_test_token()
    return {"Authorization": f"Bearer {token}"}
