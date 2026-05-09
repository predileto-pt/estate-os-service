from datetime import datetime, timezone
from uuid import UUID, uuid4

import jwt
import pytest
from httpx import ASGITransport, AsyncClient

from identity.adapters.inmemory.inmemory_user_repo import (
    InMemoryUserRepository as InMemoryIdentityUserRepository,
)
from identity.container import Container as IdentityContainer
from organizations.adapters.inmemory.inmemory_email_service import InMemoryEmailService
from organizations.adapters.inmemory.inmemory_invitation_repo import (
    InMemoryInvitationRepository,
)
from organizations.adapters.inmemory.inmemory_membership_repo import (
    InMemoryMembershipRepository,
)
from organizations.adapters.inmemory.inmemory_notification_repo import (
    InMemoryNotificationRepository,
)
from organizations.adapters.inmemory.inmemory_organization_repo import (
    InMemoryOrganizationRepository,
)
from billing.adapters.inmemory.inmemory_subscription_repo import (
    InMemorySubscriptionRepository,
)
from organizations.adapters.inmemory.inmemory_user_repo import InMemoryUserRepository
from organizations.container import Container
from organizations.domain.models.membership import Membership, MembershipRole
from organizations.domain.models.user import User
from shared.main import create_app
from properties.adapters.inmemory.inmemory_document_extractor import (
    InMemoryDocumentExtractor,
)
from properties.adapters.inmemory.inmemory_document_storage import InMemoryDocumentStorage
from properties.adapters.inmemory.inmemory_extraction_job_repo import (
    InMemoryExtractionJobRepository,
)
from properties.adapters.inmemory.inmemory_property_extractor import (
    InMemoryPropertyExtractor,
)
from properties.adapters.inmemory.inmemory_document_classifier import (
    InMemoryDocumentClassifier,
)
from properties.adapters.inmemory.inmemory_document_content_repo import (
    InMemoryDocumentContentRepository,
)
from properties.adapters.inmemory.inmemory_document_parser import InMemoryDocumentParser
from properties.adapters.inmemory.inmemory_property_repo import InMemoryPropertyRepository
from properties.container import Container as PropertyContainer
from shared.events.adapters.inmemory_event_bus import InMemoryCommandPublisher

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
def membership_repo(organization_repo):
    # Passing organization_repo enables `list_by_user_id_with_org_names`
    # to resolve org names in-process — used by IdentityMiddleware tests
    # that seed memberships.
    return InMemoryMembershipRepository(organization_repo=organization_repo)


@pytest.fixture
def invitation_repo():
    return InMemoryInvitationRepository()


@pytest.fixture
def email_service():
    return InMemoryEmailService()


@pytest.fixture
def property_repo():
    return InMemoryPropertyRepository()


@pytest.fixture
def property_poi_repo():
    from properties.adapters.inmemory.inmemory_property_poi_repo import (
        InMemoryPropertyPoiRepository,
    )

    return InMemoryPropertyPoiRepository()


@pytest.fixture
def listing_repo():
    from listings.adapters.inmemory.inmemory_listing_repository import (
        InMemoryListingRepository,
    )

    return InMemoryListingRepository()


@pytest.fixture
def listing_container(listing_repo):
    from listings.adapters.inmemory.inmemory_address_parser import InMemoryAddressParser
    from listings.adapters.inmemory.inmemory_property_listing_repo import (
        InMemoryPropertyListingRepository,
    )
    from listings.container import Container as ListingContainer

    return ListingContainer(
        listing_repo=listing_repo,
        property_listing_repo=InMemoryPropertyListingRepository(),
        address_parser=InMemoryAddressParser(),
    )


@pytest.fixture
def document_extractor():
    return InMemoryDocumentExtractor()


@pytest.fixture
def identity_container():
    return IdentityContainer(user_repo=InMemoryIdentityUserRepository())


@pytest.fixture
def billing_gateway():
    from billing.adapters.inmemory.inmemory_billing_gateway import (
        InMemoryBillingGateway,
    )

    return InMemoryBillingGateway()


@pytest.fixture
def stripe_webhook_events_repo():
    from billing.adapters.inmemory.inmemory_stripe_webhook_events_repo import (
        InMemoryStripeWebhookEventsRepository,
    )

    return InMemoryStripeWebhookEventsRepository()


@pytest.fixture
def price_catalog():
    from billing.application.use_cases.price_catalog import PriceCatalog

    return PriceCatalog(
        pro_monthly="price_pro_monthly_test",
        pro_yearly="price_pro_yearly_test",
        enterprise_monthly="price_enterprise_monthly_test",
        enterprise_yearly="price_enterprise_yearly_test",
    )


@pytest.fixture
def billing_container(
    subscription_repo,
    billing_gateway,
    stripe_webhook_events_repo,
    price_catalog,
):
    from billing.container import Container as BillingContainer

    return BillingContainer(
        subscription_repo=subscription_repo,
        billing_gateway=billing_gateway,
        stripe_webhook_events_repo=stripe_webhook_events_repo,
        price_catalog=price_catalog,
        trial_period_days=7,
        checkout_success_url="http://test/billing/return?session_id={CHECKOUT_SESSION_ID}",
        checkout_cancel_url="http://test/dashboard/settings/subscriptions?checkout=cancelled",
        portal_return_url="http://test/dashboard/settings/subscriptions",
    )


@pytest.fixture
def container(
    user_repo,
    organization_repo,
    notification_repo,
    membership_repo,
    invitation_repo,
    email_service,
    identity_container,
    billing_container,
):
    return Container(
        user_repo=user_repo,
        organization_repo=organization_repo,
        notification_repo=notification_repo,
        membership_repo=membership_repo,
        invitation_repo=invitation_repo,
        email_service=email_service,
        register_user_port=identity_container.register_user_port,
        seed_freemium_subscription=billing_container.seed_freemium_subscription_port,
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
def command_publisher():
    return InMemoryCommandPublisher()


@pytest.fixture
def extraction_queue_url():
    return "test-extraction-queue"


@pytest.fixture
def enrichment_queue_url():
    return "test-enrichment-queue"


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
    property_poi_repo,
    document_extractor,
    document_storage,
    extraction_job_repo,
    property_extractor_service,
    command_publisher,
    extraction_queue_url,
    enrichment_queue_url,
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
        command_publisher=command_publisher,
        extraction_queue_url=extraction_queue_url,
        document_classifier=document_classifier,
        document_parser=document_parser,
        document_content_repo=document_content_repo,
        property_poi_repo=property_poi_repo,
        enrichment_queue_url=enrichment_queue_url,
    )


@pytest.fixture
def app(
    container,
    identity_container,
    billing_container,
    property_container,
    listing_container,
    monkeypatch,
):
    monkeypatch.setattr("shared.config.settings.supabase_jwt_secret", TEST_JWT_SECRET)
    return create_app(
        container=container,
        identity_container=identity_container,
        billing_container=billing_container,
        property_container=property_container,
        listing_container=listing_container,
    )


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers():
    token = make_test_token()
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def seed_test_member(user_repo, membership_repo, identity_container):
    """Seed the JWT test user + Membership in TEST_ORGANIZATION_ID.

    Property and extraction-job routes enforce org membership via
    `require_org_member` / `assert_org_member`. Tests that hit those routes
    with `auth_headers` must request this fixture (or autouse it) so the
    JWT's `sub` resolves to a real domain User with a Membership.

    The User is mirrored into both the identity container (for the
    middleware's `find_user.by_supabase_id` lookup) and the organizations
    container's UserRepository (for org-side use cases that read users
    by email/id).
    """
    from identity.domain.models.user import User as IdentityUser

    now = datetime.now(timezone.utc)
    test_user_id = UUID("00000000-0000-0000-0000-000000000001")
    test_org_id = UUID(TEST_ORGANIZATION_ID)
    user = User(
        id=test_user_id,
        supabase_user_id=TEST_SUPABASE_USER_ID,
        email="test@example.com",
        name="Test User",
        phone=None,
        google_metadata=None,
        created_at=now,
        updated_at=now,
    )
    await user_repo.save(user)
    identity_user = IdentityUser(
        id=test_user_id,
        supabase_user_id=TEST_SUPABASE_USER_ID,
        email="test@example.com",
        name="Test User",
        phone=None,
        google_metadata=None,
        created_at=now,
        updated_at=now,
    )
    await identity_container.user_repo.save(identity_user)
    membership = Membership(
        id=uuid4(),
        user_id=test_user_id,
        organization_id=test_org_id,
        role=MembershipRole.OWNER,
        created_at=now,
        updated_at=now,
    )
    await membership_repo.save(membership)
    return user, membership
