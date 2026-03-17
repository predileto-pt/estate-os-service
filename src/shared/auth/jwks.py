import httpx
import structlog
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jwt.algorithms import ECAlgorithm

log = structlog.get_logger()

_cached_public_key: str | None = None


async def fetch_jwks_public_key(supabase_url: str) -> str | None:
    """Fetch the ES256 public key from Supabase's JWKS endpoint.

    Returns the PEM-encoded public key, or None if fetching fails.
    The result is cached after the first successful fetch.
    """
    global _cached_public_key
    if _cached_public_key is not None:
        return _cached_public_key

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
                _cached_public_key = pem
                log.info("jwks_public_key_fetched", url=jwks_url)
                return _cached_public_key

        log.warning("jwks_no_signing_key_found", url=jwks_url)
    except Exception as e:
        log.warning("jwks_fetch_failed", url=jwks_url, error=str(e))

    return None


def clear_cache() -> None:
    """Clear the cached public key (useful for testing)."""
    global _cached_public_key
    _cached_public_key = None
