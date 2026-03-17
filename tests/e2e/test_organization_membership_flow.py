import pytest


async def _register_user(client, auth_headers):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "Owner User",
            "email": "owner@e2e-org.pt",
            "organization_name": "E2E Organization",
            "nif": "123456789",
            "address": "Rua Augusta 1, PT",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.e2e
async def test_invite_and_list_invitations(client, auth_headers):
    user = await _register_user(client, auth_headers)
    org_id = user["organization_id"]

    # Invite a member
    invite_resp = await client.post(
        f"/api/v1/invitations?organization_id={org_id}",
        json={"email": "newmember@e2e-org.pt", "role": "member"},
        headers=auth_headers,
    )
    assert invite_resp.status_code == 201
    invite_data = invite_resp.json()
    assert invite_data["email"] == "newmember@e2e-org.pt"
    assert invite_data["status"] == "pending"

    # List invitations
    list_resp = await client.get(
        f"/api/v1/invitations?organization_id={org_id}",
        headers=auth_headers,
    )
    assert list_resp.status_code == 200
    invitations = list_resp.json()
    assert len(invitations) >= 1
    assert any(i["email"] == "newmember@e2e-org.pt" for i in invitations)


@pytest.mark.e2e
async def test_invite_and_revoke(client, auth_headers):
    user = await _register_user(client, auth_headers)
    org_id = user["organization_id"]

    # Invite
    invite_resp = await client.post(
        f"/api/v1/invitations?organization_id={org_id}",
        json={"email": "revoke-me@e2e-org.pt", "role": "member"},
        headers=auth_headers,
    )
    assert invite_resp.status_code == 201
    invitation_id = invite_resp.json()["id"]

    # Revoke
    revoke_resp = await client.delete(
        f"/api/v1/invitations/{invitation_id}",
        headers=auth_headers,
    )
    assert revoke_resp.status_code == 204
