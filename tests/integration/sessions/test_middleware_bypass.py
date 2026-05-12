"""Session endpoints must reach handlers without an Authorization: Bearer header.

The global `JWTAuthMiddleware` would normally 401 any non-public request that
lacks `Authorization: Bearer ...`. The `/api/v1/portal/session/` prefix is in
`shared.api.middleware.PUBLIC_PREFIXES`, so these endpoints bypass it.
"""


async def test_init_reachable_without_authorization_header(client):
    r = await client.post("/api/v1/portal/session/init")
    # Specifically: not blocked by JWTAuthMiddleware with "Missing or invalid authorization header".
    assert r.status_code == 200, r.text


async def test_me_auto_mints_when_no_cookie(client):
    # No cookie, no auth header. `/me` is the FE bootstrap endpoint —
    # it mints a fresh anonymous session in one round-trip, returns the
    # view, and sets the cookie. The 401-on-missing behaviour was changed
    # in favour of zero-friction anonymous browsing (a buyer hits the
    # portal, page loads, `/me` returns ANONYMOUS without a prior /init).
    r = await client.get("/api/v1/portal/session/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "ANONYMOUS"
    assert body["user_id"] is None
    # First hit sets a fresh cookie.
    assert "predileto_session" in r.headers.get("set-cookie", "")
