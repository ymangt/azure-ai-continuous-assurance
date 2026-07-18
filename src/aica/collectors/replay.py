"""Replay collector for deterministic CI and public demonstrations."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from aica.collectors.base import CollectedEvidence, CollectionRequest, envelope
from aica.domain.models import Classification


def _classification(value: object) -> Classification:
    normalized = str(value).upper()
    if normalized in Classification:
        return Classification(normalized)
    if "PUBLIC" in normalized:
        return Classification.PUBLIC
    if "RESTRICTED" in normalized or "CONTROLLED" in normalized:
        return Classification.RESTRICTED_TEST_EVIDENCE
    if "CONFIDENTIAL" in normalized:
        return Classification.CONFIDENTIAL
    return Classification.INTERNAL


class ReplayCollector:
    name = "replay"
    version = "1.0.0"

    def __init__(self, fixture_dir: Path):
        self.fixture_dir = fixture_dir

    async def collect(self, request: CollectionRequest) -> list[CollectedEvidence]:
        evidence: list[CollectedEvidence] = []
        for path in sorted(self.fixture_dir.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            captured_at = None
            if raw.get("captured_at"):
                captured_at = datetime.fromisoformat(
                    str(raw["captured_at"]).replace("Z", "+00:00")
                )
            evidence.append(
                envelope(
                    request=request,
                    source=str(raw.get("source", path.stem)),
                    collector_version=self.version,
                    query=raw.get("query", {"fixture": path.name}),
                    raw_payload=raw.get("payload", raw),
                    classification=_classification(raw.get("classification", "INTERNAL")),
                    captured_at=captured_at,
                )
            )
        return evidence
