from supabase import acreate_client

from customer_management.adapters.email.resend_email_service import ResendEmailService
from customer_management.adapters.inmemory.inmemory_event_bus import InMemoryEventBus
from customer_management.adapters.persistence.supabase_company_repo import SupabaseCompanyRepository
from customer_management.adapters.persistence.supabase_notification_repo import (
    SupabaseNotificationRepository,
)
from customer_management.adapters.persistence.supabase_subscription_repo import (
    SupabaseSubscriptionRepository,
)
from customer_management.adapters.persistence.supabase_user_repo import SupabaseUserRepository
from shared.config import Settings
from customer_management.container import Container
from property_management.adapters.ai.openai_document_classifier import OpenAIDocumentClassifier
from property_management.adapters.ai.openai_document_extractor import OpenAIDocumentExtractor
from property_management.adapters.ai.reducto_openai_property_extractor import (
    ReductoOpenAIPropertyExtractor,
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
        company_repo=SupabaseCompanyRepository(client),
        subscription_repo=SupabaseSubscriptionRepository(client),
        notification_repo=SupabaseNotificationRepository(client),
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

    property_extractor = ReductoOpenAIPropertyExtractor(
        reducto_api_key=settings.reducto_api_key,
        openai_api_key=settings.openai_api_key,
    )

    event_bus = SQSEventBus(
        queue_url=settings.sqs_property_extraction_queue_url,
        region=settings.aws_region,
        endpoint_url=settings.aws_endpoint_url,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    document_classifier = OpenAIDocumentClassifier(settings.openai_api_key)

    _property_container = PropertyContainer(
        property_repo=SupabasePropertyRepository(client),
        document_extractor=OpenAIDocumentExtractor(settings.openai_api_key),
        document_storage=document_storage,
        property_extractor=property_extractor,
        extraction_job_repo=SupabaseExtractionJobRepository(client),
        event_bus=event_bus,
        document_classifier=document_classifier,
    )
    return _property_container
