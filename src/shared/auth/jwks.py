"""Supabase JWKS fetcher with per-URL cache.

The cache **must be keyed by `supabase_url`** so admin and portal Supabase
projects don't fight over a single global cached key — see spec
`2026-05-portal-session-backend` §2.
"""

import httpx
import structlog
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jwt.algorithms import ECAlgorithm

log = structlog.get_logger()

_cached_public_keys: dict[str, str] = {}


async def fetch_jwks_public_key(supabase_url: str) -> str | None:
    """Fetch the ES256 public key from a given Supabase project's JWKS endpoint.

    Returns the PEM-encoded public key, or None if fetching fails. Cache is
    keyed by `supabase_url` so multiple projects (admin + portal) coexist.
    """
    cached = _cached_public_keys.get(supabase_url)
    if cached is not None:
        return cached

    jwks_url = f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(jwks_url)
            response.raise_for_status()

        jwks = response.json()
        for key_data in jwks.get("keys", []):
            if key_data.get("kty") == "EC" or key_data.get("use") == "sig":
                public_key = ECAlgorithm(ECAlgorithm.SHA256).from_jwk(key_data)
                pem = public_key.public_bytes(
                    encoding=Encoding.PEM,
                    format=PublicFormat.SubjectPublicKeyInfo,
                ).decode("utf-8")
                _cached_public_keys[supabase_url] = pem
                log.info("jwks_public_key_fetched", url=jwks_url)
                return pem

        log.warning("jwks_no_signing_key_found", url=jwks_url)
    except Exception as e:
        log.warning("jwks_fetch_failed", url=jwks_url, error=str(e))

    return None


def clear_cache() -> None:
    """Clear all cached public keys (useful for testing)."""
    _cached_public_keys.clear()
