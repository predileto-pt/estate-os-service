"""Organizations bounded context container.

Owns Organization, Membership, Invitation, Subscription, Notification.

Depends on the identity context via a single callable Protocol —
`RegisterUserPort` — injected at construction time (no direct imports
of identity's use cases or domain classes). Identity's `UserLookupById`
is not currently consumed by any organizations use case; we re-inject
it when invitation-email-rendering needs it.
"""

from organizations.application.ports.email_service import EmailService
from organizations.application.ports.repositories.invitation_repository import (
    InvitationRepository,
)
from organizations.application.ports.repositories.membership_repository import (
    MembershipRepository,
)
from organizations.application.ports.repositories.notification_repository import (
    NotificationRepository,
)
from organizations.application.ports.repositories.organization_repository import (
    OrganizationRepository,
)
from organizations.application.ports.repositories.portal_user_repository import (
    PortalUserRepository,
)
from organizations.application.ports.repositories.subscription_repository import (
    SubscriptionRepository,
)
from organizations.application.ports.repositories.user_repository import UserRepository
from organizations.application.use_cases.get_organization import GetOrganization
from organizations.application.use_cases.invite_member import InviteMember
from organizations.application.use_cases.list_invitations import ListInvitations
from organizations.application.use_cases.list_members import ListMembers
from organizations.application.use_cases.list_notifications import ListNotifications
from organizations.application.use_cases.manage_subscription import (
    CreateSubscription,
    UpdateSubscription,
)
from organizations.application.use_cases.mark_notifications_read import MarkNotificationsRead
from organizations.application.use_cases.register_admin_account import (
    RegisterAdminAccount,
    RegisterUserPort,
)
from organizations.application.use_cases.remove_member import RemoveMember
from organizations.application.use_cases.revoke_invitation import RevokeInvitation
from organizations.application.use_cases.send_notification import SendNotification
from organizations.application.use_cases.update_member_role import UpdateMemberRole
from organizations.application.use_cases.update_organization import UpdateOrganization


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
        register_user_port: RegisterUserPort,
    ) -> None:
        self.user_repo = user_repo
        self.organization_repo = organization_repo
        self.subscription_repo = subscription_repo
        self.notification_repo = notification_repo
        self.membership_repo = membership_repo
        self.invitation_repo = invitation_repo
        self.portal_user_repo = portal_user_repo
        self.email_service = email_service

        # Cross-context: compound admin registration uses identity's
        # RegisterUser via the callable Protocol.
        self.register_admin_account = RegisterAdminAccount(
            register_user_port=register_user_port,
            organization_repo=organization_repo,
            membership_repo=membership_repo,
            subscription_repo=subscription_repo,
            invitation_repo=invitation_repo,
        )

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
        )
        self.update_subscription = UpdateSubscription(
            subscription_repo=subscription_repo,
        )
        self.list_notifications = ListNotifications(notification_repo=notification_repo)
        self.mark_notifications_read = MarkNotificationsRead(notification_repo=notification_repo)
        self.send_notification = SendNotification(
            notification_repo=notification_repo,
        )
        self.invite_member = InviteMember(
            invitation_repo=invitation_repo,
            membership_repo=membership_repo,
            user_repo=user_repo,
        )
        self.list_members = ListMembers(
            membership_repo=membership_repo,
            user_repo=user_repo,
        )
        self.update_member_role = UpdateMemberRole(
            membership_repo=membership_repo,
            user_repo=user_repo,
        )
        self.remove_member = RemoveMember(
            membership_repo=membership_repo,
            user_repo=user_repo,
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
