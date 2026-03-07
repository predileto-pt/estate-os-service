import pytest


async def _register_user(client, auth_headers):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "name": "João Silva",
            "email": "joao@agency.pt",
            "company_name": "Imobiliária Silva",
            "nif": "123456789",
            "address": "Rua Augusta 1, PT",
        },
        headers=auth_headers,
    )
    return response.json()


@pytest.mark.asyncio
async def test_list_notifications_empty(client, auth_headers):
    await _register_user(client, auth_headers)
    response = await client.get("/api/v1/notifications", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_and_list_notification(client, auth_headers):
    user = await _register_user(client, auth_headers)
    user_id = user["id"]

    # Create notification
    create_resp = await client.post(
        "/api/v1/notifications",
        json={
            "user_id": user_id,
            "title": "Welcome!",
            "message": "Welcome to Predileto",
            "channel": "in_app",
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    notif = create_resp.json()
    assert notif["title"] == "Welcome!"
    assert notif["status"] == "unread"

    # List
    list_resp = await client.get("/api/v1/notifications", headers=auth_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_mark_notifications_read(client, auth_headers):
    user = await _register_user(client, auth_headers)
    user_id = user["id"]

    # Create notification
    create_resp = await client.post(
        "/api/v1/notifications",
        json={
            "user_id": user_id,
            "title": "Test",
            "message": "Test message",
        },
        headers=auth_headers,
    )
    notif_id = create_resp.json()["id"]

    # Mark as read
    read_resp = await client.patch(
        "/api/v1/notifications/read",
        json={"notification_ids": [notif_id]},
        headers=auth_headers,
    )
    assert read_resp.status_code == 200
    assert read_resp.json()["marked_read"] == 1

    # Verify it's read
    list_resp = await client.get("/api/v1/notifications", headers=auth_headers)
    assert list_resp.json()[0]["status"] == "read"
    assert list_resp.json()[0]["read_at"] is not None
