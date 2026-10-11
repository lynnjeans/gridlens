"""Redacted operational records: stage, timing, calls and usage category — never text.

Usage categories keep billing sources apart: local model inference, search-service quota
and ChatGPT plan usage. Unknown remaining quota is never estimated.
"""

import json
import logging
import re
from pathlib import Path

from gridlens.db import now

USAGE_CATEGORIES = {"local_inference", "search_quota", "chatgpt_plan", "fixture", "none"}
_SECRETS = [
    (re.compile(r"(?i)bearer\s+[^\s\"']+"), "Bearer [redacted]"),
    (
        re.compile(r"(?i)\b(access|refresh|id)_token([\"']?\s*[:=]\s*[\"']?)[^\s\"'&,}]+"),
        r"\1_token\2[redacted]",
    ),
    (
        re.compile(r"(?i)\b(code|id_token_hint|code_verifier|state|nonce|login_hint)=[^&\s\"']+"),
        r"\1=[redacted]",
    ),
    (re.compile(r"eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]*"), "[redacted-jwt]"),
    (re.compile(r"\btvly-[A-Za-z0-9_-]+"), "[redacted-key]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), "[redacted-key]"),
]


def redact(text: str) -> str:
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def install_log_redaction() -> None:
    """Redacts every handler on the root logger and the HTTP client loggers."""
    redactor = RedactingFilter()
    for name in ("", "httpx", "httpcore", "gridlens"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactingFilter) for f in logger.filters):
            logger.addFilter(redactor)
        for handler in logger.handlers:
            if not any(isinstance(f, RedactingFilter) for f in handler.filters):
                handler.addFilter(redactor)


class OperationLog:
    def __init__(self, path: Path):
        self.path = path

    def record(
        self,
        *,
        kind: str,
        operation: str,
        stage: str,
        status: str,
        duration_ms: int,
        calls: int,
        usage_category: str,
        usage: dict | None = None,
        error_code: str | None = None,
    ) -> None:
        if usage_category not in USAGE_CATEGORIES:
            raise ValueError("Unknown usage category")
        entry = {
            "at": now(),
            "kind": kind,
            "operation": operation,
            "stage": stage,
            "status": status,
            "duration_ms": max(0, int(duration_ms)),
            "calls": max(0, int(calls)),
            "usage_category": usage_category,
            # Numbers only: no prompts, answers, documents or identifiers from providers.
            "usage": {
                k: v
                for k, v in (usage or {}).items()
                if isinstance(v, int | float) and not isinstance(v, bool)
            },
            "error_code": error_code,
        }
        line = redact(json.dumps(entry, ensure_ascii=False, sort_keys=True))
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            logging.getLogger("gridlens").warning("Operation log could not be written")
