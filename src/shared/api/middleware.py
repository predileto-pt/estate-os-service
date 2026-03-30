import jwt
import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from shared.auth.jwks import fetch_jwks_public_key
from shared.config import settings

log = structlog.get_logger()

PUBLIC_PATHS = {
    "/api/v1/health",
    "/api/v1/admin/subscriptions/plans",
    "/api/v1/admin/properties/active",
    "/api/v1/portal/bookings",
    "/docs",
    "/openapi.json",
}


class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def _decode_token(self, token: str) -> dict:
        """Decode JWT, trying ES256 via JWKS first, then HS256 fallback."""
        # Try ES256 with JWKS public key
        if settings.supabase_url:
            public_key = await fetch_jwks_public_key(settings.supabase_url)
            if public_key:
                try:
                    return jwt.decode(
                        token, public_key, algorithms=["ES256"], audience="authenticated"
                    )
                except jwt.InvalidTokenError:
                    if not settings.supabase_jwt_secret:
                        raise

        # Fallback to HS256 with shared secret
        return jwt.decode(
            token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated"
        )

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return Response(status_code=401, content="Missing or invalid authorization header")

        token = auth_header.removeprefix("Bearer ")
        try:
            payload = await self._decode_token(token)
            request.state.supabase_user_id = payload["sub"]
        except jwt.InvalidTokenError as e:
            log.warning("jwt_invalid", error=str(e))
            return Response(status_code=401, content="Invalid token")

        return await call_next(request)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        log.info("request_started", method=request.method, path=request.url.path)
        response = await call_next(request)
        log.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
        )
        return response
