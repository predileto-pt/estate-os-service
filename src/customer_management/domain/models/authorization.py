from customer_management.domain.models.membership import MembershipRole

ROLE_PERMISSIONS: dict[MembershipRole, set[str]] = {
    MembershipRole.OWNER: {"*"},
    MembershipRole.ADMIN: {
        "organization.read",
        "organization.update",
        "member.invite",
        "member.read",
        "member.update",
        "member.remove",
        "property.*",
        "extraction.*",
        "subscription.read",
    },
    MembershipRole.MEMBER: {
        "organization.read",
        "property.create",
        "property.read",
        "property.update",
        "extraction.create",
        "extraction.read",
        "subscription.read",
    },
}


def has_permission(role: MembershipRole, codename: str) -> bool:
    permissions = ROLE_PERMISSIONS.get(role, set())
    if "*" in permissions:
        return True
    if codename in permissions:
        return True
    # Check wildcard patterns (e.g., "property.*" matches "property.create")
    namespace = codename.rsplit(".", 1)[0] if "." in codename else codename
    return f"{namespace}.*" in permissions
