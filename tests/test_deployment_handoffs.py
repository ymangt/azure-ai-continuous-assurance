from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]


def _module(name: str, relative: str) -> ModuleType:
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _validate(schema_name: str, value: dict[str, Any]) -> None:
    schema = _read(ROOT / "schemas" / schema_name)
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda item: str(item.path))
    assert not errors, "\n".join(error.message for error in errors)


def test_corpus_handoff_is_deterministic_and_schema_valid(tmp_path: Path) -> None:
    corpus = _module("aica_prepare_corpus_handoff", "scripts/azure/prepare-corpus-handoff.py")
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_digest = corpus.prepare_bundle(first)
    second_digest = corpus.prepare_bundle(second)

    assert first_digest == second_digest == corpus.verify_bundle(first)
    assert {
        path.relative_to(first).as_posix(): path.read_bytes()
        for path in first.rglob("*")
        if path.is_file()
    } == {
        path.relative_to(second).as_posix(): path.read_bytes()
        for path in second.rglob("*")
        if path.is_file()
    }
    handoff = _read(first / "handoff.json")
    _validate("corpus-handoff.schema.json", handoff)
    assert handoff["corpus"]["prefix"] == "northstar-synthetic-policy-corpus/1.0.0"
    assert len(handoff["payload"]) == 19


def test_corpus_receipt_binds_exact_remote_properties(tmp_path: Path) -> None:
    corpus = _module("aica_verify_corpus_receipt", "scripts/azure/prepare-corpus-handoff.py")
    bundle = tmp_path / "bundle"
    bundle_digest = corpus.prepare_bundle(bundle)
    handoff = _read(bundle / "handoff.json")
    payload = handoff["payload"]
    receipt = {
        "azureMcpTool": "mcp__azure__storage",
        "blobs": [
            {
                "blobName": item["blobName"],
                "contentHash": f"mcp-content-hash-{index}",
                "etag": f'"etag-{index}"',
                "lastModified": "2026-07-18T12:00:00Z",
                "propertiesVerified": True,
                "sha256": item["sha256"],
                "sizeBytes": item["sizeBytes"],
                "sourcePath": item["path"],
                "uploadStatus": "SUCCEEDED",
            }
            for index, item in enumerate(payload)
        ],
        "bundleSha256": bundle_digest,
        "container": "synthetic-corpus",
        "containerUrl": "https://staicaexample.blob.core.windows.net/synthetic-corpus",
        "environment": "dev",
        "exactBlobSetVerified": True,
        "listedBlobNames": sorted(item["blobName"] for item in payload),
        "materializedAt": "2026-07-18T12:00:00Z",
        "mcpEvidenceSha256": "a" * 64,
        "mutationChannel": "Azure MCP",
        "prefix": handoff["corpus"]["prefix"],
        "schemaVersion": "1.0.0",
        "sourceManifestSha256": handoff["corpus"]["manifestSha256"],
        "status": "VERIFIED",
        "subscriptionId": "1f6b0863-6c5d-4ae4-bfbe-a21492048366",
        "uploadCommand": "storage_blob_upload",
        "verificationCommand": "storage_blob_get",
    }
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    _validate("corpus-materialization-receipt.schema.json", receipt)
    assert corpus.verify_receipt(
        receipt_path,
        expected_subscription_id="1f6b0863-6c5d-4ae4-bfbe-a21492048366",
        expected_environment="dev",
    ) == bundle_digest

    receipt["listedBlobNames"] = receipt["listedBlobNames"][:-1]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(corpus.HandoffError, match="exact expected blob set"):
        corpus.verify_receipt(receipt_path, expected_environment="dev")


def test_entra_spec_and_materialized_callbacks_are_exact(tmp_path: Path) -> None:
    entra = _module("aica_prepare_entra_handoff", "scripts/azure/prepare-entra-handoff.py")
    spec = _read(ROOT / "infra" / "entra" / "app-registration-handoff.json")
    entra.validate_spec(spec)
    _validate("entra-app-registration-handoff.schema.json", spec)

    foundation = {
        "properties": {
            "outputs": {
                "assuranceAuthRedirectUri": {
                    "type": "String",
                    "value": (
                        "https://ca-aica-console-dev.example.canadacentral.azurecontainerapps.io"
                        "/.auth/login/aad/callback"
                    ),
                },
                "assistantAuthRedirectUri": {
                    "type": "String",
                    "value": (
                        "https://ca-aica-assistant-dev.example.eastus2.azurecontainerapps.io"
                        "/.auth/login/aad/callback"
                    ),
                },
            }
        }
    }
    foundation_path = tmp_path / "foundation.json"
    foundation_path.write_text(json.dumps(foundation, sort_keys=True), encoding="utf-8")
    handoff_path = tmp_path / "entra-handoff.json"

    digest = entra.prepare(foundation_path, "dev", handoff_path)
    assert entra.verify(foundation_path, "dev", handoff_path) == digest
    handoff = _read(handoff_path)
    _validate("entra-mcp-handoff.schema.json", handoff)
    assert {item["key"] for item in handoff["applications"]} == {
        "assurance-console",
        "policy-assistant",
    }
    for application in handoff["applications"]:
        assert application["servicePrincipalPatch"]["appRoleAssignmentRequired"] is True
        assert {
            role["value"] for role in application["applicationCreate"]["appRoles"]
        } >= {
            "Assurance.Assessor",
            "Assurance.Reviewer",
            "Assurance.RiskApprover",
        }


def test_entra_materializer_rejects_callback_from_wrong_environment(tmp_path: Path) -> None:
    entra = _module("aica_reject_entra_callback", "scripts/azure/prepare-entra-handoff.py")
    foundation = {
        "assuranceAuthRedirectUri": (
            "https://ca-aica-console-demo.example.azurecontainerapps.io/.auth/login/aad/callback"
        ),
        "assistantAuthRedirectUri": (
            "https://ca-aica-assistant-dev.example.azurecontainerapps.io/.auth/login/aad/callback"
        ),
    }
    foundation_path = tmp_path / "wrong-foundation.json"
    foundation_path.write_text(json.dumps(foundation), encoding="utf-8")

    with pytest.raises(entra.EntraHandoffError, match="callback URI is unexpected"):
        entra.prepare(foundation_path, "dev", tmp_path / "handoff.json")


def test_entra_receipt_binds_roles_clients_and_managed_identities(tmp_path: Path) -> None:
    entra = _module("aica_verify_entra_receipt", "scripts/azure/prepare-entra-handoff.py")
    spec = _read(ROOT / "infra" / "entra" / "app-registration-handoff.json")
    clients = {
        "assurance-console": "11111111-1111-4111-8111-111111111111",
        "policy-assistant": "22222222-2222-4222-8222-222222222222",
    }
    callbacks = {
        "assurance-console": (
            "https://ca-aica-console-dev.example.canadacentral.azurecontainerapps.io"
            "/.auth/login/aad/callback"
        ),
        "policy-assistant": (
            "https://ca-aica-assistant-dev.example.eastus2.azurecontainerapps.io"
            "/.auth/login/aad/callback"
        ),
    }
    app_receipts = []
    assignment_number = 1
    for app_number, source in enumerate(spec["applications"], start=1):
        key = source["key"]
        assignments = []
        for row in source["assignmentExpectations"]["personaAssignments"]:
            for _ in range(row["minimumAssignments"]):
                assignments.append(
                    {
                        "assignmentId": f"00000000-0000-4000-8000-{assignment_number:012d}",
                        "principal": "simulated assigned persona",
                        "principalIdSha256": f"{assignment_number:064x}",
                        "principalType": "Group",
                        "roleValue": row["role"],
                        "status": "ACTIVE",
                    }
                )
                assignment_number += 1
        for row in source["assignmentExpectations"]["workloadAssignments"]:
            assignments.append(
                {
                    "assignmentId": f"00000000-0000-4000-8000-{assignment_number:012d}",
                    "principal": row["principal"],
                    "principalIdSha256": f"{assignment_number:064x}",
                    "principalType": "ServicePrincipal",
                    "roleValue": row["role"],
                    "status": "ACTIVE",
                }
            )
            assignment_number += 1
        client_id = clients[key]
        app_receipts.append(
            {
                "accessTokenIssuanceEnabled": False,
                "appRoleAssignmentRequired": True,
                "appRoles": source["appRoles"],
                "applicationClientId": client_id,
                "applicationObjectId": f"{app_number:08d}-0000-4000-8000-000000000001",
                "assignments": assignments,
                "authorizedAudiences": [f"api://{client_id}"],
                "clientSecretCount": 0,
                "displayName": source["displayNameTemplate"].replace("{environment}", "dev"),
                "idTokenIssuanceEnabled": True,
                "identifierUris": [f"api://{client_id}"],
                "key": key,
                "mcpReadbackVerified": True,
                "redirectUris": [callbacks[key]],
                "servicePrincipalObjectId": (
                    f"{app_number:08d}-0000-4000-8000-000000000002"
                ),
                "signInAudience": "AzureADMyOrg",
            }
        )
    receipt = {
        "applications": app_receipts,
        "environment": "dev",
        "foundationOutputsSha256": "a" * 64,
        "materializedAt": "2026-07-18T15:00:00Z",
        "materializedHandoffSha256": "b" * 64,
        "mcpEvidenceSha256": "c" * 64,
        "mutationChannel": "Azure MCP",
        "schemaVersion": "1.0.0",
        "specSha256": entra.sha256(entra._canonical(spec)).hexdigest(),
        "status": "VERIFIED",
        "tenantId": "6b45974d-e2fe-4a1e-abad-41f2e788b9e8",
    }
    receipt_path = tmp_path / "entra-receipt.json"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    _validate("entra-materialization-receipt.schema.json", receipt)
    receipt_digest = entra.verify_receipt(
        receipt_path,
        expected_environment="dev",
        expected_assurance_client_id=clients["assurance-console"],
        expected_assistant_client_id=clients["policy-assistant"],
        expected_tenant_id="6b45974d-e2fe-4a1e-abad-41f2e788b9e8",
    )
    assert len(receipt_digest) == 64

    app_receipts[0]["assignments"] = [
        item
        for item in app_receipts[0]["assignments"]
        if item["roleValue"] != "Assurance.AuthorizationProbe"
    ]
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(entra.EntraHandoffError, match="managed-identity"):
        entra.verify_receipt(
            receipt_path,
            expected_environment="dev",
            expected_assurance_client_id=clients["assurance-console"],
            expected_assistant_client_id=clients["policy-assistant"],
        )


def test_workload_handoff_requires_private_receipts_but_uploads_only_digests() -> None:
    workflow = (ROOT / ".github" / "workflows" / "azure-handoff.yml").read_text(
        encoding="utf-8"
    )
    preflight = (ROOT / "scripts" / "azure" / "preflight.sh").read_text(encoding="utf-8")

    assert "AICA_CORPUS_MATERIALIZATION_RECEIPT_B64" in workflow
    assert "AICA_ENTRA_MATERIALIZATION_RECEIPT_B64" in workflow
    assert "corpusMaterializationReceiptSha256" in workflow
    assert "entraMaterializationReceiptSha256" in workflow
    uploaded_paths = workflow.split("name: azure-mcp-handoff-", maxsplit=1)[1]
    assert "aica-corpus-materialization-receipt.json" not in uploaded_paths
    assert "aica-entra-materialization-receipt.json" not in uploaded_paths
    assert "AICA_CORPUS_MATERIALIZATION_RECEIPT" in preflight
    assert "prepare-corpus-handoff.py" in preflight
    assert "AICA_ENTRA_MATERIALIZATION_RECEIPT" in preflight
    assert "prepare-entra-handoff.py" in preflight
