# TLDR: Supabase JWT auth failing — HS256 vs ES256

## Symptom

All authenticated requests returned `401 Unauthorized` with:

```
The specified alg value is not allowed
```

## Root cause

Supabase signs user JWTs with **ES256** (ECDSA P-256), but the middleware was configured for **HS256** using `supabase_jwt_secret`. The HS256 secret from the Supabase dashboard is only valid for service-role tokens — user auth tokens use ES256 with a different key pair. The ES256 public key isn't exposed in the Supabase dashboard UI.

## Debugging

```bash
# Decoded a JWT from the browser to confirm the algorithm
# Header showed: {"alg": "ES256", "typ": "JWT"}

# Verified Supabase exposes the public key via JWKS
curl https://<project>.supabase.co/auth/v1/.well-known/jwks.json
# Returns: {"keys": [{"kty": "EC", "use": "sig", ...}]}
```

## Fix

Fetch the ES256 public key from Supabase's JWKS endpoint at runtime instead of relying on a manually configured secret.

**Files changed:**

- `src/shared/auth/jwks.py` (new) — fetches `{supabase_url}/auth/v1/.well-known/jwks.json`, extracts the EC signing key, converts JWK → PEM, caches in memory.
- `src/shared/api/middleware.py` — `_decode_token()` tries ES256 with the JWKS key first; if that fails and `supabase_jwt_secret` is set, falls back to HS256 (used by tests).
- `src/shared/config.py` — removed `supabase_jwt_public_key` field (no longer needed).

**Fallback chain:** JWKS ES256 → HS256 with `supabase_jwt_secret`. Tests monkeypatch the secret and generate HS256 tokens, so they work without a real Supabase instance.
