from datetime import datetime, timezone
from uuid import uuid4

from customers.domain.models.membership import Membership, MembershipRole
from customers.domain.models.notification import Notification, NotificationStatus
from customers.domain.models.organization import Organization
from customers.domain.models.subscription import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
    SubscriptionType,
)
from customers.domain.models.user import User
from customers.domain.models.value_objects import PhoneNumber


class TestUser:
    def test_create_user(self):
        now = datetime.now(timezone.utc)
        user = User(
            id=uuid4(),
            supabase_user_id="sup-123",
            email="test@example.com",
            name="Test User",
            phone=PhoneNumber(country_code="+351", number="912345678"),
            organization_id=uuid4(),
            google_metadata=None,
            created_at=now,
            updated_at=now,
        )
        assert user.email == "test@example.com"
        assert user.phone.country_code == "+351"

    def test_user_without_phone(self):
        now = datetime.now(timezone.utc)
        user = User(
            id=uuid4(),
            supabase_user_id="sup-123",
            email="test@example.com",
            name="Test User",
            phone=None,
            organization_id=uuid4(),
            google_metadata=None,
            created_at=now,
            updated_at=now,
        )
        assert user.phone is None


class TestOrganization:
    def test_create_organization(self):
        now = datetime.now(timezone.utc)
        org = Organization(
            id=uuid4(),
            created_by=uuid4(),
            name="Test Agency",
            nif="123456789",
            address="Rua Augusta 1, Lisboa, PT",
            created_at=now,
            updated_at=now,
        )
        assert org.name == "Test Agency"
        assert org.nif == "123456789"


class TestMembership:
    def test_create_membership(self):
        now = datetime.now(timezone.utc)
        membership = Membership(
            id=uuid4(),
            user_id=uuid4(),
            organization_id=uuid4(),
            role=MembershipRole.OWNER,
            created_at=now,
            updated_at=now,
        )
        assert membership.role == MembershipRole.OWNER

    def test_membership_roles(self):
        assert MembershipRole.OWNER.value == "owner"
        assert MembershipRole.ADMIN.value == "admin"
        assert MembershipRole.MEMBER.value == "member"


class TestSubscription:
    def test_create_subscription(self):
        now = datetime.now(timezone.utc)
        sub = Subscription(
            id=uuid4(),
            organization_id=uuid4(),
            plan=SubscriptionPlan.FREEMIUM,
            type=SubscriptionType.MANUAL,
            status=SubscriptionStatus.ACTIVE,
            stripe_subscription_id=None,
            stripe_price_id=None,
            current_period_start=now,
            current_period_end=None,
            created_at=now,
            updated_at=now,
        )
        assert sub.plan == SubscriptionPlan.FREEMIUM
        assert sub.status == SubscriptionStatus.ACTIVE

    def test_subscription_enums(self):
        assert SubscriptionPlan.PRO.value == "pro"
        assert SubscriptionType.STRIPE.value == "stripe"
        assert SubscriptionStatus.PAST_DUE.value == "past_due"


class TestNotification:
    def test_create_notification(self):
        now = datetime.now(timezone.utc)
        notif = Notification(
            id=uuid4(),
            user_id=uuid4(),
            title="Test",
            message="Test message",
            status=NotificationStatus.UNREAD,
            channel="in_app",
            created_at=now,
            read_at=None,
        )
        assert notif.status == NotificationStatus.UNREAD
        assert notif.read_at is None
