"""Deterministic sanitization for artifacts crossing the public boundary."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

GUID_PATTERN = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)
EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
IPV4_PATTERN = re.compile(
    r"(?<![\d.])(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?![\d.])"
)
AZURE_RESOURCE_PATTERN = re.compile(
    r"(?i)/subscriptions/(?!\[REDACTED\])[^/]+/resourceGroups/"
    r"(?!\[REDACTED\])[^/]+(?:/providers/[^\s\"']+)?"
)
SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|client[_-]?secret|password|token|authorization)\s*[:=]\s*([^\s,;]+)"
)
RAW_CONTENT_PATTERN = re.compile(
    r'''(?i)raw[_-]?(?:prompt|response)["']?\s*[:=]\s*["']'''
    r'''(?!\[REDACTED\]["'])[^"']+'''
)
PRIVATE_ARTIFACT_URI_PATTERN = re.compile(r"(?i)az://private-evidence/")
SENSITIVE_GUID_ASSIGNMENT = re.compile(
    r"(?i)\b(tenant(?:id|_id)|subscription(?:id|_id)|principal(?:id|_id)|user(?:id|_id))"
    r'(["\']?\s*[:=]\s*["\']?)'
    r"([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})"
)

SENSITIVE_KEYS = {
    "tenantid",
    "tenant_id",
    "subscriptionid",
    "subscription_id",
    "userid",
    "user_id",
    "principalid",
    "principal_id",
    "email",
    "ipaddress",
    "ip_address",
    "prompt",
    "response",
    "rawprompt",
    "raw_prompt",
    "rawresponse",
    "raw_response",
    "authorization",
    "token",
    "secret",
    "password",
    "apikey",
    "api_key",
}


def redact_text(value: str) -> str:
    value = AZURE_RESOURCE_PATTERN.sub("/subscriptions/[REDACTED]/resourceGroups/[REDACTED]", value)
    value = SENSITIVE_GUID_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED-GUID]", value
    )
    value = EMAIL_PATTERN.sub("[REDACTED-IDENTITY]", value)
    value = IPV4_PATTERN.sub("[REDACTED-IP]", value)
    return SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED-SECRET]", value)


def sanitize(value: Any, *, replacement: str = "[REDACTED]") -> Any:
    """Recursively sanitize data while retaining enough structure for audit review."""

    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            if key.casefold() in SENSITIVE_KEYS:
                sanitized[key] = replacement
            else:
                sanitized[key] = sanitize(item, replacement=replacement)
        return sanitized
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize(item, replacement=replacement) for item in value]
    return value


def public_boundary_violations(value: str) -> list[str]:
    """Return categories that would make a sanitized artifact unsafe to publish."""

    violations: list[str] = []
    checks = {
        "sensitive_guid_assignment": SENSITIVE_GUID_ASSIGNMENT,
        "email": EMAIL_PATTERN,
        "ip_address": IPV4_PATTERN,
        "azure_resource_id": AZURE_RESOURCE_PATTERN,
        "secret_assignment": SECRET_PATTERN,
        "raw_content": RAW_CONTENT_PATTERN,
        "private_artifact_uri": PRIVATE_ARTIFACT_URI_PATTERN,
    }
    for name, pattern in checks.items():
        if pattern.search(value):
            violations.append(name)
    return violations


def assert_public_safe(value: str) -> None:
    violations = public_boundary_violations(value)
    if violations:
        raise ValueError(f"public boundary rejected artifact: {', '.join(violations)}")
