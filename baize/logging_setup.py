"""V20 structured logging - JSON lines for machines, text for humans.

One call configures the whole runtime:

    from baize.logging_setup import setup_logging
    setup_logging()                      # honors BAIZE_LOG_* config

Format is chosen by BAIZE_LOG_FORMAT:
  text  - human readable, colorized level when the terminal supports it
  json  - one JSON object per line (ship straight to Loki/ELK/CloudWatch)

Secrets are redacted before they can reach a log sink: any value that looks
like an API key or bearer token is masked, because "we accidentally logged
the API key" is a P0 that costs real money.
"""
from __future__ import annotations

import json
import logging
import re
import sys

from .config import load_config

__all__ = ["setup_logging", "get_logger", "JsonFormatter", "TextFormatter",
           "redact", "SECRET_PATTERNS"]

LOGGER_NAME = "baize"

# Patterns whose *values* must never appear in a log line.
SECRET_PATTERNS = [
    re.compile(r"(sk-[A-Za-z0-9_\-]{8,})"),
    re.compile(r"(gh[pousr]_[A-Za-z0-9]{16,})"),
    re.compile(r"((?i:bearer)\s+)([A-Za-z0-9._\-]{12,})"),
    re.compile(r"((?i:api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?)"
               r"([^\s\"',}]{6,})"),
]


def redact(text: str) -> str:
    """Mask credential-looking substrings. Cheap, best-effort, always on."""
    if not text:
        return text
    out = text
    for pat in SECRET_PATTERNS:
        if pat.groups >= 2:
            out = pat.sub(lambda m: m.group(1) + "***REDACTED***", out)
        else:
            out = pat.sub("***REDACTED***", out)
    return out


class JsonFormatter(logging.Formatter):
    """One JSON object per line - ready for log shipping."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for key in ("session_id", "role", "tool", "step", "event"):
            val = getattr(record, key, None)
            if val is not None:
                payload[key] = val
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Human-readable single line, with redaction applied."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                         datefmt="%H:%M:%S")

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def setup_logging(cfg: dict | None = None, stream=None) -> logging.Logger:
    """Configure the 'baize' logger. Idempotent - safe to call repeatedly."""
    cfg = cfg or load_config()
    level_name = str(cfg.get("BAIZE_LOG_LEVEL", "INFO")).upper()
    fmt = str(cfg.get("BAIZE_LOG_FORMAT", "text")).lower()

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(getattr(logging, level_name, logging.INFO))
    logger.propagate = False           # don't double-log through the root
    for h in list(logger.handlers):    # idempotency: replace, never stack
        logger.removeHandler(h)

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    logger.addHandler(handler)
    return logger


def get_logger(name: str = "") -> logging.Logger:
    """Child logger under the 'baize' namespace."""
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)
