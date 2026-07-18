"""Turn deterministic test results into reviewable assessments and risks."""

from __future__ import annotations

from datetime import UTC, datetime

from aica.domain.models import (
    ControlAssessment,
    ControlObjective,
    Effectiveness,
    EvidenceFreshness,
    Finding,
    Observation,
    ResultStatus,
    Risk,
    RiskTreatment,
    Severity,
    TestResult,
    risk_severity,
)
from aica.util.ids import new_id

MATERIAL_OBJECTIVES = {"AC-6.1", "SC-7.1", "AI-AC-01.1", "AI-DP-01.1"}


def build_assessments(
    run_id: str,
    objectives: tuple[ControlObjective, ...],
    results: list[TestResult],
) -> tuple[list[ControlAssessment], list[Observation], list[Finding], list[Risk]]:
    by_objective = {result.objective_id: result for result in results}
    assessments: list[ControlAssessment] = []
    observations: list[Observation] = []
    findings: list[Finding] = []
    risks: list[Risk] = []
    now = datetime.now(UTC)
    for objective in objectives:
        result = by_objective.get(objective.id)
        if result is None:
            result = TestResult(
                id=new_id("test"),
                run_id=run_id,
                objective_id=objective.id,
                status=ResultStatus.NOT_RUN,
                reason_code="MANUAL_REVIEW_REQUIRED",
                reason="manual or hybrid procedure requires reviewer evidence",
                test_version="1.0.0",
            )
            results.append(result)
        if result.status == ResultStatus.PASS:
            design = operating = conclusion = Effectiveness.EFFECTIVE
            freshness = EvidenceFreshness.FRESH
            coverage = 100.0
        elif result.status == ResultStatus.FAIL:
            design = Effectiveness.PARTIALLY_EFFECTIVE
            operating = conclusion = Effectiveness.INEFFECTIVE
            freshness = EvidenceFreshness.FRESH
            coverage = 100.0
        else:
            design = operating = conclusion = Effectiveness.NOT_CONCLUDED
            freshness = (
                EvidenceFreshness.STALE
                if result.reason_code == "STALE_EVIDENCE"
                else EvidenceFreshness.UNKNOWN
            )
            coverage = 0.0
        assessments.append(
            ControlAssessment(
                id=new_id("assessment"),
                run_id=run_id,
                objective_id=objective.id,
                design_effectiveness=design,
                operating_effectiveness=operating,
                coverage_percent=coverage,
                conclusion=conclusion,
                rationale=result.reason,
                evidence_freshness=freshness,
            )
        )
        unavailable = result.status == ResultStatus.ERROR or (
            result.status == ResultStatus.NOT_RUN
            and result.reason_code != "MANUAL_REVIEW_REQUIRED"
        )
        if result.status != ResultStatus.FAIL and not unavailable:
            continue
        observation = Observation(
            id=new_id("obs"),
            run_id=run_id,
            objective_id=objective.id,
            condition=result.reason,
            evidence_refs=result.evidence_refs,
            observed_at=now,
        )
        observations.append(observation)
        severity = Severity.HIGH if objective.id in MATERIAL_OBJECTIVES else Severity.MODERATE
        finding = Finding(
            id=new_id("finding"),
            run_id=run_id,
            title=(
                f"{objective.title} could not be concluded from required evidence"
                if unavailable
                else f"{objective.title} did not meet the assessment objective"
            ),
            criteria=objective.objective,
            condition=result.reason,
            cause=(
                "Required automated evidence was unavailable, unauthorized, stale, or otherwise "
                "not evaluable."
                if unavailable
                else "The assessed configuration or operating evidence did not satisfy the "
                "deterministic rule."
            ),
            consequence=(
                "The automated assurance objective cannot be concluded and a control weakness "
                "could remain undetected."
                if unavailable
                else "The control objective may not operate as intended within the assessed scope."
            ),
            affected_controls=(objective.source_control,),
            affected_assets=tuple(objective.subject_selector.split(",")),
            severity=severity,
            severity_rationale=(
                "Material access, boundary, or AI tool-control weakness."
                if severity == Severity.HIGH
                else "Control weakness with bounded synthetic-data impact."
            ),
            evidence_refs=result.evidence_refs,
        )
        findings.append(finding)
        likelihood, impact = (4, 4) if severity == Severity.HIGH else (3, 3)
        inherent_score = likelihood * impact
        residual_likelihood = max(1, likelihood - 1)
        residual_impact = impact
        residual_score = residual_likelihood * residual_impact
        risks.append(
            Risk(
                id=new_id("risk"),
                finding_id=finding.id,
                statement=(
                    f"Because {finding.cause.lower()}, {finding.condition.lower()} may occur, "
                    f"resulting in {finding.consequence.lower()}"
                ),
                likelihood=likelihood,
                impact=impact,
                inherent_score=inherent_score,
                inherent_rating=risk_severity(inherent_score),
                residual_likelihood=residual_likelihood,
                residual_impact=residual_impact,
                residual_score=residual_score,
                residual_rating=risk_severity(residual_score),
                confidence="MODERATE",
                treatment=RiskTreatment.MITIGATE,
                owner=objective.owner,
                rationale="Residual score assumes the documented remediation is implemented and retested.",
            )
        )
    return assessments, observations, findings, risks
