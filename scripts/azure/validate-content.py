#!/usr/bin/env python3
"""Offline structural checks for security content and workflow action pinning."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    errors: list[str] = []

    for path in sorted((ROOT / "sentinel").rglob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid JSON {path.relative_to(ROOT)}: {exc}")

    queries = sorted((ROOT / "sentinel" / "queries").glob("*.kql"))
    if len(queries) != 4:
        errors.append(f"expected four Sentinel queries, found {len(queries)}")
    for path in queries:
        text = path.read_text(encoding="utf-8")
        if not text.strip() or "TODO" in text or "search *" in text.lower():
            errors.append(f"unsafe/incomplete KQL: {path.relative_to(ROOT)}")
        if text.count("(") != text.count(")"):
            errors.append(f"unbalanced parentheses in {path.relative_to(ROOT)}")

    uses_pattern = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)
    pinned_pattern = re.compile(r"^[^@]+@[0-9a-f]{40}$")
    for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
        for action in uses_pattern.findall(path.read_text(encoding="utf-8")):
            if action.startswith("./"):
                continue
            if not pinned_pattern.fullmatch(action):
                errors.append(f"unpinned action {action} in {path.relative_to(ROOT)}")

    if errors:
        print("\n".join(f"ERROR: {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"content validation passed: {len(queries)} KQL rules and pinned workflow actions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
