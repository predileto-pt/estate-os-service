"""HMAC-SHA256 cookie signer with versioned keys.

Cookie value format: `base64url(uuid_bytes).base64url(hmac).N`
where N is the integer key version used to sign.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from uuid import UUID

from sessions.domain.exceptions import CookieMalformed, CookieSignatureInvalid
from sessions.domain.value_objects import SessionId


def _b64u_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


class HmacCookieSigner:
    def __init__(self, *, active_key_version: int, keys: dict[int, bytes]) -> None:
        if active_key_version not in keys:
            raise ValueError(f"active key version {active_key_version} not in keys {sorted(keys)}")
        self._active = active_key_version
        self._keys = dict(keys)

    @classmethod
    def from_env(cls, *, signing_keys: str, active_key: int) -> "HmacCookieSigner":
        """Parse `SESSION_SIGNING_KEYS=1:abc,2:def` into the signer."""
        keys: dict[int, bytes] = {}
        if not signing_keys.strip():
            raise ValueError("SESSION_SIGNING_KEYS is empty")
        for entry in signing_keys.split(","):
            entry = entry.strip()
            if not entry:
                continue
            version_str, _, key_b64 = entry.partition(":")
            if not version_str or not key_b64:
                raise ValueError(f"malformed signing key entry: {entry!r}")
            keys[int(version_str)] = _b64u_decode(key_b64)
        if active_key not in keys:
            raise ValueError(
                f"SESSION_SIGNING_ACTIVE_KEY={active_key} not in versions {sorted(keys)}"
            )
        return cls(active_key_version=active_key, keys=keys)

    def sign(self, session_id: SessionId) -> str:
        raw_id = session_id.bytes
        sig = hmac.new(self._keys[self._active], raw_id, hashlib.sha256).digest()
        return f"{_b64u_encode(raw_id)}.{_b64u_encode(sig)}.{self._active}"

    def verify(self, cookie_value: str) -> SessionId:
        parts = cookie_value.split(".")
        if len(parts) != 3:
            raise CookieMalformed(f"expected 3 parts, got {len(parts)}")
        id_b64, sig_b64, version_str = parts
        try:
            raw_id = _b64u_decode(id_b64)
            given_sig = _b64u_decode(sig_b64)
            version = int(version_str)
        except (ValueError, TypeError) as e:
            raise CookieMalformed(str(e)) from e
        if len(raw_id) != 16:
            raise CookieMalformed(f"id must be 16 bytes, got {len(raw_id)}")
        key = self._keys.get(version)
        if key is None:
            raise CookieSignatureInvalid(f"unknown key version {version}")
        expected_sig = hmac.new(key, raw_id, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_sig, given_sig):
            raise CookieSignatureInvalid("hmac mismatch")
        return SessionId(UUID(bytes=raw_id))
