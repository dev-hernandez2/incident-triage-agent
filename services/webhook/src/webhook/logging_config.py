"""JSON structured logging setup for the webhook service."""

import json
import logging
import sys
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        for key in ("fingerprint", "alertname", "status"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload)


def configure_logging() -> logging.Logger:
    logger = logging.getLogger("webhook")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.handlers = [handler]
    logger.propagate = False
    return logger
