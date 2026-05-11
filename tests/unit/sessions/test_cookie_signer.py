"""HMAC cookie signer round-trip + rotation + tamper-detection."""

import base64
from uuid import uuid4

import pytest

from sessions.adapters.signing.hmac_cookie_signer import HmacCookieSigner
from sessions.domain.exceptions import CookieMalformed, CookieSignatureInvalid
from sessions.domain.value_objects import SessionId


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def test_sign_then_verify_round_trip():
    signer = HmacCookieSigner(active_key_version=1, keys={1: b"secret-key-v1!!"})
    sid = SessionId(uuid4())
    cookie = signer.sign(sid)
    assert signer.verify(cookie) == sid
    # Three components.
    assert cookie.count(".") == 2
    # Last component is the active key version.
    assert cookie.rsplit(".", 1)[1] == "1"


def test_tampered_signature_fails():
    signer = HmacCookieSigner(active_key_version=1, keys={1: b"k1"})
    sid = SessionId(uuid4())
    cookie = signer.sign(sid)
    # Flip a bit in the signature segment.
    head, sig, ver = cookie.split(".")
    bad_sig = _b64u(bytes(b ^ 1 for b in base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))))
    with pytest.raises(CookieSignatureInvalid):
        signer.verify(f"{head}.{bad_sig}.{ver}")


def test_unknown_version_rejected():
    signer = HmacCookieSigner(active_key_version=1, keys={1: b"k1"})
    sid = SessionId(uuid4())
    head, sig, _ = signer.sign(sid).split(".")
    with pytest.raises(CookieSignatureInvalid):
        signer.verify(f"{head}.{sig}.9")


def test_malformed_cookie_rejected():
    signer = HmacCookieSigner(active_key_version=1, keys={1: b"k1"})
    with pytest.raises(CookieMalformed):
        signer.verify("not-a-cookie")
    with pytest.raises(CookieMalformed):
        signer.verify("only.two")


def test_rotation_old_key_still_verifies_while_present():
    # Sign with v1.
    signer_v1_only = HmacCookieSigner(active_key_version=1, keys={1: b"k1"})
    sid = SessionId(uuid4())
    cookie = signer_v1_only.sign(sid)

    # Deploy step: add v2 active, keep v1 around.
    rotated = HmacCookieSigner(active_key_version=2, keys={1: b"k1", 2: b"k2"})
    assert rotated.verify(cookie) == sid  # v1-signed cookie still valid.
    new_cookie = rotated.sign(sid)
    assert new_cookie.rsplit(".", 1)[1] == "2"
    assert rotated.verify(new_cookie) == sid

    # Drop v1.
    post_rotation = HmacCookieSigner(active_key_version=2, keys={2: b"k2"})
    with pytest.raises(CookieSignatureInvalid):
        post_rotation.verify(cookie)
    # New cookies still verify.
    assert post_rotation.verify(new_cookie) == sid


def test_from_env_parses_versioned_keys():
    # base64url-encoded `k1` and `k2` without padding.
    k1 = base64.urlsafe_b64encode(b"k1").rstrip(b"=").decode("ascii")
    k2 = base64.urlsafe_b64encode(b"k2").rstrip(b"=").decode("ascii")
    signer = HmacCookieSigner.from_env(signing_keys=f"1:{k1},2:{k2}", active_key=2)
    sid = SessionId(uuid4())
    cookie = signer.sign(sid)
    assert signer.verify(cookie) == sid


def test_from_env_rejects_active_not_in_keys():
    k1 = base64.urlsafe_b64encode(b"k1").rstrip(b"=").decode("ascii")
    with pytest.raises(ValueError):
        HmacCookieSigner.from_env(signing_keys=f"1:{k1}", active_key=9)
