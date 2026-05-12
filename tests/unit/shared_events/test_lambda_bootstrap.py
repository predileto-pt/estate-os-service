"""Bootstrap behaviour for Lambda cold-start Secrets Manager fetch.

Covers the three branches:
  1. Happy path — secret payload populates os.environ (setdefault).
  2. SECRET_NAME unset — no-op, no boto3 client constructed.
  3. Malformed payload — JSON parsing raises, lambda will crash on cold start.

The bootstrap calls boto3 directly (sync) so tests patch `boto3.client`.
"""

import json
import os
from unittest.mock import patch

import pytest

from shared.events import lambda_bootstrap


class _StubSecretsClient:
    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.called_with: dict | None = None

    def get_secret_value(self, *, SecretId: str) -> dict:
        self.called_with = {"SecretId": SecretId}
        return {"SecretString": self._payload}


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The test module pollutes os.environ via setdefault. Wipe known keys
    # before each test so assertions are deterministic.
    for key in (
        "SECRET_NAME",
        "AWS_REGION",
        "AWS_DEFAULT_REGION",
        "BOOTSTRAP_TEST_FOO",
        "BOOTSTRAP_TEST_BAR",
        "BOOTSTRAP_TEST_PRESET",
    ):
        monkeypatch.delenv(key, raising=False)


class TestLoadSecretsIntoEnv:
    def test_happy_path_populates_environ(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_NAME", "my-secret")
        monkeypatch.setenv("AWS_REGION", "eu-west-3")
        stub = _StubSecretsClient(
            json.dumps({"BOOTSTRAP_TEST_FOO": "1", "BOOTSTRAP_TEST_BAR": "x"})
        )

        with patch("shared.events.lambda_bootstrap.boto3.client", return_value=stub) as factory:
            lambda_bootstrap.load_secrets_into_env()

        factory.assert_called_once_with("secretsmanager", region_name="eu-west-3")
        assert stub.called_with == {"SecretId": "my-secret"}
        assert os.environ["BOOTSTRAP_TEST_FOO"] == "1"
        assert os.environ["BOOTSTRAP_TEST_BAR"] == "x"

    def test_no_secret_name_is_a_noop(self) -> None:
        # SECRET_NAME absent → don't construct any boto3 client, don't raise.
        with patch("shared.events.lambda_bootstrap.boto3.client") as factory:
            lambda_bootstrap.load_secrets_into_env()
        factory.assert_not_called()

    def test_setdefault_preserves_existing_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_NAME", "my-secret")
        monkeypatch.setenv("BOOTSTRAP_TEST_PRESET", "shell-value")
        stub = _StubSecretsClient(json.dumps({"BOOTSTRAP_TEST_PRESET": "secret-value"}))

        with patch("shared.events.lambda_bootstrap.boto3.client", return_value=stub):
            lambda_bootstrap.load_secrets_into_env()

        # setdefault: process-env value wins.
        assert os.environ["BOOTSTRAP_TEST_PRESET"] == "shell-value"

    def test_malformed_json_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_NAME", "my-secret")
        stub = _StubSecretsClient("not-json{")
        with patch("shared.events.lambda_bootstrap.boto3.client", return_value=stub):
            with pytest.raises(json.JSONDecodeError):
                lambda_bootstrap.load_secrets_into_env()

    def test_non_object_payload_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_NAME", "my-secret")
        stub = _StubSecretsClient(json.dumps(["this", "is", "a", "list"]))
        with patch("shared.events.lambda_bootstrap.boto3.client", return_value=stub):
            with pytest.raises(ValueError, match="not a JSON object"):
                lambda_bootstrap.load_secrets_into_env()

    def test_no_region_skips_region_kwarg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SECRET_NAME", "my-secret")
        stub = _StubSecretsClient(json.dumps({}))
        with patch("shared.events.lambda_bootstrap.boto3.client", return_value=stub) as factory:
            lambda_bootstrap.load_secrets_into_env()
        factory.assert_called_once_with("secretsmanager")
