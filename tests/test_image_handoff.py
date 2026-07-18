from __future__ import annotations

import importlib.util
import json
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).parents[1]
SOURCE_COMMIT = "a" * 40
PARAMETER_ORDER = (
    "assuranceApiImage",
    "assuranceJobImage",
    "consoleUiImage",
    "assistantUiImage",
)


def _module() -> ModuleType:
    path = ROOT / "scripts" / "azure" / "prepare-image-handoff.py"
    spec = importlib.util.spec_from_file_location("aica_prepare_image_handoff", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parameter_file(path: Path, *, conflict: bool = False) -> None:
    api_value = (
        f"ghcr.io/example/conflicting@sha256:{'f' * 64}"
        if conflict
        else "SET_ME_API_IMAGE_WITH_DIGEST"
    )
    path.write_text(
        "\n".join(
            (
                "using '../../infra/main.bicep'",
                "param enableWorkloads = true",
                "param assessedGitCommit = 'SET_ME_40_HEX_SOURCE_COMMIT'",
                f"param assuranceApiImage = '{api_value}'",
                "param assuranceJobImage = 'SET_ME_JOB_IMAGE_WITH_DIGEST'",
                "param consoleUiImage = 'SET_ME_CONSOLE_IMAGE_WITH_DIGEST'",
                "param assistantUiImage = 'SET_ME_ASSISTANT_IMAGE_WITH_DIGEST'",
                "",
            )
        ),
        encoding="utf-8",
    )


def _records(path: Path) -> dict[str, dict[str, Any]]:
    specs = {
        "api": ("deploy/api.Dockerfile", "image-api.json"),
        "job": ("deploy/job.Dockerfile", "image-job.json"),
        "apps-console": ("apps/console/Dockerfile", "image-apps-console.json"),
        "apps-policy-assistant": (
            "apps/policy-assistant/Dockerfile",
            "image-apps-policy-assistant.json",
        ),
    }
    values: dict[str, dict[str, Any]] = {}
    for index, (component, (dockerfile, name)) in enumerate(specs.items(), start=1):
        digest = f"sha256:{index:064x}"
        value = {
            "image": f"ghcr.io/example/aica-{component}@{digest}",
            "digest": digest,
            "sourceCommit": SOURCE_COMMIT,
            "dockerfile": dockerfile,
            "signed": True,
            "provenanceAttested": True,
        }
        component_dir = path / component
        component_dir.mkdir(parents=True)
        (component_dir / name).write_text(json.dumps(value), encoding="utf-8")
        values[name] = value
    return values


def _prepare(tmp_path: Path) -> tuple[ModuleType, Path, Path, Path, dict[str, Any]]:
    module = _module()
    parameter_file = tmp_path / "workload.bicepparam"
    records_dir = tmp_path / "records"
    receipt_path = tmp_path / "supply-chain-image-set.json"
    _parameter_file(parameter_file)
    records = _records(records_dir)
    module.prepare(
        parameter_file,
        records_dir,
        source_commit=SOURCE_COMMIT,
        workflow_run_id=12345,
        output=receipt_path,
    )
    return module, parameter_file, records_dir, receipt_path, records


def test_image_handoff_materializes_exact_commit_set_and_valid_receipt(tmp_path: Path) -> None:
    module, parameter_file, _records_dir, receipt_path, records = _prepare(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (ROOT / "schemas" / "supply-chain-image-set.schema.json").read_text(encoding="utf-8")
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=str)
    assert not errors, "\n".join(error.message for error in errors)
    assert module.verify_receipt(parameter_file, receipt_path) == module.sha256(
        receipt_path.read_bytes()
    ).hexdigest()
    assert receipt["sourceCommit"] == SOURCE_COMMIT
    assert receipt["workflowRunId"] == 12345
    assert set(receipt["images"]) == set(PARAMETER_ORDER)

    parameter_content = parameter_file.read_text(encoding="utf-8")
    assert f"param assessedGitCommit = '{SOURCE_COMMIT}'" in parameter_content
    for parameter, record_name in zip(
        PARAMETER_ORDER,
        ("image-api.json", "image-job.json", "image-apps-console.json", "image-apps-policy-assistant.json"),
        strict=True,
    ):
        assert f"param {parameter} = '{records[record_name]['image']}'" in parameter_content


@pytest.mark.parametrize(
    ("record_name", "field", "value", "message"),
    (
        ("image-api.json", "sourceCommit", "b" * 40, "source commit"),
        ("image-job.json", "dockerfile", "deploy/api.Dockerfile", "Dockerfile"),
        ("image-apps-console.json", "signed", False, "signed provenance"),
        (
            "image-apps-policy-assistant.json",
            "provenanceAttested",
            False,
            "signed provenance",
        ),
        (
            "image-api.json",
            "digest",
            f"sha256:{'f' * 64}",
            "reference and digest disagree",
        ),
        (
            "image-job.json",
            "image",
            f"ghcr.io/example/unrelated@sha256:{2:064x}",
            "repository does not match its component",
        ),
    ),
)
def test_image_handoff_rejects_untrusted_record_provenance(
    tmp_path: Path,
    record_name: str,
    field: str,
    value: object,
    message: str,
) -> None:
    module = _module()
    parameter_file = tmp_path / "workload.bicepparam"
    records_dir = tmp_path / "records"
    _parameter_file(parameter_file)
    _records(records_dir)
    record_path = next(records_dir.rglob(record_name))
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record[field] = value
    record_path.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(module.ImageHandoffError, match=message):
        module.prepare(
            parameter_file,
            records_dir,
            source_commit=SOURCE_COMMIT,
            workflow_run_id=12345,
            output=tmp_path / "receipt.json",
        )


@pytest.mark.parametrize("duplicate", (False, True))
def test_image_handoff_rejects_missing_or_duplicate_component(
    tmp_path: Path, duplicate: bool
) -> None:
    module = _module()
    parameter_file = tmp_path / "workload.bicepparam"
    records_dir = tmp_path / "records"
    _parameter_file(parameter_file)
    _records(records_dir)
    api_record = next(records_dir.rglob("image-api.json"))
    if duplicate:
        duplicate_dir = records_dir / "duplicate"
        duplicate_dir.mkdir()
        (duplicate_dir / api_record.name).write_bytes(api_record.read_bytes())
    else:
        api_record.unlink()

    with pytest.raises(module.ImageHandoffError, match=r"expected exactly one image-api\.json"):
        module.prepare(
            parameter_file,
            records_dir,
            source_commit=SOURCE_COMMIT,
            workflow_run_id=12345,
            output=tmp_path / "receipt.json",
        )


def test_image_handoff_rejects_conflicting_parameter_without_mutation(tmp_path: Path) -> None:
    module = _module()
    parameter_file = tmp_path / "workload.bicepparam"
    records_dir = tmp_path / "records"
    _parameter_file(parameter_file, conflict=True)
    _records(records_dir)
    before = parameter_file.read_bytes()

    with pytest.raises(module.ImageHandoffError, match="conflicts with verified"):
        module.prepare(
            parameter_file,
            records_dir,
            source_commit=SOURCE_COMMIT,
            workflow_run_id=12345,
            output=tmp_path / "receipt.json",
        )
    assert parameter_file.read_bytes() == before
    assert not (tmp_path / "receipt.json").exists()


def test_image_handoff_receipt_rejects_parameter_or_schema_drift(tmp_path: Path) -> None:
    module, parameter_file, _records_dir, receipt_path, _records_by_name = _prepare(tmp_path)
    original_parameter = parameter_file.read_text(encoding="utf-8")
    parameter_file.write_text(
        original_parameter.replace(f"sha256:{1:064x}", f"sha256:{9:064x}"),
        encoding="utf-8",
    )
    with pytest.raises(module.ImageHandoffError, match="does not match supply-chain provenance"):
        module.verify_receipt(parameter_file, receipt_path)

    parameter_file.write_text(original_parameter, encoding="utf-8")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["$schema"] = "unexpected.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(module.ImageHandoffError, match="receipt provenance is invalid"):
        module.verify_receipt(parameter_file, receipt_path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("boolean-run-id", "receipt provenance is invalid"),
        ("numeric-record-hash", "receipt provenance is invalid"),
    ),
)
def test_image_handoff_receipt_enforces_json_types(
    tmp_path: Path, mutation: str, message: str
) -> None:
    module, parameter_file, _records_dir, receipt_path, _records_by_name = _prepare(tmp_path)
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if mutation == "boolean-run-id":
        receipt["workflowRunId"] = True
    else:
        receipt["images"]["assuranceApiImage"]["recordSha256"] = int("1" * 64)
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(module.ImageHandoffError, match=message):
        module.verify_receipt(parameter_file, receipt_path)


def test_azure_handoff_binds_checkout_to_exact_four_image_artifacts() -> None:
    workflow = (ROOT / ".github" / "workflows" / "azure-handoff.yml").read_text(
        encoding="utf-8"
    )
    preflight = (ROOT / "scripts" / "azure" / "preflight.sh").read_text(
        encoding="utf-8"
    )

    assert "supply_chain_run_id:" in workflow
    assert "actions: read" in workflow
    assert "and .head_sha == $handoff_commit" in workflow
    assert 'and .status == "completed"' in workflow
    assert 'and .conclusion == "success"' in workflow
    assert "for component in api job apps-console apps-policy-assistant" in workflow
    assert 'artifact_name="sbom-${component}-${source_commit}"' in workflow
    assert 'actual_archive_digest="sha256:' in workflow
    assert "image-${component}.json" in workflow
    assert "sbom-${component}.spdx.json" in workflow
    assert "prepare-image-handoff.py prepare" in workflow
    assert "AICA_SUPPLY_CHAIN_IMAGE_SET=/tmp/supply-chain-image-set.json" in workflow
    assert "supplyChainImageSetSha256" in workflow
    uploaded_paths = workflow.split("name: azure-mcp-handoff-", maxsplit=1)[1]
    assert "/tmp/supply-chain-image-set.json" in uploaded_paths  # noqa: S108
    assert "AICA_SUPPLY_CHAIN_IMAGE_SET" in preflight
    assert "prepare-image-handoff.py" in preflight
    assert 'verify-receipt "$parameter_file" "$supply_chain_image_set"' in preflight


def test_bicep_binds_assistant_and_assessor_to_identical_deployment_provenance() -> None:
    main = (ROOT / "infra" / "main.bicep").read_text(encoding="utf-8")
    sut = (ROOT / "infra" / "modules" / "sut-plane.bicep").read_text(encoding="utf-8")
    workloads = (ROOT / "infra" / "modules" / "control-workloads.bicep").read_text(
        encoding="utf-8"
    )
    assessment = (ROOT / ".github" / "workflows" / "assessment.yml").read_text(
        encoding="utf-8"
    )

    for image, digest in (
        ("assuranceApiImage", "assuranceApiImageSha256"),
        ("assuranceJobImage", "assuranceJobImageSha256"),
        ("assistantUiImage", "assistantUiImageSha256"),
    ):
        assert f"last(split({image}, '@sha256:'))" in main
        assert f"{digest}: {digest}" in main

    assistant_resource = sut.split("resource policyAssistant", maxsplit=1)[1].split(
        "resource assistantAuth", maxsplit=1
    )[0]
    job_resource = workloads.split("resource assessmentJob", maxsplit=1)[1].split(
        "resource commandWorkerJob", maxsplit=1
    )[0]
    assert "image: assistantUiImage" in assistant_resource
    assert "image: assuranceApiImage" in assistant_resource
    assert "image: assuranceJobImage" in job_resource
    for key in (
        "AICA_DEPLOYED_SOURCE_COMMIT",
        "AICA_ASSURANCE_API_IMAGE_SHA256",
        "AICA_ASSISTANT_UI_IMAGE_SHA256",
        "AICA_ASSURANCE_JOB_IMAGE_SHA256",
    ):
        assert key in assistant_resource
        assert key in job_resource
        assert key in assessment
    for tag in (
        "deployedSourceCommit",
        "assuranceApiImageSha256",
        "assistantUiImageSha256",
        "assuranceJobImageSha256",
    ):
        assert tag in assistant_resource
        assert tag in job_resource


def _deployment_receipt(image_set_path: Path) -> dict[str, Any]:
    image_set = json.loads(image_set_path.read_text(encoding="utf-8"))
    subscription_id = "1f6b0863-6c5d-4ae4-bfbe-a21492048366"
    tags = {
        "deployedSourceCommit": image_set["sourceCommit"],
        "assuranceApiImageSha256": image_set["images"]["assuranceApiImage"][
            "digest"
        ].removeprefix("sha256:"),
        "assistantUiImageSha256": image_set["images"]["assistantUiImage"][
            "digest"
        ].removeprefix("sha256:"),
        "assuranceJobImageSha256": image_set["images"]["assuranceJobImage"][
            "digest"
        ].removeprefix("sha256:"),
    }
    return {
        "$schema": "../../schemas/deployment-image-readback-receipt.schema.json",
        "assessmentJob": {
            "container": {
                "image": image_set["images"]["assuranceJobImage"]["image"],
                "name": "assessor",
            },
            "provenanceTags": tags,
            "resourceId": (
                f"/subscriptions/{subscription_id}/resourceGroups/rg-aica-control-cc"
                "/providers/Microsoft.App/jobs/caj-aica-assess-dev"
            ),
        },
        "mcpEvidenceSha256": "e" * 64,
        "mutationChannel": "Azure MCP read-only",
        "policyAssistant": {
            "activeRevision": "ca-aica-assistant-dev--abc123",
            "activeRevisionTrafficWeight": 100,
            "containers": {
                "policy-assistant-api": image_set["images"]["assuranceApiImage"]["image"],
                "policy-assistant-ui": image_set["images"]["assistantUiImage"]["image"],
            },
            "provenanceTags": tags,
            "resourceId": (
                f"/subscriptions/{subscription_id}/resourceGroups/rg-aica-sut-eus2"
                "/providers/Microsoft.App/containerApps/ca-aica-assistant-dev"
            ),
        },
        "schemaVersion": "1.0.0",
        "sourceCommit": image_set["sourceCommit"],
        "sourceImageSetSha256": sha256(image_set_path.read_bytes()).hexdigest(),
        "status": "VERIFIED",
        "subscriptionId": subscription_id,
        "verifiedAt": "2026-07-18T18:00:00Z",
    }


def test_deployment_readback_receipt_binds_active_images_and_tags(tmp_path: Path) -> None:
    module, _parameter_file_path, _records_dir, image_set_path, _records_by_name = _prepare(
        tmp_path
    )
    receipt = _deployment_receipt(image_set_path)
    schema = json.loads(
        (ROOT / "schemas" / "deployment-image-readback-receipt.schema.json").read_text(
            encoding="utf-8"
        )
    )
    errors = sorted(Draft202012Validator(schema).iter_errors(receipt), key=str)
    assert not errors, "\n".join(error.message for error in errors)
    receipt_path = tmp_path / "deployment-image-readback-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    digest = module.verify_deployment_receipt(
        image_set_path,
        receipt_path,
        expected_subscription_id=receipt["subscriptionId"],
    )
    assert digest == module.sha256(receipt_path.read_bytes()).hexdigest()

    receipt["policyAssistant"]["containers"]["policy-assistant-ui"] = (
        f"ghcr.io/example/aica-apps-policy-assistant@sha256:{'f' * 64}"
    )
    receipt_path.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(module.ImageHandoffError, match="active revision does not match"):
        module.verify_deployment_receipt(image_set_path, receipt_path)
