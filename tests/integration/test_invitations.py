import pytest


async def _register_user(client, auth_headers):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "João Silva",
            "email": "joao@agency.pt",
            "organization_name": "Imobiliária Silva",
        },
        headers=auth_headers,
    )
    return response.json()


@pytest.mark.asyncio
async def test_invite_member(client, auth_headers):
    user = await _register_user(client, auth_headers)
    org_id = user["organization_id"]
    response = await client.post(
        f"/api/v1/invitations?organization_id={org_id}",
        json={"email": "invited@agency.pt", "role": "member"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "invited@agency.pt"
    assert data["role"] == "member"
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_list_invitations(client, auth_headers):
    user = await _register_user(client, auth_headers)
    org_id = user["organization_id"]

    # Invite someone
    await client.post(
        f"/api/v1/invitations?organization_id={org_id}",
        json={"email": "invited@agency.pt", "role": "member"},
        headers=auth_headers,
    )

    response = await client.get(
        f"/api/v1/invitations?organization_id={org_id}",
        headers=auth_headers,
    )
    assert response.status_code == 200
    invitations = response.json()
    assert len(invitations) == 1
    assert invitations[0]["email"] == "invited@agency.pt"


@pytest.mark.asyncio
async def test_revoke_invitation(client, auth_headers):
    user = await _register_user(client, auth_headers)
    org_id = user["organization_id"]

    # Invite someone
    invite_resp = await client.post(
        f"/api/v1/invitations?organization_id={org_id}",
        json={"email": "invited@agency.pt", "role": "admin"},
        headers=auth_headers,
    )
    invitation_id = invite_resp.json()["id"]

    # Revoke
    response = await client.delete(
        f"/api/v1/invitations/{invitation_id}",
        headers=auth_headers,
    )
    assert response.status_code == 204
