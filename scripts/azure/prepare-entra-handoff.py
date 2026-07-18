#!/usr/bin/env python3
"""Validate and materialize the two-app Entra Azure MCP handoff."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "infra" / "entra" / "app-registration-handoff.json"
HUMAN_ROLE_VALUES = {
    "Assurance.Assessor",
    "Assurance.Reviewer",
    "Assurance.RiskApprover",
}
APPLICATIONS = {
    "assurance-console": {
        "clientParameter": "assuranceApiClientId",
        "foundationOutput": "assuranceAuthRedirectUri",
        "hostnamePrefix": "ca-aica-console-",
        "workloadAssignments": {
            ("collector managed identity", "Assurance.AuthorizationProbe"),
        },
        "workloadRole": "Assurance.AuthorizationProbe",
    },
    "policy-assistant": {
        "clientParameter": "assistantClientId",
        "foundationOutput": "assistantAuthRedirectUri",
        "hostnamePrefix": "ca-aica-assistant-",
        "workloadAssignments": {
            ("assistant managed identity", "Assurance.WorkloadInvoker"),
            ("collector managed identity", "Assurance.WorkloadInvoker"),
        },
        "workloadRole": "Assurance.WorkloadInvoker",
    },
}


class EntraHandoffError(RuntimeError):
    """The Entra handoff is incomplete or internally inconsistent."""


def _canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _read_object(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        content = path.read_bytes()
        value = json.loads(content.decode())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EntraHandoffError(f"invalid JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EntraHandoffError(f"JSON input must be an object: {path}")
    return cast(dict[str, Any], value), content


def _validate_uuid(value: object, label: str) -> str:
    try:
        parsed = UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise EntraHandoffError(f"{label} must be a UUID") from exc
    return str(parsed)


def validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("schemaVersion") != "1.0.0":
        raise EntraHandoffError("unsupported Entra handoff schemaVersion")
    if spec.get("signInAudience") != "AzureADMyOrg":
        raise EntraHandoffError("the two registrations must be single-tenant AzureADMyOrg apps")
    credential = spec.get("credentialPolicy")
    if not isinstance(credential, dict) or (
        credential.get("idTokenIssuanceEnabled") is not True
        or credential.get("accessTokenIssuanceEnabled") is not False
        or credential.get("clientSecretsAllowed") is not False
    ):
        raise EntraHandoffError("credential policy must match the checked-in ID-token-only Easy Auth design")
    external = spec.get("externalGate")
    if not isinstance(external, dict) or (
        external.get("mutationChannel") != "Azure MCP only"
        or external.get("statusUntilReceipt") != "BLOCKED"
    ):
        raise EntraHandoffError("Entra creation must remain a blocked Azure MCP external gate")

    applications = spec.get("applications")
    if not isinstance(applications, list) or len(applications) != 2:
        raise EntraHandoffError("the Entra handoff must define exactly two applications")
    seen_keys: set[str] = set()
    role_ids: set[str] = set()
    for raw in applications:
        if not isinstance(raw, dict):
            raise EntraHandoffError("application specification must be an object")
        app = cast(dict[str, Any], raw)
        key = str(app.get("key", ""))
        expected = APPLICATIONS.get(key)
        if expected is None or key in seen_keys:
            raise EntraHandoffError(f"unknown or duplicate application key: {key!r}")
        seen_keys.add(key)
        if app.get("clientIdParameter") != expected["clientParameter"]:
            raise EntraHandoffError(f"{key}: client ID parameter is incorrect")
        if app.get("authorizedAudiences") != ["api://{clientId}"]:
            raise EntraHandoffError(f"{key}: authorized audience must bind its returned client ID")
        if app.get("easyAuthAllowedClientApplications") != ["{clientId}"]:
            raise EntraHandoffError(f"{key}: Easy Auth client allowlist must be self-only")
        redirect = app.get("redirectUri")
        if not isinstance(redirect, dict) or (
            redirect.get("foundationOutput") != expected["foundationOutput"]
            or redirect.get("type") != "Web"
            or redirect.get("requiredSuffix") != "/.auth/login/aad/callback"
        ):
            raise EntraHandoffError(f"{key}: callback is not bound to the matching foundation output")
        assignments = app.get("assignmentExpectations")
        if not isinstance(assignments, dict) or (
            assignments.get("appRoleAssignmentRequired") is not True
            or assignments.get("noDefaultAccess") is not True
        ):
            raise EntraHandoffError(f"{key}: unassigned principals must be denied")
        assignment_rows = assignments.get("personaAssignments")
        if not isinstance(assignment_rows, list) or {
            str(item.get("role")) for item in assignment_rows if isinstance(item, dict)
        } != HUMAN_ROLE_VALUES:
            raise EntraHandoffError(f"{key}: assignment expectations must cover all three roles")
        workload_rows = assignments.get("workloadAssignments")
        if not isinstance(workload_rows, list) or {
            (str(item.get("principal")), str(item.get("role")))
            for item in workload_rows
            if isinstance(item, dict)
        } != expected["workloadAssignments"]:
            raise EntraHandoffError(f"{key}: managed-identity app-role assignments are incomplete")
        roles = app.get("appRoles")
        if not isinstance(roles, list) or {
            str(item.get("value")) for item in roles if isinstance(item, dict)
        } != HUMAN_ROLE_VALUES | {str(expected["workloadRole"])}:
            raise EntraHandoffError(f"{key}: human and application app-role values are incomplete")
        if len(roles) != 4:
            raise EntraHandoffError(f"{key}: app roles must be unique")
        for role in roles:
            if not isinstance(role, dict):
                raise EntraHandoffError(f"{key}: app role must be an object")
            role_id = _validate_uuid(role.get("id"), f"{key} app role ID")
            if role_id in role_ids:
                raise EntraHandoffError("app-role UUIDs must be stable and globally distinct in the handoff")
            role_ids.add(role_id)
            expected_member_type = (
                ["User"] if role.get("value") in HUMAN_ROLE_VALUES else ["Application"]
            )
            if (
                role.get("allowedMemberTypes") != expected_member_type
                or role.get("isEnabled") is not True
            ):
                raise EntraHandoffError(f"{key}: app-role member type or enabled state is wrong")
    if seen_keys != set(APPLICATIONS):
        raise EntraHandoffError("both required Entra applications must be present")


def _outputs(document: dict[str, Any]) -> dict[str, Any]:
    candidates: list[object] = [document.get("outputs")]
    properties = document.get("properties")
    if isinstance(properties, dict):
        candidates.append(properties.get("outputs"))
    candidates.append(document)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        result: dict[str, Any] = {}
        for name in ("assuranceAuthRedirectUri", "assistantAuthRedirectUri"):
            raw = candidate.get(name)
            if isinstance(raw, dict) and "value" in raw:
                raw = raw["value"]
            result[name] = raw
        if all(isinstance(value, str) and value for value in result.values()):
            return result
    raise EntraHandoffError("foundation evidence does not contain both redirect URI outputs")


def _callback(value: object, key: str, environment: str) -> str:
    text = str(value)
    parsed = urlparse(text)
    expected_host_prefix = f"{APPLICATIONS[key]['hostnamePrefix']}{environment}."
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.startswith(expected_host_prefix)
        or parsed.path != "/.auth/login/aad/callback"
        or parsed.query
        or parsed.fragment
    ):
        raise EntraHandoffError(f"{key}: foundation callback URI is unexpected: {text!r}")
    return text


def materialized_handoff(
    spec: dict[str, Any],
    foundation: dict[str, Any],
    foundation_bytes: bytes,
    environment: str,
) -> dict[str, Any]:
    validate_spec(spec)
    outputs = _outputs(foundation)
    applications: list[dict[str, Any]] = []
    for source in cast(list[dict[str, Any]], spec["applications"]):
        key = str(source["key"])
        callback = _callback(
            outputs[str(source["redirectUri"]["foundationOutput"])], key, environment
        )
        app = {
            "applicationCreate": {
                "appRoles": copy.deepcopy(source["appRoles"]),
                "displayName": str(source["displayNameTemplate"]).replace(
                    "{environment}", environment
                ),
                "signInAudience": spec["signInAudience"],
                "web": {
                    "implicitGrantSettings": {
                        "enableAccessTokenIssuance": False,
                        "enableIdTokenIssuance": True,
                    },
                    "redirectUris": [callback],
                },
            },
            "applicationPatchAfterCreate": {"identifierUris": ["api://{clientId}"]},
            "assignmentExpectations": copy.deepcopy(source["assignmentExpectations"]),
            "clientIdParameter": source["clientIdParameter"],
            "easyAuthReadback": {
                "allowedAudiences": ["api://{clientId}"],
                "allowedClientApplications": ["{clientId}"],
                "callbackUri": callback,
            },
            "key": key,
            "servicePrincipalPatch": {"appRoleAssignmentRequired": True},
        }
        applications.append(app)
    return {
        "$schema": "../../schemas/entra-mcp-handoff.schema.json",
        "applications": applications,
        "completionEvidence": copy.deepcopy(spec["externalGate"]["requiredEvidence"]),
        "environment": environment,
        "foundationOutputsSha256": sha256(foundation_bytes).hexdigest(),
        "mutationChannel": "Azure MCP only",
        "schemaVersion": "1.0.0",
        "status": "READY_FOR_AZURE_MCP",
    }


def prepare(foundation_path: Path, environment: str, output: Path) -> str:
    spec, _ = _read_object(SPEC_PATH)
    foundation, foundation_bytes = _read_object(foundation_path)
    value = materialized_handoff(spec, foundation, foundation_bytes, environment)
    content = _canonical(value)
    if output.exists():
        raise EntraHandoffError(f"refusing to replace existing handoff: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(content)
    return sha256(content).hexdigest()


def verify(foundation_path: Path, environment: str, handoff_path: Path) -> str:
    spec, _ = _read_object(SPEC_PATH)
    foundation, foundation_bytes = _read_object(foundation_path)
    expected = _canonical(materialized_handoff(spec, foundation, foundation_bytes, environment))
    try:
        actual = handoff_path.read_bytes()
    except OSError as exc:
        raise EntraHandoffError(f"cannot read materialized handoff: {exc}") from exc
    if actual != expected:
        raise EntraHandoffError("materialized Entra handoff differs from the specification or outputs")
    return sha256(actual).hexdigest()


def _sha256_field(value: object, label: str) -> str:
    text = str(value)
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise EntraHandoffError(f"{label} must be a lowercase SHA-256")
    return text


def verify_receipt(
    receipt_path: Path,
    *,
    expected_environment: str,
    expected_assurance_client_id: str,
    expected_assistant_client_id: str,
    expected_tenant_id: str | None = None,
) -> str:
    """Verify private Azure MCP directory readback before workload deployment."""

    spec, _ = _read_object(SPEC_PATH)
    validate_spec(spec)
    receipt, receipt_bytes = _read_object(receipt_path)
    allowed_top = {
        "applications",
        "environment",
        "foundationOutputsSha256",
        "materializedAt",
        "materializedHandoffSha256",
        "mcpEvidenceSha256",
        "mutationChannel",
        "schemaVersion",
        "specSha256",
        "status",
        "tenantId",
    }
    if set(receipt) != allowed_top:
        raise EntraHandoffError("Entra receipt fields are incomplete or contain unapproved data")
    expected_exact = {
        "environment": expected_environment,
        "mutationChannel": "Azure MCP",
        "schemaVersion": "1.0.0",
        "specSha256": sha256(_canonical(spec)).hexdigest(),
        "status": "VERIFIED",
    }
    for field, expected_value in expected_exact.items():
        if receipt.get(field) != expected_value:
            raise EntraHandoffError(f"Entra receipt {field} differs from the approved handoff")
    for field in (
        "foundationOutputsSha256",
        "materializedHandoffSha256",
        "mcpEvidenceSha256",
    ):
        _sha256_field(receipt.get(field), f"Entra receipt {field}")
    tenant_id = _validate_uuid(receipt.get("tenantId"), "Entra receipt tenantId")
    if expected_tenant_id and tenant_id != _validate_uuid(
        expected_tenant_id, "expected tenant ID"
    ):
        raise EntraHandoffError("Entra receipt tenant does not match the deployment tenant")
    materialized = str(receipt.get("materializedAt", ""))
    if not materialized.endswith("Z"):
        raise EntraHandoffError("Entra receipt materializedAt must be RFC3339 UTC")
    try:
        if datetime.fromisoformat(materialized.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError
    except ValueError as exc:
        raise EntraHandoffError("Entra receipt materializedAt must be RFC3339 UTC") from exc

    expected_clients = {
        "assurance-console": _validate_uuid(
            expected_assurance_client_id, "expected assurance client ID"
        ),
        "policy-assistant": _validate_uuid(
            expected_assistant_client_id, "expected assistant client ID"
        ),
    }
    raw_applications = receipt.get("applications")
    if not isinstance(raw_applications, list) or len(raw_applications) != 2:
        raise EntraHandoffError("Entra receipt must contain exactly two application readbacks")
    applications: dict[str, dict[str, Any]] = {}
    for raw in raw_applications:
        if not isinstance(raw, dict):
            raise EntraHandoffError("Entra receipt application readback must be an object")
        app = cast(dict[str, Any], raw)
        key = str(app.get("key", ""))
        if key not in APPLICATIONS or key in applications:
            raise EntraHandoffError(f"Entra receipt application is unknown or duplicate: {key!r}")
        applications[key] = app

    source_apps = {
        str(item["key"]): item for item in cast(list[dict[str, Any]], spec["applications"])
    }
    app_allowed_fields = {
        "accessTokenIssuanceEnabled",
        "appRoleAssignmentRequired",
        "appRoles",
        "applicationClientId",
        "applicationObjectId",
        "assignments",
        "authorizedAudiences",
        "clientSecretCount",
        "displayName",
        "idTokenIssuanceEnabled",
        "identifierUris",
        "key",
        "mcpReadbackVerified",
        "redirectUris",
        "servicePrincipalObjectId",
        "signInAudience",
    }
    assignment_fields = {
        "assignmentId",
        "principal",
        "principalIdSha256",
        "principalType",
        "roleValue",
        "status",
    }
    for key, app in applications.items():
        if set(app) != app_allowed_fields:
            raise EntraHandoffError(f"{key}: receipt fields are incomplete or contain unapproved data")
        client_id = _validate_uuid(app.get("applicationClientId"), f"{key} client ID")
        if client_id != expected_clients[key]:
            raise EntraHandoffError(f"{key}: client ID does not match the workload parameter")
        _validate_uuid(app.get("applicationObjectId"), f"{key} application object ID")
        _validate_uuid(app.get("servicePrincipalObjectId"), f"{key} service-principal object ID")
        source = source_apps[key]
        callback = _callback(
            cast(list[str], app.get("redirectUris", []))[0]
            if isinstance(app.get("redirectUris"), list) and len(app["redirectUris"]) == 1
            else "",
            key,
            expected_environment,
        )
        expected_display = str(source["displayNameTemplate"]).replace(
            "{environment}", expected_environment
        )
        exact_fields = {
            "accessTokenIssuanceEnabled": False,
            "appRoleAssignmentRequired": True,
            "authorizedAudiences": [f"api://{client_id}"],
            "clientSecretCount": 0,
            "displayName": expected_display,
            "idTokenIssuanceEnabled": True,
            "identifierUris": [f"api://{client_id}"],
            "mcpReadbackVerified": True,
            "redirectUris": [callback],
            "signInAudience": "AzureADMyOrg",
        }
        for field, expected_value in exact_fields.items():
            if app.get(field) != expected_value:
                raise EntraHandoffError(f"{key}: receipt {field} differs from the handoff")
        expected_roles = sorted(
            cast(list[dict[str, Any]], source["appRoles"]), key=lambda role: str(role["value"])
        )
        actual_roles = app.get("appRoles")
        if not isinstance(actual_roles, list) or sorted(
            actual_roles, key=lambda role: str(role.get("value", ""))
        ) != expected_roles:
            raise EntraHandoffError(f"{key}: app-role readback differs from the specification")

        assignments = app.get("assignments")
        if not isinstance(assignments, list):
            raise EntraHandoffError(f"{key}: assignment readback must be a list")
        role_counts: dict[str, int] = {}
        workload_assignments: set[tuple[str, str]] = set()
        assignment_ids: set[str] = set()
        for raw_assignment in assignments:
            if not isinstance(raw_assignment, dict) or set(raw_assignment) != assignment_fields:
                raise EntraHandoffError(f"{key}: malformed or over-disclosed assignment evidence")
            assignment = cast(dict[str, Any], raw_assignment)
            assignment_id = _validate_uuid(
                assignment.get("assignmentId"), f"{key} assignment ID"
            )
            if assignment_id in assignment_ids:
                raise EntraHandoffError(f"{key}: duplicate app-role assignment")
            assignment_ids.add(assignment_id)
            _sha256_field(
                assignment.get("principalIdSha256"), f"{key} assignment principal binding"
            )
            if assignment.get("status") != "ACTIVE":
                raise EntraHandoffError(f"{key}: inactive assignment cannot satisfy the gate")
            role_value = str(assignment.get("roleValue", ""))
            role_counts[role_value] = role_counts.get(role_value, 0) + 1
            principal_type = assignment.get("principalType")
            principal = str(assignment.get("principal", ""))
            if role_value in HUMAN_ROLE_VALUES:
                if principal_type not in {"User", "Group"}:
                    raise EntraHandoffError(f"{key}: human role is assigned to a workload")
            else:
                if principal_type != "ServicePrincipal":
                    raise EntraHandoffError(f"{key}: workload role is not a service-principal assignment")
                workload_assignments.add((principal, role_value))
        expectations = cast(dict[str, Any], source["assignmentExpectations"])
        for row in cast(list[dict[str, Any]], expectations["personaAssignments"]):
            if role_counts.get(str(row["role"]), 0) < int(row["minimumAssignments"]):
                raise EntraHandoffError(f"{key}: required human app-role assignment is missing")
        expected_workloads = {
            (str(row["principal"]), str(row["role"]))
            for row in cast(list[dict[str, Any]], expectations["workloadAssignments"])
        }
        workload_assignment_count = sum(
            1 for item in assignments if item.get("principalType") == "ServicePrincipal"
        )
        if (
            workload_assignments != expected_workloads
            or workload_assignment_count != len(expected_workloads)
        ):
            raise EntraHandoffError(f"{key}: managed-identity app-role assignments differ")
    return sha256(receipt_bytes).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-spec")
    for command in ("prepare", "verify"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("foundation_outputs", type=Path)
        subparser.add_argument("--environment", choices=("dev", "demo"), required=True)
        target = "output" if command == "prepare" else "handoff"
        subparser.add_argument(target, type=Path)
    receipt = subparsers.add_parser("verify-receipt")
    receipt.add_argument("receipt", type=Path)
    receipt.add_argument("--expected-environment", choices=("dev", "demo"), required=True)
    receipt.add_argument("--expected-assurance-client-id", required=True)
    receipt.add_argument("--expected-assistant-client-id", required=True)
    receipt.add_argument("--expected-tenant-id")
    args = parser.parse_args()
    try:
        if args.command == "validate-spec":
            spec, _ = _read_object(SPEC_PATH)
            validate_spec(spec)
            digest = sha256(_canonical(spec)).hexdigest()
            print(f"Entra app-registration specification verified: {digest}")
        elif args.command == "prepare":
            digest = prepare(args.foundation_outputs, args.environment, args.output)
            print(f"Entra Azure MCP handoff prepared: {digest}")
        elif args.command == "verify":
            digest = verify(args.foundation_outputs, args.environment, args.handoff)
            print(f"Entra Azure MCP handoff verified: {digest}")
        else:
            digest = verify_receipt(
                args.receipt,
                expected_environment=args.expected_environment,
                expected_assurance_client_id=args.expected_assurance_client_id,
                expected_assistant_client_id=args.expected_assistant_client_id,
                expected_tenant_id=args.expected_tenant_id,
            )
            print(f"Entra Azure MCP materialization receipt verified: {digest}")
    except (EntraHandoffError, OSError) as exc:
        print(f"Entra handoff failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
