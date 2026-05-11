"""Session endpoints must reach handlers without an Authorization: Bearer header.

The global `JWTAuthMiddleware` would normally 401 any non-public request that
lacks `Authorization: Bearer ...`. The `/api/v1/session/` prefix is in
`shared.api.middleware.PUBLIC_PREFIXES`, so these endpoints bypass it.
"""


async def test_init_reachable_without_authorization_header(client):
    r = await client.post("/api/v1/session/init")
    # Specifically: not blocked by JWTAuthMiddleware with "Missing or invalid authorization header".
    assert r.status_code == 200, r.text


async def test_me_returns_401_session_missing_not_401_jwt(client):
    # No cookie, no auth header. JWT middleware would say "Missing or invalid
    # authorization header"; the session handler says SESSION_MISSING.
    r = await client.get("/api/v1/session/me")
    assert r.status_code == 401
    body = r.json()
    # Body is JSON from the session exception handler, not a plain-text JWT 401.
    assert "code" in body
    assert body["code"] in {"SESSION_MISSING", "SESSION_INVALID"}
