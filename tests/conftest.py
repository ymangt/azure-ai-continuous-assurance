from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from aica.domain.models import (
    AssessmentMethod,
    AssessmentPackage,
    AssessmentRun,
    Classification,
    ControlAssessment,
    ControlObjective,
    Effectiveness,
    EvidenceFreshness,
    EvidenceItem,
    ResultStatus,
    RunStatus,
    SystemRecord,
    TestResult,
)
from aica.util.canonical import sha256_value


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


def objective(objective_id: str = "SC-7.1", source_control: str = "SC-7") -> ControlObjective:
    return ControlObjective(
        id=objective_id,
        source_control=source_control,
        title="Boundary protection",
        objective="Verify that public administrative access is prohibited.",
        methods=(AssessmentMethod.TEST,),
        subject_selector="synthetic/network-boundary",
        cadence="daily and on change",
        evidence_requirements=("Azure Resource Graph network configuration",),
        owner="Cloud Security Owner",
        automated=True,
    )


def evidence(
    now: datetime,
    *,
    evidence_id: str = "ev-1",
    source: str = "azure.resource_graph.inventory",
    payload: Any = None,
    freshness: EvidenceFreshness = EvidenceFreshness.FRESH,
    authorized: bool = True,
    collection_error: str | None = None,
) -> EvidenceItem:
    payload = payload if payload is not None else {"compliant": True}
    return EvidenceItem(
        id=evidence_id,
        source=source,
        scope=("synthetic/test",),
        captured_at=now,
        observation_window_start=now - timedelta(hours=1),
        observation_window_end=now,
        query_digest=sha256_value({"source": source}),
        collector_version="1.0.0",
        private_artifact_uri=f"private://{evidence_id}",
        media_type="application/json",
        sha256=sha256_value(payload),
        sanitized_sha256=sha256_value(payload),
        classification=Classification.INTERNAL,
        freshness=freshness,
        redaction_profile="public-v1",
        authorized=authorized,
        collection_error=collection_error,
        payload=payload,
    )


def package(now: datetime, root: Path | None = None) -> AssessmentPackage:
    control = objective()
    item = evidence(now)
    result = TestResult(
        id="test-1",
        run_id="run-1",
        objective_id=control.id,
        status=ResultStatus.PASS,
        reason_code="EXPECTED_CONDITION_MET",
        reason="No public inbound RDP rule was found.",
        test_version="1.0.0",
        evidence_refs=(item.id,),
        evaluated_at=now,
    )
    assessment = ControlAssessment(
        id="assessment-1",
        run_id="run-1",
        objective_id=control.id,
        design_effectiveness=Effectiveness.EFFECTIVE,
        operating_effectiveness=Effectiveness.EFFECTIVE,
        coverage_percent=100,
        conclusion=Effectiveness.EFFECTIVE,
        rationale="Fresh evidence supports the objective.",
        evidence_freshness=EvidenceFreshness.FRESH,
    )
    run = AssessmentRun(
        id="run-1",
        trigger="manual",
        scope=("synthetic/test",),
        observation_window_start=now - timedelta(hours=1),
        observation_window_end=now,
        git_commit="abcdef0",
        collector_version="1.0.0",
        evaluator_version="1.0.0",
        started_at=now,
        ended_at=now + timedelta(seconds=1),
        status=RunStatus.COMPLETED,
        estimated_cost_cad=0,
    )
    return AssessmentPackage(
        run=run,
        system=SystemRecord.model_validate_json(
            Path("config/system-record.json").read_text(encoding="utf-8")
        ),
        objectives=(control,),
        evidence=(item,),
        test_results=(result,),
        assessments=(assessment,),
    )
