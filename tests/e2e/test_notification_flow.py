import pytest


async def _register_user(client, auth_headers):
    response = await client.post(
        "/api/v1/admin/auth/register",
        json={
            "name": "Notification User",
            "email": "notif@e2e-test.pt",
            "organization_name": "E2E Notifications",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.e2e
async def test_create_list_and_mark_read(client, auth_headers):
    user = await _register_user(client, auth_headers)
    user_id = user["id"]

    # Create notification
    create_resp = await client.post(
        "/api/v1/admin/notifications",
        json={
            "user_id": user_id,
            "title": "E2E Welcome!",
            "message": "Welcome to the E2E test",
            "channel": "in_app",
        },
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    notif = create_resp.json()
    assert notif["title"] == "E2E Welcome!"
    assert notif["status"] == "unread"

    # List notifications
    list_resp = await client.get("/api/v1/admin/notifications", headers=auth_headers)
    assert list_resp.status_code == 200
    notifications = list_resp.json()
    assert len(notifications) == 1

    # Mark as read
    read_resp = await client.patch(
        "/api/v1/admin/notifications/read",
        json={"notification_ids": [notif["id"]]},
        headers=auth_headers,
    )
    assert read_resp.status_code == 200
    assert read_resp.json()["marked_read"] == 1

    # Verify it's read
    list_resp = await client.get("/api/v1/admin/notifications", headers=auth_headers)
    assert list_resp.json()[0]["status"] == "read"
    assert list_resp.json()[0]["read_at"] is not None


@pytest.mark.e2e
async def test_list_notifications_empty(client, auth_headers):
    await _register_user(client, auth_headers)

    response = await client.get("/api/v1/admin/notifications", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []
