from datetime import datetime, timezone
from uuid import uuid4

from customer_management.domain.models.company import Company
from customer_management.domain.models.notification import Notification, NotificationStatus
from customer_management.domain.models.user import User
from customer_management.domain.models.value_objects import PhoneNumber


def _make_company(**overrides) -> Company:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "user_id": uuid4(),
        "name": "Test Company",
        "nif": "123456789",
        "address": "Rua do Teste 1, Lisboa",
        "created_at": now,
        "updated_at": now,
    }
    return Company(**(defaults | overrides))


def _make_user(company_id, **overrides) -> User:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "supabase_user_id": str(uuid4()),
        "email": f"user-{uuid4().hex[:8]}@test.com",
        "name": "Test User",
        "phone": PhoneNumber(country_code="+351", number="912345678"),
        "company_id": company_id,
        "google_metadata": None,
        "created_at": now,
        "updated_at": now,
    }
    return User(**(defaults | overrides))


def _make_notification(user_id, **overrides) -> Notification:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "user_id": user_id,
        "title": "Test Notification",
        "message": "This is a test notification",
        "status": NotificationStatus.UNREAD,
        "channel": "in_app",
        "created_at": now,
        "read_at": None,
    }
    return Notification(**(defaults | overrides))


async def test_save_and_get_notification(company_repo, user_repo, notification_repo):
    company = await company_repo.save(_make_company())
    user = await user_repo.save(_make_user(company.id))
    notif = _make_notification(user.id)

    saved = await notification_repo.save(notif)
    assert saved.id == notif.id
    assert saved.status == NotificationStatus.UNREAD

    fetched = await notification_repo.get_by_id(notif.id)
    assert fetched is not None
    assert fetched.title == notif.title
    assert fetched.message == notif.message


async def test_list_by_user_id(company_repo, user_repo, notification_repo):
    company = await company_repo.save(_make_company())
    user = await user_repo.save(_make_user(company.id))

    # Save 3 notifications
    for i in range(3):
        await notification_repo.save(_make_notification(user.id, title=f"Notification {i}"))

    results = await notification_repo.list_by_user_id(user.id)
    assert len(results) == 3

    # Verify limit works
    limited = await notification_repo.list_by_user_id(user.id, limit=2)
    assert len(limited) == 2


async def test_mark_as_read(company_repo, user_repo, notification_repo):
    company = await company_repo.save(_make_company())
    user = await user_repo.save(_make_user(company.id))

    n1 = await notification_repo.save(_make_notification(user.id))
    n2 = await notification_repo.save(_make_notification(user.id))

    count = await notification_repo.mark_as_read([n1.id, n2.id], user.id)
    assert count == 2

    fetched = await notification_repo.get_by_id(n1.id)
    assert fetched.status == NotificationStatus.READ
    assert fetched.read_at is not None
