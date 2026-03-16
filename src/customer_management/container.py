from customer_management.application.ports.email_service import EmailService
from customer_management.application.ports.event_bus import EventBus
from customer_management.application.ports.repositories.company_repository import CompanyRepository
from customer_management.application.ports.repositories.notification_repository import (
    NotificationRepository,
)
from customer_management.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.application.use_cases.get_company import GetCompany
from customer_management.application.use_cases.get_user_profile import GetUserProfile
from customer_management.application.use_cases.list_notifications import ListNotifications
from customer_management.application.use_cases.manage_subscription import (
    CreateSubscription,
    UpdateSubscription,
)
from customer_management.application.use_cases.mark_notifications_read import MarkNotificationsRead
from customer_management.application.use_cases.register_user import RegisterUser
from customer_management.application.use_cases.send_notification import SendNotification
from customer_management.application.use_cases.update_company import UpdateCompany
from customer_management.application.use_cases.update_user_profile import UpdateUserProfile


class Container:
    def __init__(
        self,
        user_repo: UserRepository,
        company_repo: CompanyRepository,
        subscription_repo: SubscriptionRepository,
        notification_repo: NotificationRepository,
        email_service: EmailService,
        event_bus: EventBus,
    ) -> None:
        self.user_repo = user_repo
        self.company_repo = company_repo
        self.subscription_repo = subscription_repo
        self.notification_repo = notification_repo
        self.email_service = email_service
        self.event_bus = event_bus

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
        self.get_company = GetCompany(
            company_repo=company_repo,
            user_repo=user_repo,
        )
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
