from supabase import acreate_client

from core_api.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from core_api.adapters.persistence.supabase_applicant_repo import SupabaseApplicantRepository
from core_api.adapters.persistence.supabase_intake_form_request_repo import (
    SupabaseIntakeFormRequestRepository,
)
from core_api.config import Settings
from core_api.container import Container

_container: Container | None = None


async def get_container() -> Container:
    global _container
    if _container is not None:
        return _container

    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)

    _container = Container(
        user_repo=None,  # type: ignore[arg-type]
        company_repo=None,  # type: ignore[arg-type]
        subscription_repo=None,  # type: ignore[arg-type]
        notification_repo=None,  # type: ignore[arg-type]
        email_service=None,  # type: ignore[arg-type]
        event_bus=InMemoryEventBus(),
        applicant_repo=SupabaseApplicantRepository(client),
        intake_form_request_repo=SupabaseIntakeFormRequestRepository(client),
    )
    return _container
