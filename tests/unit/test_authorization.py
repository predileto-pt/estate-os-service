from organizations.domain.models.authorization import has_permission
from organizations.domain.models.membership import MembershipRole


class TestHasPermission:
    def test_owner_has_all_permissions(self):
        assert has_permission(MembershipRole.OWNER, "organization.read")
        assert has_permission(MembershipRole.OWNER, "organization.update")
        assert has_permission(MembershipRole.OWNER, "member.invite")
        assert has_permission(MembershipRole.OWNER, "anything.at.all")

    def test_admin_has_org_and_member_permissions(self):
        assert has_permission(MembershipRole.ADMIN, "organization.read")
        assert has_permission(MembershipRole.ADMIN, "organization.update")
        assert has_permission(MembershipRole.ADMIN, "member.invite")
        assert has_permission(MembershipRole.ADMIN, "member.read")
        assert has_permission(MembershipRole.ADMIN, "member.update")
        assert has_permission(MembershipRole.ADMIN, "member.remove")

    def test_admin_has_wildcard_permissions(self):
        assert has_permission(MembershipRole.ADMIN, "property.create")
        assert has_permission(MembershipRole.ADMIN, "property.read")
        assert has_permission(MembershipRole.ADMIN, "extraction.create")

    def test_admin_cannot_manage_subscriptions_beyond_read(self):
        assert has_permission(MembershipRole.ADMIN, "subscription.read")
        assert not has_permission(MembershipRole.ADMIN, "subscription.update")

    def test_member_basic_permissions(self):
        assert has_permission(MembershipRole.MEMBER, "organization.read")
        assert has_permission(MembershipRole.MEMBER, "property.create")
        assert has_permission(MembershipRole.MEMBER, "property.read")
        assert has_permission(MembershipRole.MEMBER, "property.update")
        assert has_permission(MembershipRole.MEMBER, "extraction.create")
        assert has_permission(MembershipRole.MEMBER, "extraction.read")
        assert has_permission(MembershipRole.MEMBER, "subscription.read")

    def test_member_cannot_manage_org_or_members(self):
        assert not has_permission(MembershipRole.MEMBER, "organization.update")
        assert not has_permission(MembershipRole.MEMBER, "member.invite")
        assert not has_permission(MembershipRole.MEMBER, "member.update")
        assert not has_permission(MembershipRole.MEMBER, "member.remove")
