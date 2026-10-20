"""Masks secrets in tool output before it reaches the LLM or storage."""

import re

_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")
_KEY_VALUE_SECRET = re.compile(
    r"(?i)\b(password|passwd|token|api[_-]?key|secret|access[_-]?key)"
    r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)"
)
# Real secrets look like base64 (often with +/= padding) or long pure-hex
# digests. Kubernetes resource names (e.g. "cartservice-c7cf86b58-fmkhn"),
# file paths (e.g. "/var/log/pods/..."), and "namespace/name" job labels
# must not match: hex requires 32+ hex-only chars with no hyphens or
# slashes, and base64 requires '+' or a trailing '=' padding char — '/'
# alone is excluded as a signal since it's common in paths and labels.
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_LONG_BASE64_CANDIDATE = re.compile(r"[A-Za-z0-9+/]{20,}={0,2}")

_MASK = "***REDACTED***"


def _redact_base64_candidate(match: re.Match[str]) -> str:
    token = match.group(0)
    if "+" in token or token.endswith("="):
        return _MASK
    return token


def redact(text: str) -> str:
    text = _BEARER.sub(f"Bearer {_MASK}", text)
    text = _KEY_VALUE_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}{_MASK}", text)
    text = _LONG_HEX.sub(_MASK, text)
    text = _LONG_BASE64_CANDIDATE.sub(_redact_base64_candidate, text)
    return text
