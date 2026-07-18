"""UUIDv7 generation without a runtime dependency."""

from __future__ import annotations

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    """Generate a time-ordered RFC 9562 UUIDv7."""

    timestamp_ms = time.time_ns() // 1_000_000
    if timestamp_ms >= 1 << 48:
        raise OverflowError("timestamp does not fit UUIDv7")
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    return uuid.UUID(int=value)


def new_id(prefix: str | None = None) -> str:
    value = str(uuid7())
    return f"{prefix}-{value}" if prefix else value
