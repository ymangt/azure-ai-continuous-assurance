#!/usr/bin/env python3
"""Bind workload parameters to one successful exact-commit supply-chain image set."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, cast


class ImageHandoffError(RuntimeError):
    """The supply-chain image set is incomplete, ambiguous, or inconsistent."""


IMAGE_SPECS = {
    "assuranceApiImage": ("api", "deploy/api.Dockerfile", "image-api.json"),
    "assuranceJobImage": ("job", "deploy/job.Dockerfile", "image-job.json"),
    "consoleUiImage": ("apps-console", "apps/console/Dockerfile", "image-apps-console.json"),
    "assistantUiImage": (
        "apps-policy-assistant",
        "apps/policy-assistant/Dockerfile",
        "image-apps-policy-assistant.json",
    ),
}
PLACEHOLDERS = {
    "assessedGitCommit": "SET_ME_40_HEX_SOURCE_COMMIT",
    "assuranceApiImage": "SET_ME_API_IMAGE_WITH_DIGEST",
    "assuranceJobImage": "SET_ME_JOB_IMAGE_WITH_DIGEST",
    "consoleUiImage": "SET_ME_CONSOLE_IMAGE_WITH_DIGEST",
    "assistantUiImage": "SET_ME_ASSISTANT_IMAGE_WITH_DIGEST",
}
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_PATTERN = re.compile(
    r"ghcr\.io/[a-z0-9._-]+/[a-z0-9._/-]+@sha256:[0-9a-f]{64}"
)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _read_object(path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        content = path.read_bytes()
        value = json.loads(content.decode())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImageHandoffError(f"invalid JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ImageHandoffError(f"JSON input must be an object: {path}")
    return cast(dict[str, Any], value), content


def _parameter(content: str, name: str) -> str:
    pattern = re.compile(rf"^\s*param\s+{re.escape(name)}\s*=\s*'([^'\r\n]*)'\s*$", re.MULTILINE)
    values = pattern.findall(content)
    if len(values) != 1:
        raise ImageHandoffError(f"parameter file must define {name} exactly once")
    return values[0]


def _replace_parameter(content: str, name: str, value: str) -> str:
    pattern = re.compile(
        rf"^(\s*param\s+{re.escape(name)}\s*=\s*')[^'\r\n]*('\s*)$",
        re.MULTILINE,
    )
    updated, count = pattern.subn(lambda match: f"{match.group(1)}{value}{match.group(2)}", content)
    if count != 1:
        raise ImageHandoffError(f"parameter file must define {name} exactly once")
    return updated


def _record(records_dir: Path, parameter: str, source_commit: str) -> tuple[dict[str, str], str]:
    component, dockerfile, basename = IMAGE_SPECS[parameter]
    paths = sorted(records_dir.rglob(basename))
    if len(paths) != 1:
        raise ImageHandoffError(f"expected exactly one {basename}, found {len(paths)}")
    value, content = _read_object(paths[0])
    expected_keys = {
        "image",
        "digest",
        "sourceCommit",
        "dockerfile",
        "signed",
        "provenanceAttested",
    }
    if set(value) != expected_keys:
        raise ImageHandoffError(f"{basename}: image record has an unexpected shape")
    image = str(value.get("image", ""))
    digest = str(value.get("digest", ""))
    if not IMAGE_PATTERN.fullmatch(image) or not DIGEST_PATTERN.fullmatch(digest):
        raise ImageHandoffError(f"{basename}: image or digest is not an immutable GHCR reference")
    if image.rsplit("@", 1)[1] != digest:
        raise ImageHandoffError(f"{basename}: image reference and digest disagree")
    expected_image_pattern = re.compile(
        rf"ghcr\.io/[a-z0-9._-]+/aica-{re.escape(component)}@{re.escape(digest)}"
    )
    if not expected_image_pattern.fullmatch(image):
        raise ImageHandoffError(f"{basename}: image repository does not match its component")
    if value.get("sourceCommit") != source_commit:
        raise ImageHandoffError(f"{basename}: source commit does not match the selected workflow run")
    if value.get("dockerfile") != dockerfile:
        raise ImageHandoffError(f"{basename}: Dockerfile provenance is incorrect")
    if value.get("signed") is not True or value.get("provenanceAttested") is not True:
        raise ImageHandoffError(f"{basename}: signed provenance is incomplete")
    return (
        {
            "component": component,
            "digest": digest,
            "dockerfile": dockerfile,
            "image": image,
            "recordSha256": sha256(content).hexdigest(),
        },
        image,
    )


def prepare(
    parameter_file: Path,
    records_dir: Path,
    *,
    source_commit: str,
    workflow_run_id: int,
    output: Path,
) -> str:
    if not COMMIT_PATTERN.fullmatch(source_commit):
        raise ImageHandoffError("source commit must be lowercase 40-hex")
    if workflow_run_id <= 0:
        raise ImageHandoffError("workflow run ID must be positive")
    try:
        content = parameter_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ImageHandoffError(f"cannot read parameter file: {exc}") from exc
    if not re.search(r"^\s*param\s+enableWorkloads\s*=\s*true\s*$", content, re.MULTILINE):
        raise ImageHandoffError("supply-chain image binding is only valid for workload parameters")

    images: dict[str, dict[str, str]] = {}
    desired: dict[str, str] = {"assessedGitCommit": source_commit}
    for parameter in IMAGE_SPECS:
        images[parameter], desired[parameter] = _record(records_dir, parameter, source_commit)
    image_refs = [desired[parameter] for parameter in IMAGE_SPECS]
    if len(set(image_refs)) != len(image_refs):
        raise ImageHandoffError("supply-chain image references must be distinct")

    for name, expected in desired.items():
        current = _parameter(content, name)
        if current not in {PLACEHOLDERS[name], expected}:
            raise ImageHandoffError(f"{name} conflicts with verified supply-chain provenance")
        content = _replace_parameter(content, name, expected)
    receipt = {
        "$schema": "../../schemas/supply-chain-image-set.schema.json",
        "images": images,
        "mutationChannel": "GitHub Actions read-only",
        "schemaVersion": "1.0.0",
        "sourceCommit": source_commit,
        "status": "VERIFIED",
        "workflowPath": ".github/workflows/supply-chain.yml",
        "workflowRunId": workflow_run_id,
    }
    receipt_bytes = _canonical(receipt)
    if output.exists():
        raise ImageHandoffError(f"refusing to replace existing receipt: {output}")
    parameter_file.write_text(content, encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(receipt_bytes)
    return sha256(receipt_bytes).hexdigest()


def _validated_image_set(receipt_path: Path) -> tuple[dict[str, Any], bytes]:
    receipt, content = _read_object(receipt_path)
    expected_top_level = {
        "$schema",
        "images",
        "mutationChannel",
        "schemaVersion",
        "sourceCommit",
        "status",
        "workflowPath",
        "workflowRunId",
    }
    if set(receipt) != expected_top_level or content != _canonical(receipt):
        raise ImageHandoffError("supply-chain image-set receipt is not canonical or has extra fields")
    source_commit = receipt.get("sourceCommit")
    if (
        receipt.get("$schema") != "../../schemas/supply-chain-image-set.schema.json"
        or receipt.get("schemaVersion") != "1.0.0"
        or receipt.get("status") != "VERIFIED"
        or receipt.get("mutationChannel") != "GitHub Actions read-only"
        or receipt.get("workflowPath") != ".github/workflows/supply-chain.yml"
        or type(receipt.get("workflowRunId")) is not int
        or cast(int, receipt["workflowRunId"]) <= 0
        or not isinstance(source_commit, str)
        or not COMMIT_PATTERN.fullmatch(source_commit)
    ):
        raise ImageHandoffError("supply-chain image-set receipt provenance is invalid")
    images = receipt.get("images")
    if not isinstance(images, dict) or set(images) != set(IMAGE_SPECS):
        raise ImageHandoffError("supply-chain image-set receipt is incomplete")
    image_refs: set[str] = set()
    for parameter, (component, dockerfile, _basename) in IMAGE_SPECS.items():
        raw = images.get(parameter)
        if not isinstance(raw, dict) or set(raw) != {
            "component",
            "digest",
            "dockerfile",
            "image",
            "recordSha256",
        }:
            raise ImageHandoffError(f"{parameter}: receipt entry is malformed")
        image = str(raw.get("image", ""))
        digest = str(raw.get("digest", ""))
        expected_image_pattern = re.compile(
            rf"ghcr\.io/[a-z0-9._-]+/aica-{re.escape(component)}@{re.escape(digest)}"
        )
        if (
            raw.get("component") != component
            or raw.get("dockerfile") != dockerfile
            or not IMAGE_PATTERN.fullmatch(image)
            or not DIGEST_PATTERN.fullmatch(digest)
            or image.rsplit("@", 1)[1] != digest
            or not expected_image_pattern.fullmatch(image)
            or not isinstance(raw.get("recordSha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", raw["recordSha256"])
        ):
            raise ImageHandoffError(f"{parameter}: receipt provenance is invalid")
        image_refs.add(image)
    if len(image_refs) != len(IMAGE_SPECS):
        raise ImageHandoffError("supply-chain image references must be distinct")
    return receipt, content


def verify_receipt(parameter_file: Path, receipt_path: Path) -> str:
    receipt, content = _validated_image_set(receipt_path)
    try:
        parameter_content = parameter_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ImageHandoffError(f"cannot read parameter file: {exc}") from exc
    if _parameter(parameter_content, "assessedGitCommit") != receipt["sourceCommit"]:
        raise ImageHandoffError("assessedGitCommit does not match supply-chain provenance")
    for parameter in IMAGE_SPECS:
        if _parameter(parameter_content, parameter) != receipt["images"][parameter]["image"]:
            raise ImageHandoffError(f"{parameter} does not match supply-chain provenance")
    return sha256(content).hexdigest()


def _resource_subscription(resource_id: object, resource_type: str) -> str | None:
    if not isinstance(resource_id, str):
        return None
    match = re.fullmatch(
        rf"/subscriptions/([0-9a-f-]{{36}})/resourceGroups/[A-Za-z0-9._()-]+"
        rf"/providers/Microsoft\.App/{resource_type}/[a-z0-9-]+",
        resource_id,
        flags=re.IGNORECASE,
    )
    return match.group(1).casefold() if match else None


def verify_deployment_receipt(
    image_set_path: Path,
    deployment_receipt_path: Path,
    *,
    expected_subscription_id: str | None = None,
) -> str:
    """Compare Azure MCP active-resource readback to the intended signed image set."""

    image_set, image_set_content = _validated_image_set(image_set_path)
    receipt, content = _read_object(deployment_receipt_path)
    expected_top_level = {
        "$schema",
        "assessmentJob",
        "mcpEvidenceSha256",
        "mutationChannel",
        "policyAssistant",
        "schemaVersion",
        "sourceCommit",
        "sourceImageSetSha256",
        "status",
        "subscriptionId",
        "verifiedAt",
    }
    if set(receipt) != expected_top_level or content != _canonical(receipt):
        raise ImageHandoffError(
            "deployment image readback receipt is not canonical or has extra fields"
        )
    subscription_id = receipt.get("subscriptionId")
    verified_at = receipt.get("verifiedAt")
    try:
        parsed_verified_at = datetime.fromisoformat(str(verified_at).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ImageHandoffError("deployment image readback timestamp is invalid") from exc
    if (
        receipt.get("$schema")
        != "../../schemas/deployment-image-readback-receipt.schema.json"
        or receipt.get("schemaVersion") != "1.0.0"
        or receipt.get("status") != "VERIFIED"
        or receipt.get("mutationChannel") != "Azure MCP read-only"
        or not isinstance(subscription_id, str)
        or not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", subscription_id)
        or not isinstance(verified_at, str)
        or not verified_at.endswith("Z")
        or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", verified_at)
        or parsed_verified_at.tzinfo is None
        or not isinstance(receipt.get("mcpEvidenceSha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", receipt["mcpEvidenceSha256"])
        or receipt.get("sourceCommit") != image_set["sourceCommit"]
        or receipt.get("sourceImageSetSha256") != sha256(image_set_content).hexdigest()
    ):
        raise ImageHandoffError("deployment image readback receipt provenance is invalid")
    if (
        expected_subscription_id is not None
        and subscription_id != expected_subscription_id.casefold()
    ):
        raise ImageHandoffError("deployment image readback subscription does not match")

    expected_tags = {
        "deployedSourceCommit": image_set["sourceCommit"],
        "assuranceApiImageSha256": image_set["images"]["assuranceApiImage"]["digest"].removeprefix(
            "sha256:"
        ),
        "assistantUiImageSha256": image_set["images"]["assistantUiImage"]["digest"].removeprefix(
            "sha256:"
        ),
        "assuranceJobImageSha256": image_set["images"]["assuranceJobImage"]["digest"].removeprefix(
            "sha256:"
        ),
    }
    policy_assistant = receipt.get("policyAssistant")
    if not isinstance(policy_assistant, dict) or set(policy_assistant) != {
        "activeRevision",
        "activeRevisionTrafficWeight",
        "containers",
        "provenanceTags",
        "resourceId",
    }:
        raise ImageHandoffError("Policy Assistant deployment readback is malformed")
    if (
        _resource_subscription(policy_assistant.get("resourceId"), "containerApps")
        != subscription_id
        or not isinstance(policy_assistant.get("activeRevision"), str)
        or not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,127}", policy_assistant["activeRevision"])
        or type(policy_assistant.get("activeRevisionTrafficWeight")) is not int
        or policy_assistant.get("activeRevisionTrafficWeight") != 100
        or policy_assistant.get("containers")
        != {
            "policy-assistant-api": image_set["images"]["assuranceApiImage"]["image"],
            "policy-assistant-ui": image_set["images"]["assistantUiImage"]["image"],
        }
        or policy_assistant.get("provenanceTags") != expected_tags
    ):
        raise ImageHandoffError(
            "Policy Assistant active revision does not match supply-chain provenance"
        )

    assessment_job = receipt.get("assessmentJob")
    if not isinstance(assessment_job, dict) or set(assessment_job) != {
        "container",
        "provenanceTags",
        "resourceId",
    }:
        raise ImageHandoffError("assessment job deployment readback is malformed")
    if (
        _resource_subscription(assessment_job.get("resourceId"), "jobs") != subscription_id
        or assessment_job.get("container")
        != {
            "image": image_set["images"]["assuranceJobImage"]["image"],
            "name": "assessor",
        }
        or assessment_job.get("provenanceTags") != expected_tags
    ):
        raise ImageHandoffError("assessment job does not match supply-chain provenance")
    return sha256(content).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare_parser = commands.add_parser("prepare")
    prepare_parser.add_argument("parameter_file", type=Path)
    prepare_parser.add_argument("records_dir", type=Path)
    prepare_parser.add_argument("--source-commit", required=True)
    prepare_parser.add_argument("--workflow-run-id", type=int, required=True)
    prepare_parser.add_argument("--output", type=Path, required=True)
    verify_parser = commands.add_parser("verify-receipt")
    verify_parser.add_argument("parameter_file", type=Path)
    verify_parser.add_argument("receipt", type=Path)
    deployment_parser = commands.add_parser("verify-deployment-receipt")
    deployment_parser.add_argument("image_set", type=Path)
    deployment_parser.add_argument("receipt", type=Path)
    deployment_parser.add_argument("--expected-subscription-id")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            digest = prepare(
                args.parameter_file,
                args.records_dir,
                source_commit=args.source_commit,
                workflow_run_id=args.workflow_run_id,
                output=args.output,
            )
            print(f"Supply-chain image set prepared: {digest}")
        elif args.command == "verify-receipt":
            digest = verify_receipt(args.parameter_file, args.receipt)
            print(f"Supply-chain image set verified: {digest}")
        else:
            digest = verify_deployment_receipt(
                args.image_set,
                args.receipt,
                expected_subscription_id=args.expected_subscription_id,
            )
            print(f"Deployment image readback verified: {digest}")
    except (ImageHandoffError, OSError) as exc:
        print(f"Image handoff failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
