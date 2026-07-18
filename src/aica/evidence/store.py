"""Append-only local repository used by CI and the API.

Azure Blob and Table adapters implement the same layout at deployment time; the
filesystem adapter keeps every workflow reproducible without cloud credentials.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from azure.core.exceptions import ResourceExistsError
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.storage.blob import BlobServiceClient, ContentSettings

from aica.domain.models import AssessmentPackage, ReviewDecision
from aica.util.canonical import canonical_json_bytes, sha256_file


class VersionConflictError(RuntimeError):
    pass


class JsonRunRepository:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _run_path(self, run_id: str) -> Path:
        direct = self.root / run_id / "package.json"
        if direct.exists():
            return direct
        for candidate in self.root.glob("*/package.json"):
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            candidate_id = raw.get("run", {}).get("id") or raw.get("id")
            if candidate_id == run_id:
                return candidate
        raise FileNotFoundError(f"assessment run {run_id!r} was not found")

    def list_runs(self) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for candidate in sorted(self.root.glob("*/package.json")):
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            run = raw.get("run", raw)
            summaries.append(run)
        return sorted(summaries, key=lambda item: item.get("started_at", ""), reverse=True)

    def get_package(self, run_id: str) -> AssessmentPackage:
        return AssessmentPackage.model_validate_json(
            self._run_path(run_id).read_text(encoding="utf-8")
        )

    def write_package(self, package: AssessmentPackage) -> Path:
        path = self.root / package.run.id / "package.json"
        if path.exists():
            raise FileExistsError(f"run {package.run.id} is immutable and already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(path, canonical_json_bytes(package))
        return path

    def append_decision(self, decision: ReviewDecision) -> Path:
        decision_dir = self.root / "decisions" / decision.subject_id
        decision_dir.mkdir(parents=True, exist_ok=True)
        existing = sorted(decision_dir.glob("*.json"))
        current_version = len(existing)
        if decision.expected_version != current_version:
            raise VersionConflictError(
                f"expected version {decision.expected_version}, current version is {current_version}"
            )
        path = decision_dir / f"{decision.version:08d}-{decision.id}.json"
        self._atomic_write(path, canonical_json_bytes(decision))
        return path

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


class AzureBlobArtifactStore:
    """Immutable Blob artifact publisher authenticated with managed identity."""

    def __init__(
        self,
        account_url: str,
        container: str,
        *,
        managed_identity_client_id: str | None,
    ):
        credential = (
            ManagedIdentityCredential(client_id=managed_identity_client_id)
            if managed_identity_client_id
            else DefaultAzureCredential()
        )
        self.client = BlobServiceClient(account_url, credential).get_container_client(container)

    @staticmethod
    def _media_type(path: Path) -> str:
        return {
            ".json": "application/json",
            ".html": "text/html; charset=utf-8",
            ".csv": "text/csv; charset=utf-8",
        }.get(path.suffix.casefold(), "application/octet-stream")

    def upload_file(
        self,
        path: Path,
        blob_name: str,
        *,
        run_id: str,
        classification: str,
    ) -> tuple[str, str | None]:
        blob = self.client.get_blob_client(blob_name)
        metadata = {
            "runid": run_id,
            "classification": classification,
            "sha256": sha256_file(path),
        }
        try:
            with path.open("rb") as handle:
                result = blob.upload_blob(
                    handle,
                    overwrite=False,
                    metadata=metadata,
                    content_settings=ContentSettings(content_type=self._media_type(path)),
                )
            version_id = result.get("version_id")
        except ResourceExistsError:
            properties = blob.get_blob_properties()
            version_id = properties.version_id
        return blob.url, version_id

    def upload_tree(
        self,
        root: Path,
        *,
        prefix: str,
        run_id: str,
        classification: str,
    ) -> dict[str, tuple[str, str | None]]:
        uploaded: dict[str, tuple[str, str | None]] = {}
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            uploaded[relative] = self.upload_file(
                path,
                f"{prefix.rstrip('/')}/{relative}",
                run_id=run_id,
                classification=classification,
            )
        return uploaded
