# Customers

The `customers` bounded context manages multi-tenant accounts: users, organizations, memberships, invitations, billing subscriptions, and in-app notifications. Every other context refers to organizations and users by UUID — this is where their lifecycle lives.

**Source:** `src/customers/`

## Domain entities

| Entity | Description |
|--------|-------------|
| `User` | Authenticated user backed by Supabase auth. Belongs to one organization via membership. |
| `PortalUser` | External/guest user with no organization (used by the applicant portal). |
| `Organization` | Tenant. Owns properties, subscriptions, members. |
| `Membership` | User-Organization link with a role (`OWNER`, `ADMIN`, `MEMBER`). |
| `Invitation` | Pending email invite with 7-day expiry. Status: `PENDING` / `ACCEPTED` / `EXPIRED` / `REVOKED`. |
| `Subscription` | Billing record. Plans: `FREEMIUM` / `PRO` / `ENTERPRISE`. Types: `STRIPE` / `MANUAL` / `DEPOSIT`. |
| `Notification` | In-app notification. Status: `UNREAD` / `READ`. |

Value objects: `PhoneNumber`, `Address` (in `domain/models/value_objects.py`).
Authorization rules: `domain/models/authorization.py` (`has_permission(role, permission)`).

## Events the context produces / consumes

Every event uses the shared `DomainEvent` envelope from `shared.events.base` with versioned `event_type` strings defined in `src/shared/events/types.py`. Post-ADR-008 the context has **no unique event producers** — the event-type constants below are reserved for publish sites that will be added as customer workflows grow:

- `USER_REGISTERED.v1`
- `MEMBER_INVITED.v1` / `MEMBER_JOINED.v1` / `MEMBER_REMOVED.v1` / `MEMBER_ROLE_CHANGED.v1`
- `SUBSCRIPTION_CREATED.v1` / `SUBSCRIPTION_UPDATED.v1`
- `NOTIFICATION_SENT.v1`

The context **consumes** `APPLICANT_SCREENED.v1` (see §Workers).

## Feature catalog

| Feature | Trigger | Purpose |
|---------|---------|---------|
| [RegisterUser](#registeruser) | `POST /api/v1/admin/auth/register` | Create user + organization + freemium subscription, or join via invitation |
| [RegisterPortalUser](#registerportaluser) | `POST /api/v1/portal/auth/register` | Create a portal user (no organization) |
| [GetUserProfile](#getuserprofile) | `GET /api/v1/admin/users/me` | Return current user + organization + role |
| [UpdateUserProfile](#updateuserprofile) | `PATCH /api/v1/admin/users/me` | Update user name and phone |
| [GetPortalUser](#getportaluser) | `GET /api/v1/portal/auth/me` | Return portal user profile |
| [GetOrganization](#getorganization) | `GET /api/v1/admin/organizations/{org_id}` | Return organization details (membership-gated) |
| [UpdateOrganization](#updateorganization) | `PATCH /api/v1/admin/organizations/{org_id}` | Update name, NIF, address |
| [ListMembers](#listmembers) | `GET /api/v1/admin/memberships?organization_id=` | List all members of an organization |
| [InviteMember](#invitemember) | `POST /api/v1/admin/invitations` | Invite a user by email with a role |
| [ListInvitations](#listinvitations) | `GET /api/v1/admin/invitations?organization_id=` | List all invitations for an org |
| [RevokeInvitation](#revokeinvitation) | `DELETE /api/v1/admin/invitations/{invitation_id}` | Revoke a pending invitation |
| [UpdateMemberRole](#updatememberrole) | `PATCH /api/v1/admin/memberships/{membership_id}` | Change a member's role (last-owner protected) |
| [RemoveMember](#removemember) | `DELETE /api/v1/admin/memberships/{membership_id}` | Remove a member (last-owner protected) |
| [CreateSubscription](#createsubscription) | `POST /api/v1/admin/subscriptions` | Create a subscription record |
| [UpdateSubscription](#updatesubscription) | `PATCH /api/v1/admin/subscriptions/{subscription_id}` | Update billing/Stripe data |
| [ListNotifications](#listnotifications) | `GET /api/v1/admin/notifications` | Paginated notifications for current user |
| [MarkNotificationsRead](#marknotificationsread) | `PATCH /api/v1/admin/notifications/read` | Mark a batch of notifications read |
| [SendNotification](#sendnotification) | `POST /api/v1/admin/notifications` | Create an in-app notification (internal callers) |

---

## Feature details

### RegisterUser

Create a new user. If the email has a pending invitation, joins that organization with the invited role. Otherwise creates a fresh organization, a freemium subscription, and assigns OWNER.

- **Inputs:** `supabase_user_id`, `email`, `name`, `organization_name?`, `phone?`, `google_metadata?`
- **Output:** `User`
- **Side effects:** writes `User`, `Organization` (or marks `Invitation` accepted), `Subscription`, `Membership`
- **Source:** `src/customers/application/use_cases/register_user.py`

### RegisterPortalUser

Register an external user (e.g., applicant) with no organization context.

- **Inputs:** `supabase_user_id`, `email`, `name`, `phone?`
- **Output:** `PortalUser`
- **Source:** `src/customers/application/use_cases/register_portal_user.py`

### GetUserProfile

Return the authenticated user along with their organization and role. Used by the dashboard on every page load.

- **Inputs:** `supabase_user_id`
- **Output:** `(User, Organization | None, Membership | None)`
- **Source:** `src/customers/application/use_cases/get_user_profile.py`

### UpdateUserProfile

Update the user's name and/or phone. Calls `User.update_profile()` on the domain model.

- **Inputs:** `user_id`, `name?`, `phone?`
- **Output:** `User`
- **Source:** `src/customers/application/use_cases/update_user_profile.py`

### GetPortalUser

Return the portal user profile by Supabase ID.

- **Inputs:** `supabase_user_id`
- **Output:** `PortalUser`
- **Source:** `src/customers/application/use_cases/get_portal_user.py`

### GetOrganization

Return organization details. Requires the requester to be a member.

- **Inputs:** `supabase_user_id`, `organization_id`
- **Output:** `Organization`
- **Raises:** `OrganizationNotFoundError`, `AuthorizationError`
- **Source:** `src/customers/application/use_cases/get_organization.py`

### UpdateOrganization

Update organization name, NIF, and address. Requires `organization.update` permission (OWNER or ADMIN).

- **Inputs:** `organization_id`, `supabase_user_id`, `name?`, `nif?`, `address?`
- **Output:** `Organization`
- **Source:** `src/customers/application/use_cases/update_organization.py`

### ListMembers

List all memberships for an organization. Requires the requester to be a member.

- **Inputs:** `supabase_user_id`, `organization_id`
- **Output:** `list[Membership]`
- **Source:** `src/customers/application/use_cases/list_members.py`

### InviteMember

Create a pending invitation with a 7-day expiry. The invitation token is `secrets.token_urlsafe(32)`.

- **Inputs:** `supabase_user_id`, `organization_id`, `email`, `role`
- **Output:** `Invitation`
- **Permission:** `member.invite`
- **Source:** `src/customers/application/use_cases/invite_member.py`

### ListInvitations

List all invitations for an organization (any status).

- **Inputs:** `supabase_user_id`, `organization_id`
- **Output:** `list[Invitation]`
- **Source:** `src/customers/application/use_cases/list_invitations.py`

### RevokeInvitation

Mark a pending invitation as `REVOKED`. The invitee can no longer accept it.

- **Inputs:** `supabase_user_id`, `invitation_id`
- **Output:** `Invitation`
- **Permission:** `member.invite`
- **Source:** `src/customers/application/use_cases/revoke_invitation.py`

### UpdateMemberRole

Change a member's role. Raises `LastOwnerError` if it would demote the last OWNER.

- **Inputs:** `supabase_user_id`, `membership_id`, `new_role`
- **Output:** `Membership`
- **Permission:** `member.update`
- **Events:** `MEMBER_ROLE_CHANGED.v1`
- **Source:** `src/customers/application/use_cases/update_member_role.py`

### RemoveMember

Remove a member from an organization. Raises `LastOwnerError` if it would remove the last OWNER.

- **Inputs:** `supabase_user_id`, `membership_id`
- **Output:** `None`
- **Permission:** `member.remove`
- **Events:** `MEMBER_REMOVED.v1`
- **Source:** `src/customers/application/use_cases/remove_member.py`

### CreateSubscription

Create a subscription for an organization. Defaults to active status with current period start = now.

- **Inputs:** `organization_id`, `plan`, `type`, `status?`, `stripe_subscription_id?`, `stripe_price_id?`, `current_period_start?`, `current_period_end?`
- **Output:** `Subscription`
- **Events:** `SUBSCRIPTION_CREATED.v1`
- **Source:** `src/customers/application/use_cases/manage_subscription.py`

### UpdateSubscription

Patch any subscription field. Used for Stripe webhooks and manual admin updates.

- **Inputs:** `subscription_id`, `status?`, `stripe_subscription_id?`, `stripe_price_id?`, `current_period_start?`, `current_period_end?`
- **Output:** `Subscription`
- **Events:** `SUBSCRIPTION_UPDATED.v1`
- **Source:** `src/customers/application/use_cases/manage_subscription.py`

### ListNotifications

Paginated list of notifications for the current user.

- **Inputs:** `user_id`, `limit?` (default 50, max 100), `offset?` (default 0)
- **Output:** `list[Notification]`
- **Source:** `src/customers/application/use_cases/list_notifications.py`

### MarkNotificationsRead

Mark a batch of notifications as `READ`. Returns the count updated.

- **Inputs:** `notification_ids`, `user_id`
- **Output:** `int`
- **Source:** `src/customers/application/use_cases/mark_notifications_read.py`

### SendNotification

Create an in-app notification for a user. Called by other use cases (e.g., after invitation, after screening) — not exposed externally to the public API.

- **Inputs:** `user_id`, `title`, `message`, `channel?` (default `"in_app"`)
- **Output:** `Notification`
- **Events:** `NOTIFICATION_SENT.v1`
- **Source:** `src/customers/application/use_cases/send_notification.py`

## Workers

`src/customers/adapters/workers/event_processor.py` exports `handle_applicant_screened` — the customers-side handler for `APPLICANT_SCREENED.v1` (sends a screening-complete email to the property owner). The handler runs on the shared `SQSWorker` (ADR-008), wired via `src/customers/entrypoints/worker.py --queue events`. The customers-events-queue is subscribed to the `domain-events-APPLICANT_SCREENED-v1` SNS topic.

## Container

`src/customers/container.py` wires 18 use cases to their port dependencies. The container is built once in `src/shared/entrypoints/bootstrap.py::get_container()` and stored on `app.state.container`.
