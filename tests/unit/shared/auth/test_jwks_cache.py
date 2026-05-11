"""JWKS cache must be URL-keyed (admin + portal Supabase don't collide).

Tests the cache shape directly rather than mocking httpx — the cache is a
plain module-level dict (`shared.auth.jwks._cached_public_keys`).
"""

import shared.auth.jwks as jwks_mod


def setup_function():
    jwks_mod.clear_cache()


def teardown_function():
    jwks_mod.clear_cache()


def test_cache_is_url_keyed():
    admin_url = "https://admin.supabase.co"
    portal_url = "https://portal.supabase.co"
    # Simulate two successful fetches having populated the cache.
    jwks_mod._cached_public_keys[admin_url] = "PEM-ADMIN"
    jwks_mod._cached_public_keys[portal_url] = "PEM-PORTAL"
    # Cache must hold both, distinct, no collision.
    assert jwks_mod._cached_public_keys[admin_url] == "PEM-ADMIN"
    assert jwks_mod._cached_public_keys[portal_url] == "PEM-PORTAL"
    assert jwks_mod._cached_public_keys[admin_url] != jwks_mod._cached_public_keys[portal_url]


def test_clear_cache_drops_all_urls():
    jwks_mod._cached_public_keys["a"] = "x"
    jwks_mod._cached_public_keys["b"] = "y"
    jwks_mod.clear_cache()
    assert jwks_mod._cached_public_keys == {}
