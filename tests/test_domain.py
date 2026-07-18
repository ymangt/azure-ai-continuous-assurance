from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from aica.domain.models import (
    AssessmentRun,
    ControlAssessment,
    Effectiveness,
    EvidenceFreshness,
    ResultStatus,
    Risk,
    RiskTreatment,
    RunStatus,
    Severity,
)
from aica.domain.models import (
    TestResult as AssuranceTestResult,
)


def test_pass_requires_evidence(now) -> None:
    with pytest.raises(ValidationError, match="PASS requires"):
        AssuranceTestResult(
            id="test-1",
            run_id="run-1",
            objective_id="SC-7.1",
            status=ResultStatus.PASS,
            reason_code="EXPECTED_CONDITION_MET",
            reason="Rule passed.",
            test_version="1.0.0",
            evaluated_at=now,
        )


def test_stale_evidence_cannot_produce_conclusion() -> None:
    with pytest.raises(ValidationError, match="NOT_CONCLUDED"):
        ControlAssessment(
            id="assessment-1",
            run_id="run-1",
            objective_id="SC-7.1",
            design_effectiveness=Effectiveness.EFFECTIVE,
            operating_effectiveness=Effectiveness.EFFECTIVE,
            coverage_percent=100,
            conclusion=Effectiveness.EFFECTIVE,
            rationale="This conclusion must be rejected.",
            evidence_freshness=EvidenceFreshness.STALE,
        )


def test_risk_score_and_rating_are_derived() -> None:
    risk = Risk(
        id="risk-1",
        finding_id="finding-1",
        statement="Because access is broad, unauthorized access may occur, causing data exposure.",
        likelihood=4,
        impact=4,
        inherent_score=16,
        inherent_rating=Severity.HIGH,
        residual_likelihood=2,
        residual_impact=4,
        residual_score=8,
        residual_rating=Severity.MODERATE,
        confidence="HIGH",
        treatment=RiskTreatment.MITIGATE,
        owner="Cloud Security Owner",
        rationale="Remediation narrows the allowed source.",
    )
    assert risk.inherent_score == 16
    with pytest.raises(ValidationError, match="inherent score"):
        risk.model_copy(update={"inherent_score": 15}, deep=True).model_validate(
            {**risk.model_dump(), "inherent_score": 15}
        )


def test_retest_run_requires_prior_run(now) -> None:
    with pytest.raises(ValidationError, match="prior run"):
        AssessmentRun(
            id="run-2",
            trigger="retest",
            scope=("synthetic/test",),
            observation_window_start=now - timedelta(hours=1),
            observation_window_end=now,
            git_commit="abcdef0",
            collector_version="1.0.0",
            evaluator_version="1.0.0",
            started_at=now,
            status=RunStatus.QUEUED,
        )
