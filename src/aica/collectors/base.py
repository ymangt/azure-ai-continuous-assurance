"""Collector protocol and evidence-envelope normalization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from aica.domain.models import Classification, EvidenceFreshness, EvidenceItem
from aica.evidence.redaction import sanitize
from aica.util.canonical import canonical_json_bytes, sha256_bytes, sha256_value
from aica.util.ids import new_id


class CollectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    observation_window_start: datetime
    observation_window_end: datetime
    scope: tuple[str, ...]
    output_dir: Path
    assessed_git_commit: str | None = None
    redaction_profile: str = "public-v1"
    max_age: timedelta = timedelta(hours=26)


class CollectedEvidence(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid", frozen=True)

    item: EvidenceItem
    raw_payload: Any
    normalized_payload: Any
    sanitized_payload: Any


class Collector(Protocol):
    name: str
    version: str

    async def collect(self, request: CollectionRequest) -> list[CollectedEvidence]: ...


def envelope(
    *,
    request: CollectionRequest,
    source: str,
    collector_version: str,
    query: dict[str, Any],
    raw_payload: Any,
    normalized_payload: Any | None = None,
    classification: Classification = Classification.INTERNAL,
    captured_at: datetime | None = None,
    authorized: bool = True,
    collection_error: str | None = None,
) -> CollectedEvidence:
    captured_at = captured_at or datetime.now(UTC)
    normalized_payload = raw_payload if normalized_payload is None else normalized_payload
    sanitized = sanitize(normalized_payload)
    raw_bytes = canonical_json_bytes(raw_payload)
    sanitized_bytes = canonical_json_bytes(sanitized)
    evidence_id = new_id("ev")
    evidence_dir = request.output_dir / "evidence" / evidence_id
    private_uri = evidence_dir / "normalized.json"
    freshness = (
        EvidenceFreshness.UNKNOWN
        if collection_error
        else (
            EvidenceFreshness.FRESH
            if captured_at >= datetime.now(UTC) - request.max_age
            else EvidenceFreshness.STALE
        )
    )
    item = EvidenceItem(
        id=evidence_id,
        source=source,
        scope=request.scope,
        captured_at=captured_at,
        observation_window_start=request.observation_window_start,
        observation_window_end=request.observation_window_end,
        query_digest=sha256_value(query),
        collector_version=collector_version,
        private_artifact_uri=str(private_uri),
        media_type="application/json",
        sha256=sha256_bytes(raw_bytes),
        sanitized_sha256=sha256_bytes(sanitized_bytes),
        classification=classification,
        freshness=freshness,
        redaction_profile=request.redaction_profile,
        authorized=authorized,
        collection_error=collection_error,
        payload=sanitized,
    )
    return CollectedEvidence(
        item=item,
        raw_payload=raw_payload,
        normalized_payload=normalized_payload,
        sanitized_payload=sanitized,
    )


def write_collected(evidence: CollectedEvidence, output_dir: Path) -> list[Path]:
    evidence_dir = output_dir / "evidence" / evidence.item.id
    evidence_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "raw.json": evidence.raw_payload,
        "normalized.json": evidence.normalized_payload,
        "sanitized.json": evidence.sanitized_payload,
        "metadata.json": evidence.item.model_dump(mode="json", exclude={"payload"}),
    }
    paths: list[Path] = []
    for name, content in outputs.items():
        path = evidence_dir / name
        path.write_bytes(canonical_json_bytes(content))
        paths.append(path)
    return paths
