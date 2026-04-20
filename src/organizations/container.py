"""Organizations bounded context container.

Owns Organization, Membership, Invitation, Notification.

Depends on two other contexts via callable Protocols, injected at
container construction time (no direct imports of other contexts'
domain classes from organizations business code):

- `RegisterUserPort` (from identity) — used by RegisterAdminAccount to
  create the User row idempotently.
- `SeedFreemiumSubscription` (from billing) — used by RegisterAdminAccount
  to create the default freemium Subscription row for the new org.

Subscription / Stripe / Billing concerns live in `src/billing/`.
"""

from billing.application.ports.seed_freemium_subscription import (
    SeedFreemiumSubscription,
)
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
from organizations.application.ports.repositories.user_repository import UserRepository
from organizations.application.use_cases.get_organization import GetOrganization
from organizations.application.use_cases.invite_member import InviteMember
from organizations.application.use_cases.list_invitations import ListInvitations
from organizations.application.use_cases.list_members import ListMembers
from organizations.application.use_cases.list_notifications import ListNotifications
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
        notification_repo: NotificationRepository,
        membership_repo: MembershipRepository,
        invitation_repo: InvitationRepository,
        email_service: EmailService,
        register_user_port: RegisterUserPort,
        seed_freemium_subscription: SeedFreemiumSubscription,
    ) -> None:
        self.user_repo = user_repo
        self.organization_repo = organization_repo
        self.notification_repo = notification_repo
        self.membership_repo = membership_repo
        self.invitation_repo = invitation_repo
        self.email_service = email_service

        # Cross-context: compound admin registration uses identity's
        # RegisterUser + billing's SeedFreemiumSubscription via callable Protocols.
        self.register_admin_account = RegisterAdminAccount(
            register_user_port=register_user_port,
            seed_freemium_subscription=seed_freemium_subscription,
            organization_repo=organization_repo,
            membership_repo=membership_repo,
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
