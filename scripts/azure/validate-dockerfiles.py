#!/usr/bin/env python3
"""Reject registry-backed Dockerfile stages that are not SHA-256 pinned."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FROM = re.compile(r"^\s*FROM(?:\s+--platform=\S+)?\s+(?P<image>\S+)", re.IGNORECASE)
PINNED_IMAGE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
EXCLUDED_PARTS = {".git", ".venv", "node_modules"}


def dockerfiles() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*")
        if path.is_file()
        and (path.name == "Dockerfile" or path.name.endswith(".Dockerfile"))
        and not any(part in EXCLUDED_PARTS for part in path.relative_to(ROOT).parts)
    )


def main() -> int:
    errors: list[str] = []
    stages = 0
    files = dockerfiles()
    if not files:
        errors.append("no Dockerfiles found")

    for path in files:
        file_stages = 0
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = FROM.match(line)
            if not match:
                continue
            file_stages += 1
            stages += 1
            image = match.group("image")
            if not PINNED_IMAGE.fullmatch(image):
                errors.append(
                    f"{path.relative_to(ROOT)}:{number}: FROM image is not pinned "
                    f"by a 64-hex sha256 digest: {image}"
                )
        if file_stages == 0:
            errors.append(f"{path.relative_to(ROOT)}: no FROM stage found")

    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Dockerfile pin validation passed: {stages} stages across {len(files)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
