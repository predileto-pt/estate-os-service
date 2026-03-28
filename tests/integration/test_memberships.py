import pytest


async def _register_user(client, auth_headers):
    response = await client.post(
        "/api/v1/admin/auth/register",
        json={
            "name": "João Silva",
            "email": "joao@agency.pt",
            "organization_name": "Imobiliária Silva",
        },
        headers=auth_headers,
    )
    return response.json()


@pytest.mark.asyncio
async def test_list_members(client, auth_headers):
    user = await _register_user(client, auth_headers)
    org_id = user["organization_id"]
    response = await client.get(
        f"/api/v1/admin/memberships?organization_id={org_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    members = response.json()
    assert len(members) == 1
    assert members[0]["role"] == "owner"
    assert members[0]["user_id"] == user["id"]


@pytest.mark.asyncio
async def test_update_member_role(client, auth_headers, membership_repo):
    user = await _register_user(client, auth_headers)
    org_id = user["organization_id"]

    # Register a second user to update

    # Get the first membership to verify we can't demote the only owner
    response = await client.get(
        f"/api/v1/admin/memberships?organization_id={org_id}",
        headers=auth_headers,
    )
    owner_membership_id = response.json()[0]["id"]

    # Try to demote the only owner — should fail
    response = await client.patch(
        f"/api/v1/admin/memberships/{owner_membership_id}",
        json={"role": "member"},
        headers=auth_headers,
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_remove_last_owner_fails(client, auth_headers):
    user = await _register_user(client, auth_headers)
    org_id = user["organization_id"]

    response = await client.get(
        f"/api/v1/admin/memberships?organization_id={org_id}",
        headers=auth_headers,
    )
    owner_membership_id = response.json()[0]["id"]

    response = await client.delete(
        f"/api/v1/admin/memberships/{owner_membership_id}",
        headers=auth_headers,
    )
    assert response.status_code == 409
