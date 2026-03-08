from core_api.application.ports.email_service import EmailService
from core_api.application.ports.event_bus import EventBus
from core_api.application.ports.repositories.applicant_repository import ApplicantRepository
from core_api.application.ports.repositories.company_repository import CompanyRepository
from core_api.application.ports.repositories.intake_form_request_repository import (
    IntakeFormRequestRepository,
)
from core_api.application.ports.repositories.notification_repository import NotificationRepository
from core_api.application.ports.repositories.subscription_repository import SubscriptionRepository
from core_api.application.ports.repositories.user_repository import UserRepository
from core_api.application.use_cases.get_user_profile import GetUserProfile
from core_api.application.use_cases.list_notifications import ListNotifications
from core_api.application.use_cases.manage_subscription import (
    CreateSubscription,
    UpdateSubscription,
)
from core_api.application.use_cases.mark_notifications_read import MarkNotificationsRead
from core_api.application.use_cases.process_screening_result import ProcessScreeningResult
from core_api.application.use_cases.register_user import RegisterUser
from core_api.application.use_cases.send_notification import SendNotification
from core_api.application.use_cases.update_company import UpdateCompany
from core_api.application.use_cases.update_user_profile import UpdateUserProfile


class Container:
    def __init__(
        self,
        user_repo: UserRepository,
        company_repo: CompanyRepository,
        subscription_repo: SubscriptionRepository,
        notification_repo: NotificationRepository,
        email_service: EmailService,
        event_bus: EventBus,
        applicant_repo: ApplicantRepository | None = None,
        intake_form_request_repo: IntakeFormRequestRepository | None = None,
    ) -> None:
        self.user_repo = user_repo
        self.company_repo = company_repo
        self.subscription_repo = subscription_repo
        self.notification_repo = notification_repo
        self.email_service = email_service
        self.event_bus = event_bus
        self.applicant_repo = applicant_repo
        self.intake_form_request_repo = intake_form_request_repo

        # Use cases
        self.register_user = RegisterUser(
            user_repo=user_repo,
            company_repo=company_repo,
            subscription_repo=subscription_repo,
            event_bus=event_bus,
        )
        self.get_user_profile = GetUserProfile(
            user_repo=user_repo,
            company_repo=company_repo,
        )
        self.update_user_profile = UpdateUserProfile(user_repo=user_repo)
        self.update_company = UpdateCompany(company_repo=company_repo)
        self.create_subscription = CreateSubscription(
            subscription_repo=subscription_repo,
            event_bus=event_bus,
        )
        self.update_subscription = UpdateSubscription(
            subscription_repo=subscription_repo,
            event_bus=event_bus,
        )
        self.list_notifications = ListNotifications(notification_repo=notification_repo)
        self.mark_notifications_read = MarkNotificationsRead(notification_repo=notification_repo)
        self.send_notification = SendNotification(
            notification_repo=notification_repo,
            event_bus=event_bus,
        )

        # Screening result processing (optional — only wired when repos are provided)
        if applicant_repo and intake_form_request_repo:
            self.process_screening_result = ProcessScreeningResult(
                applicant_repo=applicant_repo,
                intake_form_request_repo=intake_form_request_repo,
                event_bus=event_bus,
            )
