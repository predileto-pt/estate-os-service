import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from organizations.domain.models.invitation import Invitation, InvitationStatus
from organizations.domain.models.membership import MembershipRole
from organizations.domain.models.organization import Organization
from organizations.domain.models.user import User
from organizations.domain.models.value_objects import PhoneNumber


def _make_organization(**overrides) -> Organization:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "created_by": uuid4(),
        "name": "Test Organization",
        "nif": "123456789",
        "address": "Rua do Teste 1, Lisboa",
        "created_at": now,
        "updated_at": now,
    }
    return Organization(**(defaults | overrides))


def _make_user(organization_id, **overrides) -> User:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "supabase_user_id": str(uuid4()),
        "email": f"user-{uuid4().hex[:8]}@test.com",
        "name": "Test User",
        "phone": PhoneNumber(country_code="+351", number="912345678"),
        "organization_id": organization_id,
        "google_metadata": None,
        "created_at": now,
        "updated_at": now,
    }
    return User(**(defaults | overrides))


def _make_invitation(organization_id, invited_by, **overrides) -> Invitation:
    now = datetime.now(timezone.utc)
    defaults = {
        "id": uuid4(),
        "organization_id": organization_id,
        "email": f"invite-{uuid4().hex[:8]}@test.com",
        "role": MembershipRole.MEMBER,
        "invited_by": invited_by,
        "token": secrets.token_urlsafe(32),
        "status": InvitationStatus.PENDING,
        "expires_at": now + timedelta(days=7),
        "created_at": now,
    }
    return Invitation(**(defaults | overrides))


async def test_save_and_get_invitation(organization_repo, user_repo, invitation_repo):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))
    invitation = _make_invitation(org.id, user.id)

    saved = await invitation_repo.save(invitation)
    assert saved.id == invitation.id
    assert saved.status == InvitationStatus.PENDING

    fetched = await invitation_repo.get_by_id(invitation.id)
    assert fetched is not None
    assert fetched.email == invitation.email
    assert fetched.role == MembershipRole.MEMBER


async def test_get_pending_by_email(organization_repo, user_repo, invitation_repo):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))
    email = "pending@test.com"
    invitation = _make_invitation(org.id, user.id, email=email)
    await invitation_repo.save(invitation)

    fetched = await invitation_repo.get_pending_by_email(email)
    assert fetched is not None
    assert fetched.email == email
    assert fetched.status == InvitationStatus.PENDING


async def test_get_pending_by_email_excludes_non_pending(
    organization_repo, user_repo, invitation_repo
):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))
    email = "accepted@test.com"

    # Save an accepted invitation
    invitation = _make_invitation(org.id, user.id, email=email, status=InvitationStatus.ACCEPTED)
    await invitation_repo.save(invitation)

    fetched = await invitation_repo.get_pending_by_email(email)
    assert fetched is None


async def test_get_pending_by_email_and_organization(organization_repo, user_repo, invitation_repo):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))
    email = "specific@test.com"
    invitation = _make_invitation(org.id, user.id, email=email)
    await invitation_repo.save(invitation)

    fetched = await invitation_repo.get_pending_by_email_and_organization(email, org.id)
    assert fetched is not None
    assert fetched.email == email
    assert fetched.organization_id == org.id


async def test_list_by_organization(organization_repo, user_repo, invitation_repo):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))

    for _ in range(3):
        await invitation_repo.save(_make_invitation(org.id, user.id))

    invitations = await invitation_repo.list_by_organization(org.id)
    assert len(invitations) == 3


async def test_update_invitation_status(organization_repo, user_repo, invitation_repo):
    org = await organization_repo.save(_make_organization())
    user = await user_repo.save(_make_user(org.id))
    invitation = _make_invitation(org.id, user.id)
    await invitation_repo.save(invitation)

    invitation.status = InvitationStatus.REVOKED
    updated = await invitation_repo.update(invitation)
    assert updated.status == InvitationStatus.REVOKED

    fetched = await invitation_repo.get_by_id(invitation.id)
    assert fetched.status == InvitationStatus.REVOKED
