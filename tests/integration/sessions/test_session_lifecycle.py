"""End-to-end lifecycle: init → me → patch → claim → logout."""

from uuid import uuid4


async def test_init_mints_cookie_and_anonymous_view(client):
    response = await client.post("/api/v1/session/init")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "ANONYMOUS"
    assert body["user_id"] is None
    assert "SAVE_FAVORITE" in body["capabilities"]
    assert "COMMENT" not in body["capabilities"]
    assert body["favorites"] == []
    assert body["prefs"] == {}

    # Cookie is set, HttpOnly + SameSite=Lax.
    set_cookie = response.headers.get("set-cookie", "")
    assert "predileto_session=" in set_cookie
    # Header casing depends on the server; Starlette emits e.g. "HttpOnly", "SameSite=lax".
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()
    assert "path=/" in set_cookie.lower()


async def test_init_with_valid_cookie_is_no_op(client):
    r1 = await client.post("/api/v1/session/init")
    assert r1.status_code == 200
    r2 = await client.post("/api/v1/session/init")
    assert r2.status_code == 200
    # No new Set-Cookie on the second call — the cookie was already valid.
    assert "set-cookie" not in {k.lower() for k in r2.headers.keys()}


async def test_me_returns_view_for_valid_cookie(client):
    await client.post("/api/v1/session/init")
    r = await client.get("/api/v1/session/me")
    assert r.status_code == 200
    assert r.json()["kind"] == "ANONYMOUS"


async def test_me_without_cookie_returns_401(client):
    # Don't init — no cookie sent.
    r = await client.get("/api/v1/session/me")
    assert r.status_code == 401
    body = r.json()
    assert body["code"] in {"SESSION_MISSING", "SESSION_INVALID"}


async def test_me_with_tampered_cookie_returns_session_invalid(client):
    await client.post("/api/v1/session/init")
    # Tamper with the cookie.
    cookie = client.cookies.get("predileto_session")
    assert cookie is not None
    head, sig, ver = cookie.split(".")
    tampered = f"{head}.{'A' * len(sig)}.{ver}"
    client.cookies.set("predileto_session", tampered)
    r = await client.get("/api/v1/session/me")
    assert r.status_code == 401
    assert r.json()["code"] == "SESSION_INVALID"


async def test_patch_favorites_and_prefs(client):
    await client.post("/api/v1/session/init")
    pid1 = str(uuid4())
    pid2 = str(uuid4())
    r = await client.patch(
        "/api/v1/session/me",
        json={
            "favorites": {"add": [pid1, pid2], "remove": []},
            "prefs": {"merge": {"theme": "dark"}},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["favorites"]) == {pid1, pid2}
    assert body["prefs"] == {"theme": "dark"}


async def test_patch_rejects_invalid_uuid(client):
    await client.post("/api/v1/session/init")
    r = await client.patch(
        "/api/v1/session/me",
        json={"favorites": {"add": ["not-a-uuid"], "remove": []}},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "INVALID_FAVORITE_ID"


async def test_patch_rejects_oversized_prefs(client):
    await client.post("/api/v1/session/init")
    big = {"k": "x" * 9000}
    r = await client.patch("/api/v1/session/me", json={"prefs": {"merge": big}})
    assert r.status_code == 400
    assert r.json()["code"] == "PREFS_TOO_LARGE"


async def test_claim_with_valid_token_flips_to_authenticated(client):
    from tests.integration.sessions.conftest import PORTAL_USER_ID, VALID_TOKEN

    await client.post("/api/v1/session/init")
    pid = str(uuid4())
    await client.patch("/api/v1/session/me", json={"favorites": {"add": [pid], "remove": []}})

    initial_cookie = client.cookies.get("predileto_session")
    r = await client.post(
        "/api/v1/session/claim",
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "AUTHENTICATED"
    assert body["user_id"] == str(PORTAL_USER_ID)
    # Cookie not rotated.
    assert client.cookies.get("predileto_session") == initial_cookie
    # Favorites preserved through claim.
    assert pid in body["favorites"]
    # Authenticated capabilities are present.
    assert "COMMENT" in body["capabilities"]


async def test_claim_with_unknown_token_returns_401(client):
    await client.post("/api/v1/session/init")
    r = await client.post(
        "/api/v1/session/claim",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401
    assert r.json()["code"] == "PORTAL_AUTH_TOKEN_INVALID"


async def test_claim_without_bearer_header_returns_401(client):
    await client.post("/api/v1/session/init")
    r = await client.post("/api/v1/session/claim")
    assert r.status_code == 401
    assert r.json()["code"] == "PORTAL_AUTH_TOKEN_INVALID"


async def test_logout_clears_favorites_and_prefs(client):
    from tests.integration.sessions.conftest import VALID_TOKEN

    await client.post("/api/v1/session/init")
    pid = str(uuid4())
    await client.patch(
        "/api/v1/session/me",
        json={
            "favorites": {"add": [pid], "remove": []},
            "prefs": {"merge": {"theme": "dark"}},
        },
    )
    await client.post(
        "/api/v1/session/claim",
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
    )
    initial_cookie = client.cookies.get("predileto_session")

    r = await client.post("/api/v1/session/logout")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "ANONYMOUS"
    assert body["user_id"] is None
    assert body["favorites"] == []
    assert body["prefs"] == {}
    # Cookie not rotated.
    assert client.cookies.get("predileto_session") == initial_cookie


async def test_logout_is_idempotent_on_anonymous_session(client):
    await client.post("/api/v1/session/init")
    r1 = await client.post("/api/v1/session/logout")
    r2 = await client.post("/api/v1/session/logout")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["kind"] == "ANONYMOUS"
    assert r2.json()["kind"] == "ANONYMOUS"
