#!/usr/bin/env python3
"""Fail closed on dangerous or out-of-scope Azure What-If changes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

ALLOWED_GROUPS = {
    "rg-aica-control-cc",
    "rg-aica-sut-eus2",
    "rg-aica-fixture-eus2",
    "rg-sc200-sentinel-lab",
}
FORBIDDEN_ROLE_IDS = {
    "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",  # Owner
    "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9",  # User Access Administrator
}
COMMAND_WORKER_ROLE_NAME = "aica assessment job starter"
COMMAND_WORKER_ROLE_ACTIONS = {
    "microsoft.app/jobs/read",
    "microsoft.app/jobs/execution/read",
    "microsoft.app/jobs/start/action",
}
SECURITY_READER_ROLE_ID = "39bc4728-0917-49c7-9d2c-d95423bc2eb4"


def walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def change_records(document: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in walk(document):
        if not isinstance(value, dict):
            continue
        if "changeType" in value and any(key in value for key in ("resourceId", "after", "before", "delta")):
            records.append(value)
    return records


def resource_group(resource_id: str) -> str | None:
    match = re.search(r"/resourceGroups/([^/]+)", resource_id, flags=re.IGNORECASE)
    return match.group(1) if match else None


def normalized_resource_type(value: Any, resource_id: str) -> str:
    if isinstance(value, dict) and value.get("type"):
        return str(value["type"]).lower()
    match = re.search(r"/providers/([^/]+/[^/]+)", resource_id, flags=re.IGNORECASE)
    return match.group(1).lower() if match else ""


def command_worker_role_is_exact(properties: dict[str, Any]) -> bool:
    actions = {
        str(action).lower()
        for permission in properties.get("permissions", [])
        if isinstance(permission, dict)
        for action in permission.get("actions", [])
    }
    scopes = {
        str(scope).lower().rstrip("/")
        for scope in properties.get("assignableScopes", [])
    }
    return (
        str(properties.get("roleName", "")).lower() == COMMAND_WORKER_ROLE_NAME
        and str(properties.get("type", "")).lower() == "customrole"
        and actions == COMMAND_WORKER_ROLE_ACTIONS
        and len(scopes) == 1
        and next(iter(scopes), "").endswith("/resourcegroups/rg-aica-control-cc")
    )


def allowed_subscription_resource(value: Any, resource_id: str) -> bool:
    if not isinstance(value, dict):
        return False
    kind = normalized_resource_type(value, resource_id)
    properties = value.get("properties", {})
    if not isinstance(properties, dict):
        return False

    if kind == "microsoft.consumption/budgets":
        name_is_expected = bool(
            re.search(r"/budgets/budget-aica-(dev|demo)$", resource_id, flags=re.IGNORECASE)
        )
        amount = properties.get("amount")
        return (
            name_is_expected
            and isinstance(amount, (int, float))
            and not isinstance(amount, bool)
            and 0 < amount <= 25
            and str(properties.get("category", "")).lower() == "cost"
            and str(properties.get("timeGrain", "")).lower() == "monthly"
        )

    if kind == "microsoft.authorization/roledefinitions":
        return command_worker_role_is_exact(properties)

    if kind == "microsoft.authorization/roleassignments":
        role_id = str(properties.get("roleDefinitionId", "")).lower().rsplit("/", 1)[-1]
        return (
            role_id == SECURITY_READER_ROLE_ID
            and str(properties.get("principalType", "")).lower() == "serviceprincipal"
            and bool(re.fullmatch(r"[0-9a-fA-F-]{36}", str(properties.get("principalId", ""))))
        )

    return False


def inspect_after(
    value: Any,
    resource_id: str,
    errors: list[str],
    allow_model: bool,
    allow_phi: bool,
) -> None:
    if not isinstance(value, dict):
        return
    resource_type = normalized_resource_type(value, resource_id)
    properties = value.get("properties", {}) if isinstance(value.get("properties", {}), dict) else {}

    if "microsoft.storage/storageaccounts" in resource_id.lower() or resource_type == "microsoft.storage/storageaccounts":
        if properties.get("allowBlobPublicAccess") is not False:
            errors.append(f"anonymous-capable storage change: {resource_id}")
        if properties.get("allowSharedKeyAccess") is not False:
            errors.append(f"Shared Key storage change: {resource_id}")

    if "microsoft.authorization/roleassignments" in resource_id.lower() or resource_type == "microsoft.authorization/roleassignments":
        role_id = str(properties.get("roleDefinitionId", "")).lower().rsplit("/", 1)[-1]
        if role_id in FORBIDDEN_ROLE_IDS:
            errors.append(f"forbidden privileged role assignment: {resource_id}")

    if "microsoft.authorization/roledefinitions" in resource_id.lower() or resource_type == "microsoft.authorization/roledefinitions":
        role_name = str(properties.get("roleName", "")).lower()
        if role_name == COMMAND_WORKER_ROLE_NAME and not command_worker_role_is_exact(properties):
            errors.append(f"command worker role is broader, incomplete, or mis-scoped: {resource_id}")

    if "microsoft.cognitiveservices/accounts/deployments" in resource_id.lower() and not allow_model:
        errors.append(f"model deployment lacks explicit quota approval: {resource_id}")

    if "/microsoft.app/containerapps/ca-aica-phi-" in resource_id.lower() and not allow_phi:
        errors.append(f"Phi fallback lacks explicit zero-quota approval: {resource_id}")

    if resource_type in {"microsoft.compute/virtualmachines", "microsoft.network/publicipaddresses"}:
        errors.append(f"prohibited fixture/architecture resource type {resource_type}: {resource_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("what_if", type=Path)
    parser.add_argument("--allow-model-deployment", action="store_true")
    parser.add_argument("--allow-phi-fallback", action="store_true")
    args = parser.parse_args()

    document = json.loads(args.what_if.read_text(encoding="utf-8"))
    records = change_records(document)
    if not records:
        print("What-If review failed closed: no change records found", file=sys.stderr)
        return 2

    errors: list[str] = []
    counts: dict[str, int] = {}
    for record in records:
        change_type = str(record.get("changeType", "Unknown"))
        counts[change_type] = counts.get(change_type, 0) + 1
        resource_id = str(record.get("resourceId", ""))
        group = resource_group(resource_id)
        if group and group.lower() not in {name.lower() for name in ALLOWED_GROUPS}:
            errors.append(f"resource outside approved groups: {resource_id}")
        if not group and not allowed_subscription_resource(record.get("after"), resource_id):
            errors.append(f"subscription-level resource is not explicitly allowed: {resource_id}")
        if change_type.lower() == "delete":
            errors.append(f"delete requires separate, explicit review: {resource_id}")
        inspect_after(
            record.get("after"),
            resource_id,
            errors,
            args.allow_model_deployment,
            args.allow_phi_fallback,
        )

    summary = {"changeCounts": counts, "recordCount": len(records), "approved": not errors}
    print(json.dumps(summary, indent=2, sort_keys=True))
    if errors:
        for error in sorted(set(errors)):
            print(f"DENY: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
