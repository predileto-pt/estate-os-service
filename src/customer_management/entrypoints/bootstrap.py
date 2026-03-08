from supabase import acreate_client

from customer_management.adapters.email.resend_email_service import ResendEmailService
from customer_management.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from customer_management.adapters.persistence.supabase_company_repo import SupabaseCompanyRepository
from customer_management.adapters.persistence.supabase_notification_repo import SupabaseNotificationRepository
from customer_management.adapters.persistence.supabase_subscription_repo import SupabaseSubscriptionRepository
from customer_management.adapters.persistence.supabase_user_repo import SupabaseUserRepository
from customer_management.config import Settings
from customer_management.container import Container

_container: Container | None = None


async def get_container() -> Container:
    global _container
    if _container is not None:
        return _container

    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)

    _container = Container(
        user_repo=SupabaseUserRepository(client),
        company_repo=SupabaseCompanyRepository(client),
        subscription_repo=SupabaseSubscriptionRepository(client),
        notification_repo=SupabaseNotificationRepository(client),
        email_service=ResendEmailService(settings.resend_api_key),
        event_bus=InMemoryEventBus(),
    )
    return _container
