"""Shared Supabase JWT decoder.

Single helper used by both the admin path (`JWTAuthMiddleware`) and the
portal path (`SupabasePortalTokenValidator`). Parameterised by Supabase
project credentials so multiple projects coexist in one process.

Algorithm: try ES256 via JWKS first; fall back to HS256 with the shared
secret. Mirrors the behaviour previously inlined in `JWTAuthMiddleware`.
"""

import jwt

from shared.auth.jwks import fetch_jwks_public_key


async def decode_supabase_token(
    token: str,
    *,
    supabase_url: str,
    jwt_secret: str,
    audience: str = "authenticated",
) -> dict:
    """Decode a Supabase JWT against a specific project's credentials.

    Raises `jwt.InvalidTokenError` (or a subclass) on any failure.
    """
    # Try ES256 via JWKS public key first.
    if supabase_url:
        public_key = await fetch_jwks_public_key(supabase_url)
        if public_key:
            try:
                return jwt.decode(
                    token,
                    public_key,
                    algorithms=["ES256"],
                    audience=audience,
                )
            except jwt.InvalidTokenError:
                if not jwt_secret:
                    raise

    # HS256 fallback with shared secret.
    return jwt.decode(
        token,
        jwt_secret,
        algorithms=["HS256"],
        audience=audience,
    )
