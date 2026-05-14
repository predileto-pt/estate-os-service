"""JSON log formatters for uvicorn's `uvicorn.error` and `uvicorn.access` loggers.

Referenced from `deploy/log_config.yaml` via the dictConfig `()` factory key so
uvicorn emits structured logs that Coolify / Logfire ingest the same way as the
structlog output from `shared.config.setup_logging`.

Kept stdlib-only on purpose (no python-json-logger dep).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_BASE_RECORD_KEYS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
        "asctime",
        "taskName",
    }
)


def _record_to_dict(record: logging.LogRecord) -> dict[str, object]:
    payload: dict[str, object] = {
        "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
        "level": record.levelname.lower(),
        "logger": record.name,
        "message": record.getMessage(),
    }
    if record.exc_info:
        payload["exc_info"] = logging.Formatter().formatException(record.exc_info)
    for key, value in record.__dict__.items():
        if key in _BASE_RECORD_KEYS or key.startswith("_"):
            continue
        payload.setdefault(key, value)
    return payload


class JsonFormatter(logging.Formatter):
    """JSON formatter for `uvicorn.error` (startup + framework messages)."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_record_to_dict(record), default=str)


class JsonAccessFormatter(logging.Formatter):
    """JSON formatter for `uvicorn.access`.

    Uvicorn passes the access tuple as `record.args`:
    `(client_addr, method, full_path, http_version, status_code)`.
    See `uvicorn.logging.AccessFormatter` for the upstream parse.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
        }
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client_addr, method, full_path, http_version, status_code = record.args
            payload.update(
                {
                    "client_addr": client_addr,
                    "method": method,
                    "path": full_path,
                    "http_version": http_version,
                    "status_code": int(status_code) if status_code is not None else None,
                    "message": f"{method} {full_path} {status_code}",
                }
            )
        else:
            payload["message"] = record.getMessage()
        return json.dumps(payload, default=str)
