#!/usr/bin/env python3
"""Validate an MCP resource inventory and emit a deletion allowlist; never deletes."""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path


def parse_expiry(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()

    if not re.fullmatch(r"[0-9a-fA-F-]{36}", args.subscription):
        raise SystemExit("invalid subscription UUID")
    if args.resource_group != "rg-aica-fixture-eus2":
        raise SystemExit("cleanup is hard-limited to rg-aica-fixture-eus2")
    expected = f"DELETE_EXPIRED_FIXTURE:{args.subscription}:{args.scenario}"
    if args.confirm != expected:
        raise SystemExit(f"confirmation mismatch; expected {expected}")

    payload = json.loads(args.inventory.read_text(encoding="utf-8"))
    resources = payload.get("resources", payload if isinstance(payload, list) else [])
    if not resources:
        raise SystemExit("inventory is empty; nothing is authorized")

    now = datetime.now(UTC)
    allowed: list[str] = []
    for resource in resources:
        resource_id = str(resource.get("id", ""))
        tags = resource.get("tags") or {}
        if f"/subscriptions/{args.subscription}/".lower() not in resource_id.lower():
            raise SystemExit(f"inventory crosses subscription boundary: {resource_id}")
        if f"/resourceGroups/{args.resource_group}/".lower() not in resource_id.lower():
            raise SystemExit(f"inventory crosses resource-group boundary: {resource_id}")
        if str(tags.get("fixture", "")).lower() != "true":
            raise SystemExit(f"resource lacks fixture=true: {resource_id}")
        if tags.get("scenarioId") != args.scenario:
            raise SystemExit(f"resource scenario mismatch: {resource_id}")
        if tags.get("dataClassification") != "synthetic":
            raise SystemExit(f"resource is not synthetic: {resource_id}")
        expiry = parse_expiry(str(tags.get("expiresOn", "")))
        if expiry > now:
            raise SystemExit(f"resource has not expired: {resource_id}")
        allowed.append(resource_id)

    print(json.dumps({
        "operator": "Azure MCP only",
        "operation": "delete listed fixture resources, never the group",
        "scenarioId": args.scenario,
        "resourceIds": sorted(allowed),
        "postcondition": "MCP Resource Graph query returns zero resources tagged with this scenarioId",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
