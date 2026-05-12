"""Cold-start Secrets Manager → os.environ bootstrap for Lambda workers.

Lambda has no `user_data.sh` equivalent. This module fills the same role:
fetch the JSON-encoded secret blob from AWS Secrets Manager at import
time and `os.environ.setdefault(...)` each key, so that `Settings()`
(pydantic-settings) reads the right values when the per-context container
is built downstream.

**Import-order constraint**: this module must NOT import `shared.config`
or any module that transitively imports it. `shared/config.py` wires
Logfire at module load (`logfire.configure(token=settings.logfire_token)`)
which instantiates `Settings()` immediately — before env vars are present,
that read defaults to empties. Keep this file dependent on `os`, `json`,
and `boto3` only.

`setdefault` semantics are deliberate: anything already in the process
env wins over the secret payload, which makes local Lambda testing and
single-key overrides painless.
"""

import json
import os

import boto3


def load_secrets_into_env() -> None:
    """Read `SECRET_NAME` from env and populate process env with secret keys.

    No-op when `SECRET_NAME` is unset (local dev / unit tests). Raises if
    the secret value isn't valid JSON or isn't an object — those are
    fatal misconfigurations the Lambda should crash on.
    """
    secret_name = os.environ.get("SECRET_NAME")
    if not secret_name:
        return

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    client_kwargs: dict[str, str] = {}
    if region:
        client_kwargs["region_name"] = region

    client = boto3.client("secretsmanager", **client_kwargs)
    response = client.get_secret_value(SecretId=secret_name)
    payload = json.loads(response["SecretString"])
    if not isinstance(payload, dict):
        raise ValueError(
            f"Secret {secret_name!r} is not a JSON object — got {type(payload).__name__}"
        )

    for key, value in payload.items():
        os.environ.setdefault(key, str(value))
