#!/usr/bin/env python3
"""Build and verify an immutable Azure MCP policy-corpus handoff."""

from __future__ import annotations

import argparse
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
CORPUS_ROOT = ROOT / "data" / "policy-corpus"
SCHEMA_VERSION = "1.0.0"
CONTAINER_NAME = "synthetic-corpus"
MCP_TOOL = "mcp__azure__storage"
UPLOAD_COMMAND = "storage_blob_upload"
VERIFY_COMMAND = "storage_blob_get"
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
SAFE_SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class HandoffError(RuntimeError):
    """The corpus cannot be safely handed off or verified."""


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _digest(value: bytes) -> str:
    return sha256(value).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"invalid JSON input {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HandoffError(f"JSON input must be an object: {path}")
    return cast(dict[str, Any], value)


def _source_snapshot() -> tuple[dict[str, Any], bytes, list[dict[str, Any]]]:
    manifest_path = CORPUS_ROOT / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = _read_json(manifest_path)
    if manifest.get("classification") != "SYNTHETIC":
        raise HandoffError("production corpus handoff is restricted to SYNTHETIC content")
    corpus_id = manifest.get("corpus_id")
    version = manifest.get("version")
    if not isinstance(corpus_id, str) or not SAFE_SEGMENT.fullmatch(corpus_id):
        raise HandoffError("corpus_id is missing or unsafe")
    if not isinstance(version, str) or not SAFE_SEGMENT.fullmatch(version):
        raise HandoffError("corpus version is missing or unsafe")
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not 15 <= len(documents) <= 25:
        raise HandoffError("corpus manifest must contain 15-25 documents")
    if manifest.get("active_document_count") != len(documents):
        raise HandoffError("active_document_count does not match the document list")

    entries: list[dict[str, Any]] = []
    expected_names = {"manifest.json"}
    seen_ids: set[str] = set()
    for raw in documents:
        if not isinstance(raw, dict):
            raise HandoffError("corpus document entry must be an object")
        item = cast(dict[str, Any], raw)
        document_id = item.get("id")
        relative = item.get("path")
        if not isinstance(document_id, str) or not document_id or document_id in seen_ids:
            raise HandoffError(f"duplicate or empty corpus document id: {document_id!r}")
        if (
            not isinstance(relative, str)
            or "\\" in relative
            or Path(relative).name != relative
            or relative.startswith(".")
            or Path(relative).suffix.casefold() not in {".md", ".json"}
        ):
            raise HandoffError(f"unsafe corpus document path: {relative!r}")
        if relative in expected_names:
            raise HandoffError(f"duplicate corpus document path: {relative}")
        if "synthetic" not in str(item.get("classification", "")).casefold():
            raise HandoffError(f"{document_id}: non-synthetic classification")
        content = (CORPUS_ROOT / relative).read_bytes()
        expected_size = item.get("size_bytes")
        expected_sha = item.get("sha256")
        if expected_size != len(content):
            raise HandoffError(f"{relative}: byte count differs from the source manifest")
        if not isinstance(expected_sha, str) or not HEX_SHA256.fullmatch(expected_sha):
            raise HandoffError(f"{relative}: source manifest SHA-256 is invalid")
        if _digest(content) != expected_sha:
            raise HandoffError(f"{relative}: content differs from the source manifest")
        try:
            content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HandoffError(f"{relative}: corpus documents must be UTF-8") from exc
        seen_ids.add(document_id)
        expected_names.add(relative)
        entries.append(
            {
                "contentType": (
                    "text/markdown; charset=utf-8"
                    if Path(relative).suffix.casefold() == ".md"
                    else "application/json; charset=utf-8"
                ),
                "documentId": document_id,
                "path": relative,
                "sha256": expected_sha,
                "sizeBytes": len(content),
            }
        )

    actual_names = {
        path.name for path in CORPUS_ROOT.iterdir() if path.is_file() and not path.name.startswith(".")
    }
    if actual_names != expected_names:
        raise HandoffError(
            "corpus directory membership differs from the manifest: "
            f"expected={sorted(expected_names)!r}, actual={sorted(actual_names)!r}"
        )
    return manifest, manifest_bytes, sorted(entries, key=lambda item: str(item["path"]))


def expected_prefix() -> str:
    manifest, _, _ = _source_snapshot()
    return f"{manifest['corpus_id']}/{manifest['version']}"


def expected_handoff() -> dict[str, Any]:
    manifest, manifest_bytes, document_entries = _source_snapshot()
    prefix = f"{manifest['corpus_id']}/{manifest['version']}"
    payload_entries = [
        {
            "contentType": "application/json; charset=utf-8",
            "documentId": None,
            "path": "manifest.json",
            "sha256": _digest(manifest_bytes),
            "sizeBytes": len(manifest_bytes),
        },
        *document_entries,
    ]
    for entry in payload_entries:
        entry["blobName"] = f"{prefix}/{entry['path']}"
        entry["localFile"] = f"payload/{entry['path']}"
    return {
        "$schema": "../../schemas/corpus-handoff.schema.json",
        "azureMcp": {
            "mutationChannel": "Azure MCP only",
            "tool": MCP_TOOL,
            "uploadCommand": UPLOAD_COMMAND,
            "verificationCommand": VERIFY_COMMAND,
        },
        "container": CONTAINER_NAME,
        "corpus": {
            "classification": "SYNTHETIC",
            "documentCount": len(document_entries),
            "id": manifest["corpus_id"],
            "manifestSha256": _digest(manifest_bytes),
            "prefix": prefix,
            "version": manifest["version"],
        },
        "payload": payload_entries,
        "postconditions": {
            "applicationStartupVerification": (
                "download exact prefix membership and verify manifest byte counts and SHA-256"
            ),
            "exactBlobSetRequired": True,
            "materializationReceiptRequiredBeforeWorkloads": True,
        },
        "schemaVersion": SCHEMA_VERSION,
    }


README = """# Synthetic policy corpus Azure MCP handoff

No Azure operation was performed while producing this bundle. The only approved mutation path is
Azure MCP `mcp__azure__storage` command `storage_blob_upload`. Upload each `payload` file to the
exact `blobName` in `handoff.json`; uploads are create-only, so a changed corpus must increment its
manifest version and use a new immutable prefix.

After upload, use `storage_blob_get` with the exact prefix and for each individual blob. Preserve a
private receipt containing the exact list, byte counts, content hashes, ETags, last-modified values,
MCP evidence digest, and successful operation status. Run `prepare-corpus-handoff.py verify-receipt`
against that receipt. A workload deployment must supply the protected receipt to preflight through
`AICA_CORPUS_MATERIALIZATION_RECEIPT`; the receipt is evidence and must not be committed or published.

The Policy Assistant downloads the complete prefix on startup and independently verifies exact blob
membership, UTF-8 decoding, classifications, byte counts, and SHA-256 digests before indexing.
"""


def _expected_bundle_files() -> dict[str, bytes]:
    handoff = expected_handoff()
    values = {
        "README.md": README.encode(),
        "handoff.json": _canonical_json(handoff),
    }
    for entry in cast(list[dict[str, Any]], handoff["payload"]):
        relative = str(entry["path"])
        values[f"payload/{relative}"] = (CORPUS_ROOT / relative).read_bytes()
    return values


def _checksum_document(files: dict[str, bytes]) -> bytes:
    return "".join(f"{_digest(files[name])}  {name}\n" for name in sorted(files)).encode()


def prepare_bundle(output: Path) -> str:
    if output.exists() and any(output.iterdir()):
        raise HandoffError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    files = _expected_bundle_files()
    for relative, content in files.items():
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    checksums = _checksum_document(files)
    (output / "SHA256SUMS").write_bytes(checksums)
    bundle_sha = _digest(checksums)
    (output / "BUNDLE-SHA256").write_text(f"{bundle_sha}\n", encoding="utf-8")
    return bundle_sha


def verify_bundle(bundle: Path) -> str:
    expected = _expected_bundle_files()
    checksums = _checksum_document(expected)
    expected["SHA256SUMS"] = checksums
    expected["BUNDLE-SHA256"] = f"{_digest(checksums)}\n".encode()
    actual_names = {
        path.relative_to(bundle).as_posix() for path in bundle.rglob("*") if path.is_file()
    }
    if actual_names != set(expected):
        raise HandoffError(
            "bundle membership mismatch: "
            f"expected={sorted(expected)!r}, actual={sorted(actual_names)!r}"
        )
    for relative, content in expected.items():
        if (bundle / relative).read_bytes() != content:
            raise HandoffError(f"bundle content mismatch: {relative}")
    return _digest(checksums)


def _uuid(value: object, label: str) -> str:
    try:
        parsed = UUID(str(value))
    except (ValueError, AttributeError) as exc:
        raise HandoffError(f"{label} must be a UUID") from exc
    return str(parsed)


def verify_receipt(
    receipt_path: Path,
    *,
    expected_subscription_id: str | None = None,
    expected_environment: str | None = None,
) -> str:
    receipt = _read_json(receipt_path)
    handoff = expected_handoff()
    payload = cast(list[dict[str, Any]], handoff["payload"])
    expected_by_blob = {str(item["blobName"]): item for item in payload}
    expected_names = sorted(expected_by_blob)
    expected_files = _expected_bundle_files()
    bundle_sha = _digest(_checksum_document(expected_files))

    exact = {
        "schemaVersion": SCHEMA_VERSION,
        "status": "VERIFIED",
        "mutationChannel": "Azure MCP",
        "azureMcpTool": MCP_TOOL,
        "uploadCommand": UPLOAD_COMMAND,
        "verificationCommand": VERIFY_COMMAND,
        "container": CONTAINER_NAME,
        "prefix": expected_prefix(),
        "bundleSha256": bundle_sha,
        "sourceManifestSha256": handoff["corpus"]["manifestSha256"],
        "exactBlobSetVerified": True,
    }
    for field, expected_value in exact.items():
        if receipt.get(field) != expected_value:
            raise HandoffError(f"receipt {field} does not match the handoff")

    subscription_id = _uuid(receipt.get("subscriptionId"), "receipt subscriptionId")
    if expected_subscription_id and subscription_id != _uuid(
        expected_subscription_id, "expected subscription ID"
    ):
        raise HandoffError("receipt subscription does not match the deployment subscription")
    environment = receipt.get("environment")
    if environment not in {"dev", "demo"}:
        raise HandoffError("receipt environment must be dev or demo")
    if expected_environment and environment != expected_environment:
        raise HandoffError("receipt environment does not match the deployment environment")

    container_url = receipt.get("containerUrl")
    parsed_url = urlparse(str(container_url))
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or not parsed_url.hostname.endswith(".blob.core.windows.net")
        or parsed_url.query
        or parsed_url.fragment
        or parsed_url.path.rstrip("/") != f"/{CONTAINER_NAME}"
    ):
        raise HandoffError("receipt containerUrl is not the HTTPS synthetic-corpus container")
    if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("mcpEvidenceSha256", ""))):
        raise HandoffError("receipt must bind the private Azure MCP evidence with SHA-256")
    materialized = str(receipt.get("materializedAt", ""))
    if not materialized.endswith("Z"):
        raise HandoffError("receipt materializedAt must be RFC3339 UTC")
    try:
        if datetime.fromisoformat(materialized.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError
    except ValueError as exc:
        raise HandoffError("receipt materializedAt must be RFC3339 UTC") from exc

    listed = receipt.get("listedBlobNames")
    if listed != expected_names:
        raise HandoffError("receipt does not record the exact expected blob set")
    blobs = receipt.get("blobs")
    if not isinstance(blobs, list) or len(blobs) != len(expected_names):
        raise HandoffError("receipt blob properties are incomplete")
    actual_by_blob: dict[str, dict[str, Any]] = {}
    for raw in blobs:
        if not isinstance(raw, dict):
            raise HandoffError("receipt blob property entry must be an object")
        item = cast(dict[str, Any], raw)
        name = str(item.get("blobName", ""))
        if not name or name in actual_by_blob:
            raise HandoffError(f"receipt has a duplicate or empty blob name: {name!r}")
        actual_by_blob[name] = item
    if set(actual_by_blob) != set(expected_by_blob):
        raise HandoffError("receipt blob property names differ from the handoff")
    for name, expected in expected_by_blob.items():
        actual = actual_by_blob[name]
        required = {
            "sourcePath": expected["path"],
            "sizeBytes": expected["sizeBytes"],
            "sha256": expected["sha256"],
            "uploadStatus": "SUCCEEDED",
            "propertiesVerified": True,
        }
        for field, expected_value in required.items():
            if actual.get(field) != expected_value:
                raise HandoffError(f"{name}: receipt {field} differs from the handoff")
        for field in ("etag", "lastModified", "contentHash"):
            if not isinstance(actual.get(field), str) or not actual[field].strip():
                raise HandoffError(f"{name}: receipt is missing Azure {field}")
    return bundle_sha


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("output", type=Path)
    verify = subparsers.add_parser("verify")
    verify.add_argument("bundle", type=Path)
    receipt = subparsers.add_parser("verify-receipt")
    receipt.add_argument("receipt", type=Path)
    receipt.add_argument("--expected-subscription-id")
    receipt.add_argument("--expected-environment", choices=("dev", "demo"))
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            digest = prepare_bundle(args.output)
            print(f"corpus handoff prepared: {digest}")
        elif args.command == "verify":
            digest = verify_bundle(args.bundle)
            print(f"corpus handoff verified: {digest}")
        else:
            digest = verify_receipt(
                args.receipt,
                expected_subscription_id=args.expected_subscription_id,
                expected_environment=args.expected_environment,
            )
            print(f"corpus materialization receipt verified: {digest}")
    except (HandoffError, OSError) as exc:
        print(f"corpus handoff failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
