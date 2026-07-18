"""Read-only composition over generated and checked-in sanitized runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol, cast

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient

from aica.domain.models import AssessmentPackage
from aica.evidence.manifest import (
    SignedManifest,
    load_signed_manifest,
    verify_manifest,
    verify_manifest_signature,
)
from aica.util.canonical import sha256_bytes


class PackageNotFoundError(FileNotFoundError):
    pass


class PackageIntegrityError(RuntimeError):
    pass


class RunStore(Protocol):
    def list_runs_raw(self) -> list[dict[str, Any]]: ...

    def get_raw(self, run_id: str) -> dict[str, Any]: ...

    def get(self, run_id: str) -> AssessmentPackage: ...

    def latest_raw(self) -> dict[str, Any]: ...


class CompositeRunStore:
    def __init__(
        self,
        roots: list[Path],
        *,
        trusted_key_fingerprints: frozenset[str] = frozenset(),
        trusted_key_id_prefix: str | None = None,
    ):
        self.roots = roots
        self.trusted_key_fingerprints = trusted_key_fingerprints
        self.trusted_key_id_prefix = trusted_key_id_prefix

    def _candidates(self) -> list[Path]:
        candidates: list[Path] = []
        for root in self.roots:
            if root.exists():
                candidates.extend(root.glob("*/package.json"))
                candidates.extend(root.glob("*/assessment-package.json"))
        return sorted(set(candidates))

    @staticmethod
    def _run(raw: dict[str, Any]) -> dict[str, Any]:
        return cast(dict[str, Any], raw.get("run", raw.get("assessment_run", raw)))

    def _trust_errors(self, signed: SignedManifest) -> list[str]:
        errors: list[str] = []
        if (
            self.trusted_key_fingerprints
            and signed.key_fingerprint not in self.trusted_key_fingerprints
        ):
            errors.append("manifest signing-key fingerprint is not trusted")
        if self.trusted_key_id_prefix and not signed.key_id.startswith(self.trusted_key_id_prefix):
            errors.append("manifest key identifier is outside the trusted key")
        return errors

    def _with_verified_manifest(self, raw: dict[str, Any], package_path: Path) -> dict[str, Any]:
        manifest_path = package_path.parent / "run-manifest.json"
        if not manifest_path.is_file():
            raise PackageIntegrityError(f"signed manifest missing for {package_path.name}")
        try:
            signed = load_signed_manifest(manifest_path)
        except (ValueError, json.JSONDecodeError) as exc:
            raise PackageIntegrityError("signed manifest is malformed") from exc
        errors = verify_manifest(signed, package_path.parent) + self._trust_errors(signed)
        if errors:
            raise PackageIntegrityError("; ".join(errors))
        source_run = self._run(raw)
        source_run_id = str(source_run.get("id", source_run.get("run_id", "")))
        if signed.manifest.run_id != source_run_id:
            raise PackageIntegrityError("manifest run ID does not match package run ID")
        enriched = json.loads(json.dumps(raw))
        self._run(enriched)["manifest_digest"] = signed.manifest_sha256
        return cast(dict[str, Any], enriched)

    def list_runs_raw(self) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for path in self._candidates():
            raw = self._with_verified_manifest(json.loads(path.read_text(encoding="utf-8")), path)
            run = self._run(raw)
            run_id = str(run.get("id", run.get("run_id", "")))
            if run_id:
                by_id[run_id] = run
        return sorted(
            by_id.values(),
            key=lambda item: str(item.get("started_at", item.get("start", ""))),
            reverse=True,
        )

    def package_path(self, run_id: str) -> Path:
        for path in self._candidates():
            raw = json.loads(path.read_text(encoding="utf-8"))
            run = self._run(raw)
            candidate = str(run.get("id", run.get("run_id", "")))
            if candidate == run_id:
                return path
        raise PackageNotFoundError(run_id)

    def get_raw(self, run_id: str) -> dict[str, Any]:
        path = self.package_path(run_id)
        raw = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
        return self._with_verified_manifest(raw, path)

    def get(self, run_id: str) -> AssessmentPackage:
        return AssessmentPackage.model_validate(self.get_raw(run_id))

    def latest_raw(self) -> dict[str, Any]:
        runs = self.list_runs_raw()
        if not runs:
            raise PackageNotFoundError("no assessment runs are available")
        run_id = str(runs[0].get("id", runs[0].get("run_id")))
        return self.get_raw(run_id)


class AzureBlobRunStore:
    """Read derived packages directly from the versioned evidence account."""

    def __init__(
        self,
        account_url: str,
        container: str,
        *,
        managed_identity_client_id: str | None,
        trusted_key_fingerprints: frozenset[str],
        trusted_key_id_prefix: str | None,
    ):
        credential = (
            ManagedIdentityCredential(client_id=managed_identity_client_id)
            if managed_identity_client_id
            else DefaultAzureCredential()
        )
        self.container = BlobServiceClient(account_url, credential).get_container_client(container)
        self.trusted_key_fingerprints = trusted_key_fingerprints
        self.trusted_key_id_prefix = trusted_key_id_prefix

    def _package_names(self) -> list[str]:
        return sorted(
            blob.name
            for blob in self.container.list_blobs(name_starts_with="runs/")
            if blob.name.endswith("/package.json")
        )

    def _download_bytes(self, blob_name: str) -> bytes:
        try:
            return bytes(self.container.download_blob(blob_name).readall())
        except ResourceNotFoundError as exc:
            raise PackageNotFoundError(blob_name) from exc

    def _download(self, blob_name: str) -> dict[str, Any]:
        return cast(dict[str, Any], json.loads(self._download_bytes(blob_name)))

    def _manifest(self, run_id: str) -> SignedManifest:
        try:
            raw = self._download(f"runs/{run_id}/run-manifest.json")
            signed = SignedManifest.model_validate(raw)
        except PackageNotFoundError as exc:
            raise PackageIntegrityError(f"signed manifest missing for run {run_id}") from exc
        except ValueError as exc:
            raise PackageIntegrityError("signed manifest is malformed") from exc
        errors = verify_manifest_signature(signed)
        if (
            self.trusted_key_fingerprints
            and signed.key_fingerprint not in self.trusted_key_fingerprints
        ):
            errors.append("manifest signing-key fingerprint is not trusted")
        if self.trusted_key_id_prefix and not signed.key_id.startswith(self.trusted_key_id_prefix):
            errors.append("manifest key identifier is outside the trusted key")
        if errors:
            raise PackageIntegrityError("; ".join(errors))
        return signed

    def _with_verified_manifest(
        self, raw: dict[str, Any], run_id: str, package_content: bytes
    ) -> dict[str, Any]:
        signed = self._manifest(run_id)
        artifact = next(
            (item for item in signed.manifest.artifacts if item.path == "package.json"), None
        )
        if artifact is None:
            raise PackageIntegrityError("manifest does not cover package.json")
        if artifact.sha256 != sha256_bytes(package_content) or artifact.size_bytes != len(
            package_content
        ):
            raise PackageIntegrityError("package.json digest or size does not match manifest")
        source_run = cast(dict[str, Any], raw.get("run", raw))
        source_run_id = str(source_run.get("id", source_run.get("run_id", "")))
        if signed.manifest.run_id != source_run_id:
            raise PackageIntegrityError("manifest run ID does not match package run ID")
        enriched = json.loads(json.dumps(raw))
        run = cast(dict[str, Any], enriched.get("run", enriched))
        run["manifest_digest"] = signed.manifest_sha256
        return cast(dict[str, Any], enriched)

    def list_runs_raw(self) -> list[dict[str, Any]]:
        runs = []
        for name in self._package_names():
            run_id = name.split("/")[-2]
            content = self._download_bytes(name)
            raw = self._with_verified_manifest(
                cast(dict[str, Any], json.loads(content)), run_id, content
            )
            runs.append(cast(dict[str, Any], raw.get("run", raw)))
        return sorted(runs, key=lambda item: str(item.get("started_at", "")), reverse=True)

    def get_raw(self, run_id: str) -> dict[str, Any]:
        content = self._download_bytes(f"runs/{run_id}/package.json")
        return self._with_verified_manifest(
            cast(dict[str, Any], json.loads(content)), run_id, content
        )

    def get(self, run_id: str) -> AssessmentPackage:
        return AssessmentPackage.model_validate(self.get_raw(run_id))

    def latest_raw(self) -> dict[str, Any]:
        runs = self.list_runs_raw()
        if not runs:
            raise PackageNotFoundError("no assessment runs are available")
        return self.get_raw(str(runs[0]["id"]))
