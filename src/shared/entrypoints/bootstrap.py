from supabase import acreate_client

from customer_management.adapters.email.resend_email_service import ResendEmailService
from customer_management.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from customer_management.adapters.persistence.supabase_invitation_repo import (
    SupabaseInvitationRepository,
)
from customer_management.adapters.persistence.supabase_membership_repo import (
    SupabaseMembershipRepository,
)
from customer_management.adapters.persistence.supabase_notification_repo import (
    SupabaseNotificationRepository,
)
from customer_management.adapters.persistence.supabase_organization_repo import (
    SupabaseOrganizationRepository,
)
from customer_management.adapters.persistence.supabase_subscription_repo import (
    SupabaseSubscriptionRepository,
)
from customer_management.adapters.persistence.supabase_user_repo import SupabaseUserRepository
from shared.config import Settings
from customer_management.container import Container
from property_management.adapters.ai.openai_id_document_extractor import OpenAIIdDocumentExtractor
from property_management.adapters.ai.openai_text_document_classifier import (
    OpenAITextDocumentClassifier,
)
from property_management.adapters.ai.reducto_document_parser import ReductoDocumentParser
from property_management.adapters.ai.reducto_openai_property_extractor import (
    ReductoOpenAIPropertyExtractor,
)
from property_management.adapters.persistence.supabase_document_content_repo import (
    SupabaseDocumentContentRepository,
)
from property_management.adapters.persistence.supabase_extraction_job_repo import (
    SupabaseExtractionJobRepository,
)
from property_management.adapters.persistence.supabase_property_repo import (
    SupabasePropertyRepository,
)
from property_management.adapters.queue.sqs_event_bus import SQSEventBus
from property_management.adapters.storage.s3_document_storage import S3DocumentStorage
from property_management.container import Container as PropertyContainer

_container: Container | None = None
_property_container: PropertyContainer | None = None


async def get_container() -> Container:
    global _container
    if _container is not None:
        return _container

    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)

    _container = Container(
        user_repo=SupabaseUserRepository(client),
        organization_repo=SupabaseOrganizationRepository(client),
        subscription_repo=SupabaseSubscriptionRepository(client),
        notification_repo=SupabaseNotificationRepository(client),
        membership_repo=SupabaseMembershipRepository(client),
        invitation_repo=SupabaseInvitationRepository(client),
        email_service=ResendEmailService(settings.resend_api_key),
        event_bus=InMemoryEventBus(),
    )
    return _container


async def get_property_container() -> PropertyContainer:
    global _property_container
    if _property_container is not None:
        return _property_container

    settings = Settings()
    client = await acreate_client(settings.supabase_url, settings.supabase_service_role_key)

    document_storage = S3DocumentStorage(
        bucket_name=settings.s3_bucket_name,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    document_parser = ReductoDocumentParser(
        reducto_api_key=settings.reducto_api_key,
    )

    property_extractor = ReductoOpenAIPropertyExtractor(
        openai_api_key=settings.openai_api_key,
    )

    event_bus = SQSEventBus(
        queue_url=settings.sqs_property_extraction_queue_url,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    document_classifier = OpenAITextDocumentClassifier(settings.openai_api_key)
    document_data_extractor = OpenAIIdDocumentExtractor(settings.openai_api_key)

    _property_container = PropertyContainer(
        property_repo=SupabasePropertyRepository(client),
        document_extractor=document_data_extractor,
        document_storage=document_storage,
        property_extractor=property_extractor,
        extraction_job_repo=SupabaseExtractionJobRepository(client),
        event_bus=event_bus,
        document_classifier=document_classifier,
        document_parser=document_parser,
        document_content_repo=SupabaseDocumentContentRepository(client),
    )
    return _property_container
