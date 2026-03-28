from customer_management.application.ports.email_service import EmailService
from customer_management.application.ports.event_bus import EventBus
from customer_management.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from customer_management.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from customer_management.application.ports.repositories.notification_repository import (
    NotificationRepository,
)
from customer_management.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from customer_management.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from customer_management.application.ports.repositories.portal_user_repository import (
    PortalUserRepository,
)
from customer_management.application.ports.repositories.user_repository import UserRepository
from customer_management.application.use_cases.get_organization import GetOrganization
from customer_management.application.use_cases.get_portal_user import GetPortalUser
from customer_management.application.use_cases.get_user_profile import GetUserProfile
from customer_management.application.use_cases.invite_member import InviteMember
from customer_management.application.use_cases.list_invitations import ListInvitations
from customer_management.application.use_cases.list_members import ListMembers
from customer_management.application.use_cases.list_notifications import ListNotifications
from customer_management.application.use_cases.manage_subscription import (
    CreateSubscription,
    UpdateSubscription,
)
from customer_management.application.use_cases.mark_notifications_read import MarkNotificationsRead
from customer_management.application.use_cases.register_portal_user import RegisterPortalUser
from customer_management.application.use_cases.register_user import RegisterUser
from customer_management.application.use_cases.remove_member import RemoveMember
from customer_management.application.use_cases.revoke_invitation import RevokeInvitation
from customer_management.application.use_cases.send_notification import SendNotification
from customer_management.application.use_cases.update_member_role import UpdateMemberRole
from customer_management.application.use_cases.update_organization import UpdateOrganization
from customer_management.application.use_cases.update_user_profile import UpdateUserProfile


class Container:
    def __init__(
        self,
        user_repo: UserRepository,
        organization_repo: OrganizationRepository,
        subscription_repo: SubscriptionRepository,
        notification_repo: NotificationRepository,
        membership_repo: MembershipRepository,
        invitation_repo: InvitationRepository,
        portal_user_repo: PortalUserRepository,
        email_service: EmailService,
        event_bus: EventBus,
    ) -> None:
        self.user_repo = user_repo
        self.organization_repo = organization_repo
        self.subscription_repo = subscription_repo
        self.notification_repo = notification_repo
        self.membership_repo = membership_repo
        self.invitation_repo = invitation_repo
        self.portal_user_repo = portal_user_repo
        self.email_service = email_service
        self.event_bus = event_bus

        # Use cases
        self.register_user = RegisterUser(
            user_repo=user_repo,
            organization_repo=organization_repo,
            subscription_repo=subscription_repo,
            membership_repo=membership_repo,
            invitation_repo=invitation_repo,
            event_bus=event_bus,
        )
        self.get_user_profile = GetUserProfile(
            user_repo=user_repo,
            organization_repo=organization_repo,
            membership_repo=membership_repo,
        )
        self.update_user_profile = UpdateUserProfile(user_repo=user_repo)
        self.get_organization = GetOrganization(
            organization_repo=organization_repo,
            user_repo=user_repo,
            membership_repo=membership_repo,
        )
        self.update_organization = UpdateOrganization(
            organization_repo=organization_repo,
            user_repo=user_repo,
            membership_repo=membership_repo,
        )
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
        self.invite_member = InviteMember(
            invitation_repo=invitation_repo,
            membership_repo=membership_repo,
            user_repo=user_repo,
            event_bus=event_bus,
        )
        self.list_members = ListMembers(
            membership_repo=membership_repo,
            user_repo=user_repo,
        )
        self.update_member_role = UpdateMemberRole(
            membership_repo=membership_repo,
            user_repo=user_repo,
            event_bus=event_bus,
        )
        self.remove_member = RemoveMember(
            membership_repo=membership_repo,
            user_repo=user_repo,
            event_bus=event_bus,
        )
        self.list_invitations = ListInvitations(
            invitation_repo=invitation_repo,
            membership_repo=membership_repo,
            user_repo=user_repo,
        )
        self.revoke_invitation = RevokeInvitation(
            invitation_repo=invitation_repo,
            membership_repo=membership_repo,
            user_repo=user_repo,
        )

        # Portal user use cases
        self.register_portal_user = RegisterPortalUser(
            portal_user_repo=portal_user_repo,
        )
        self.get_portal_user = GetPortalUser(
            portal_user_repo=portal_user_repo,
        )
