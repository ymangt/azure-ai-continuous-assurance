#!/usr/bin/env python3
"""Assemble strict API packages and local-only signed public sample manifests.

This is a deterministic data-shape adapter over the richer human-readable sample
records. Signatures use LocalEs256Signer and are CI/sample-only; production runs
must use KeyVaultEs256Signer after Azure MCP deployment verification.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from aica.collectors.ai import (
    compose_behavioral_evidence_payload,
    load_mapping_metrics,
    load_mapping_suggestion,
)
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
    ExceptionRecord,
    Finding,
    Observation,
    Remediation,
    Retest,
    ReviewDecision,
    ReviewState,
    Risk,
    RiskTreatment,
    Severity,
    SystemRecord,
    TestResult,
)
from aica.evidence.manifest import (
    CadCostBreakdown,
    LocalEs256Signer,
    ManifestArtifact,
    UnsignedManifest,
    sign_manifest,
)
from aica.pipeline import terminal_run_status
from aica.util.canonical import canonical_json_bytes, sha256_file, sha256_value

ROOT = Path(__file__).resolve().parents[2]
RUN_ROOT = ROOT / "data" / "sample-runs"
PROFILE_PATH = ROOT / "assurance" / "controls" / "control-profile.json"
SYSTEM_RECORD_PATH = ROOT / "config" / "system-record.json"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dt(value: str) -> datetime:
    if len(value) == 10:
        value += "T00:00:00Z"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def digest(value: str) -> str:
    return value.removeprefix("sha256:")


def objective_records() -> tuple[ControlObjective, ...]:
    profile = load(PROFILE_PATH)
    titles = {item["id"]: item["title"] for item in profile["controls"]}
    method_map = {
        "AUTOMATED": (AssessmentMethod.TEST,),
        "HYBRID": (AssessmentMethod.HYBRID,),
        "MANUAL": (AssessmentMethod.EXAMINE, AssessmentMethod.INTERVIEW),
    }
    return tuple(
        ControlObjective(
            id=item["id"],
            source_control=item["control_id"],
            title=f"{titles[item['control_id']]} — objective {item['id']}",
            objective=item["objective"],
            methods=method_map[item["method"]],
            subject_selector=item["subject_selector"],
            cadence=item["cadence"],
            evidence_requirements=tuple(item["evidence_requirements"]),
            owner=item["owner"],
            automated=item["method"] == "AUTOMATED",
            limitations=(item["limitations"],),
        )
        for item in profile["objectives"]
    )


def evidence_records(source: dict[str, Any]) -> tuple[EvidenceItem, ...]:
    classification_map = {
        "PUBLIC": Classification.PUBLIC,
        "INTERNAL": Classification.INTERNAL,
        "RESTRICTED_ASSURANCE": Classification.CONFIDENTIAL,
        "CONTROLLED_EVALUATION": Classification.RESTRICTED_TEST_EVIDENCE,
    }
    items: list[EvidenceItem] = []
    for item in source["items"]:
        error = item.get("collection_error")
        sanitized_payload = {"sanitized_summary": item["sanitized_summary"]}
        items.append(
            EvidenceItem(
                id=item["evidence_id"],
                source=item["source"],
                scope=(item["scope"],),
                captured_at=dt(item["captured_at"]),
                observation_window_start=dt(item["capture_window"]["start"]),
                observation_window_end=dt(item["capture_window"]["end"]),
                query_digest=digest(item["api_query_digest"]),
                collector_version=item["collector_version"],
                private_artifact_uri="private://withheld",
                media_type=item["media_type"],
                sha256=digest(item["sha256"]),
                sanitized_sha256=sha256_value(sanitized_payload),
                blob_version=None,
                classification=classification_map[item["classification"]],
                freshness=EvidenceFreshness(item["freshness"]["state"]),
                redaction_profile=item["redaction"]["profile"],
                authorized=error is None,
                collection_error=None if error is None else f"{error['code']}: {error['message']}",
                payload=sanitized_payload,
            )
        )
    return tuple(items)


def bind_sample_evaluation(
    evidence: tuple[EvidenceItem, ...], *, name: str, run_id: str
) -> tuple[EvidenceItem, ...]:
    """Carry the remediated replay read model inside its signed sample package."""

    if name != "remediated":
        return evidence
    cases = load(ROOT / "data" / "ai-evaluations" / "behavioral-cases.json")
    replay = load(ROOT / "data" / "ai-evaluations" / "replay-results.json")
    baseline = load(
        ROOT / "data" / "collector-fixtures" / "baseline" / "ai.behavioral_evaluation.json"
    )
    baseline_by_id = {
        str(item["id"]): item for item in baseline.get("payload", {}).get("nodes", [])
    }
    suggestion = load_mapping_suggestion(
        ROOT / "data" / "ai-evaluations" / "mapping-suggestion.json",
        run_id=run_id,
        evaluation_id=str(replay["evaluation_id"]),
    )
    payload = compose_behavioral_evidence_payload(
        cases=cases,
        results=replay,
        mapping_metrics=load_mapping_metrics(
            ROOT / "data" / "mapping-benchmark" / "human-labeled-examples.json"
        ),
        suggested_mapping=suggestion,
        baseline_by_id=baseline_by_id,
    )
    return tuple(
        item.model_copy(update={"payload": payload, "sanitized_sha256": sha256_value(payload)})
        if item.source == "AI_BEHAVIORAL_EVALUATION"
        else item
        for item in evidence
    )


def result_records(
    source: dict[str, Any], run_id: str, evaluated_at: datetime
) -> tuple[TestResult, ...]:
    reason_codes = {
        "PASS": "EXPECTED_CONDITION_MET",
        "FAIL": "EXPECTED_CONDITION_NOT_MET",
        "ERROR": "COLLECTION_ERROR",
        "NOT_RUN": "OUTSIDE_OBSERVATION_WINDOW",
        "NOT_APPLICABLE": "NOT_APPLICABLE_TO_SCOPE",
    }
    return tuple(
        TestResult(
            id=item["result_id"],
            run_id=run_id,
            objective_id=item["objective_id"],
            status=item["status"],
            reason_code=reason_codes[item["status"]],
            reason=item["reason"],
            test_version=item["test_version"],
            evidence_refs=tuple(item["evidence_refs"]),
            evaluated_at=evaluated_at,
            details={key: item[key] for key in ("finding_refs", "retest_ref") if key in item},
        )
        for item in source["results"]
    )


def effect(value: str) -> Effectiveness:
    if value in {"EFFECTIVE_WITH_LIMITATION", "EFFECTIVE_WITH_EXCEPTION"}:
        return Effectiveness.EFFECTIVE
    if value == "NOT_APPLICABLE":
        return Effectiveness.NOT_CONCLUDED
    return Effectiveness(value)


def assessment_records(
    source: dict[str, Any],
    objectives: tuple[ControlObjective, ...],
    results: tuple[TestResult, ...],
    evidence: tuple[EvidenceItem, ...],
    run_id: str,
) -> tuple[ControlAssessment, ...]:
    by_control = {item["control_id"]: item for item in source["assessments"]}
    result_by_objective = {item.objective_id: item for item in results}
    evidence_by_id = {item.id: item for item in evidence}
    output: list[ControlAssessment] = []
    for objective in objectives:
        result = result_by_objective[objective.id]
        control = by_control[objective.source_control]
        cited = [evidence_by_id[ref] for ref in result.evidence_refs]
        freshness = (
            EvidenceFreshness.FRESH
            if cited and all(item.freshness == EvidenceFreshness.FRESH for item in cited)
            else EvidenceFreshness.UNKNOWN
        )
        design = effect(control["design_effectiveness"])
        operating = effect(control["operating_effectiveness"])
        conclusion = effect(control["assessor_conclusion"])
        coverage = 100.0
        if result.status == "FAIL":
            operating = Effectiveness.INEFFECTIVE
            conclusion = Effectiveness.INEFFECTIVE
        elif result.status in {"ERROR", "NOT_RUN", "NOT_APPLICABLE"}:
            operating = Effectiveness.NOT_CONCLUDED
            conclusion = Effectiveness.NOT_CONCLUDED
            coverage = 0.0
        if freshness != EvidenceFreshness.FRESH:
            conclusion = Effectiveness.NOT_CONCLUDED
        output.append(
            ControlAssessment(
                id=f"CA-{run_id[-4:]}-{objective.id}",
                run_id=run_id,
                objective_id=objective.id,
                design_effectiveness=design,
                operating_effectiveness=operating,
                coverage_percent=coverage,
                conclusion=conclusion,
                reviewer=control["reviewer"],
                rationale=f"{result.reason} {control['rationale']}",
                evidence_freshness=freshness,
                review_state=ReviewState.ACCEPTED,
            )
        )
    return tuple(output)


OBS_OBJECTIVE = {
    "OBS-001": "SC-7.1",
    "OBS-002": "AI-DP-01.1",
    "OBS-003": "AI-AC-01.1",
    "OBS-004": "AI-TE-01.1",
    "OBS-005": "SI-4.1",
    "OBS-R-001": "SC-7.1",
    "OBS-R-002": "AI-DP-01.1",
    "OBS-R-003": "AI-AC-01.1",
    "OBS-R-004": "AI-TE-01.1",
    "OBS-R-005": "SI-4.1",
    "OBS-R-006": "SC-7.2",
}


INHERENT = {
    "RSK-001": (3, 4),
    "RSK-002": (4, 4),
    "RSK-003": (3, 5),
    "RSK-004": (3, 4),
    "RSK-005": (2, 5),
}
BASELINE_RESIDUAL = {
    "RSK-001": (2, 4),
    "RSK-002": (3, 4),
    "RSK-003": (2, 5),
    "RSK-004": (3, 3),
}
RETEST_RESIDUAL = {
    "RSK-001": (1, 3),
    "RSK-002": (2, 3),
    "RSK-003": (1, 4),
    "RSK-004": (1, 3),
    "RSK-005": (2, 3),
}


def lifecycle_records(
    source: dict[str, Any],
    run_id: str,
    remediated: bool,
    results: tuple[TestResult, ...],
) -> dict[str, tuple[Any, ...]]:
    observations = tuple(
        Observation(
            id=item["observation_id"],
            run_id=run_id,
            objective_id=OBS_OBJECTIVE[item["observation_id"]],
            condition=item["statement"],
            evidence_refs=tuple(item["evidence_refs"]),
            observed_at=dt(item["observed_at"]),
        )
        for item in source["observations"]
    )
    findings = tuple(
        Finding(
            id=item["finding_id"],
            run_id=run_id,
            objective_id=item["affected_objectives"][0],
            title=f"{item['finding_id']} — {item['affected_objectives'][0]}",
            criteria=item["criteria"],
            condition=item["condition"],
            cause=item["cause"],
            consequence=item["consequence"],
            affected_controls=tuple(item["affected_controls"]),
            affected_assets=tuple(item["affected_assets"]),
            severity=Severity(item["severity"]),
            severity_rationale=item["severity_rationale"],
            evidence_refs=tuple(item["evidence_refs"]),
            status=item["status"],
        )
        for item in source["findings"]
    )
    residuals = RETEST_RESIDUAL if remediated else BASELINE_RESIDUAL
    risks: list[Risk] = []
    risk_to_finding: dict[str, str] = {}
    for item in source["risks"]:
        finding_id = item["finding_refs"][0] if item["finding_refs"] else "FND-005"
        risk_to_finding[item["risk_id"]] = finding_id
        inherent_likelihood, inherent_impact = INHERENT[item["risk_id"]]
        residual_likelihood, residual_impact = residuals[item["risk_id"]]
        treatment = (
            RiskTreatment.ACCEPT
            if item["treatment"] == "ACCEPT_WITH_EXCEPTION"
            else RiskTreatment.MITIGATE
        )
        risks.append(
            Risk(
                id=item["risk_id"],
                finding_id=finding_id,
                statement=item["statement"],
                likelihood=inherent_likelihood,
                impact=inherent_impact,
                inherent_score=inherent_likelihood * inherent_impact,
                inherent_rating=item["inherent_rating"],
                residual_likelihood=residual_likelihood,
                residual_impact=residual_impact,
                residual_score=residual_likelihood * residual_impact,
                residual_rating=item["residual_rating"],
                confidence=item["confidence"],
                treatment=treatment,
                owner=item["owner"],
                rationale=f"Current treatment: {item['treatment']}; next review {item['review_date']}.",
            )
        )
    exceptions = tuple(
        ExceptionRecord(
            id=item["exception_id"],
            finding_id=risk_to_finding[item["subject_ref"]],
            approver=item["approver"],
            rationale=item["rationale"],
            compensating_controls=tuple(item["compensating_controls"]),
            approved_at=dt(item["approved_at"]),
            expires_at=dt(item["expires_at"]),
            review_cadence=item["review_cadence"],
        )
        for item in source["exceptions"]
    )
    remediation_status = {
        "PLANNED": "PLANNED",
        "IN_PROGRESS": "IN_PROGRESS",
        "READY_FOR_RETEST": "READY_FOR_RETEST",
        "COMPLETED": "VERIFIED",
    }
    remediations = tuple(
        Remediation(
            id=item["remediation_id"],
            finding_id=item["finding_ref"],
            owner=item["owner"],
            action=item["action"],
            target_date=dt(item["target_date"]),
            commit_or_pr=item.get("commit_ref")
            or item.get("pull_request_ref")
            or "SAMPLE-NOT-AVAILABLE",
            evidence_refs=tuple(item["evidence_refs"]),
            status=remediation_status[item["status"]],
        )
        for item in source["remediations"]
    )
    retest_to_finding = {item["retest_id"]: item.get("finding_ref") for item in source["retests"]}
    result_by_id = {item.id: item for item in results}
    review_by_retest = {
        item["subject_ref"]: item["decision_id"]
        for item in source["review_decisions"]
        if item["subject_ref"].startswith("RET-")
    }
    retests = tuple(
        Retest(
            id=item["retest_id"],
            finding_id=item["finding_ref"],
            before_run_id=item["before_run_id"],
            after_run_id=item["after_run_id"],
            objective_id=result_by_id[item["new_result_ref"]].objective_id,
            test_result_id=item["new_result_ref"],
            evidence_refs=tuple(item["new_evidence_refs"]),
            result=item["result"],
            decision=item["decision"],
            evidence_freshness=EvidenceFreshness.FRESH,
            review_state=(
                ReviewState.ACCEPTED
                if item["retest_id"] in review_by_retest
                else ReviewState.SUGGESTED
            ),
            review_decision_id=review_by_retest.get(item["retest_id"]),
            rationale=item["rationale"],
            tested_at=dt("2026-06-08T12:24:00Z"),
        )
        for item in source["retests"]
        if item.get("finding_ref") is not None
    )
    decisions: list[ReviewDecision] = []
    for item in source["review_decisions"]:
        subject = item["subject_ref"]
        if subject.startswith("AI-SUGGESTION"):
            subject_type = "AI_SUGGESTION"
            subject_id = subject
        elif subject.startswith("RUN-"):
            subject_type = "RUN"
            subject_id = run_id
        elif subject.startswith("EXC-"):
            subject_type = "EXCEPTION"
            subject_id = subject
        elif subject.startswith("RET-"):
            subject_type = "FINDING"
            subject_id = retest_to_finding.get(subject) or subject
        else:
            subject_type = "CONTROL"
            subject_id = subject
        decisions.append(
            ReviewDecision(
                id=item["decision_id"],
                reviewer=item["reviewer"],
                subject_type=subject_type,
                subject_id=subject_id,
                prior_state=item["prior_state"],
                decision=item["decision"],
                rationale=item["rationale"],
                timestamp=dt(item["timestamp"]),
                artifact_hash=digest(item["artifact_hash"]),
                expected_version=0,
                version=1,
            )
        )
    return {
        "observations": observations,
        "findings": findings,
        "risks": tuple(risks),
        "exceptions": exceptions,
        "remediations": remediations,
        "retests": retests,
        "decisions": tuple(decisions),
    }


def build_package(name: str) -> AssessmentPackage:
    path = RUN_ROOT / name
    run_source = load(path / "run.json")
    objectives = objective_records()
    evidence = bind_sample_evaluation(
        evidence_records(load(path / "evidence.json")),
        name=name,
        run_id=run_source["run_id"],
    )
    evaluated_at = dt(run_source["ended_at"])
    results = result_records(load(path / "results.json"), run_source["run_id"], evaluated_at)
    assessments = assessment_records(
        load(path / "control-assessments.json"), objectives, results, evidence, run_source["run_id"]
    )
    lifecycle = lifecycle_records(
        load(path / "lifecycle.json"),
        run_source["run_id"],
        name == "remediated",
        results,
    )
    trigger = "retest" if run_source["trigger"] == "RETEST" else "fixture"
    run = AssessmentRun(
        id=run_source["run_id"],
        trigger=trigger,
        scope=tuple(run_source["scope"]["selectors"]),
        observation_window_start=dt(run_source["observation_window"]["start"]),
        observation_window_end=dt(run_source["observation_window"]["end"]),
        git_commit=run_source["git_commit"],
        collector_version=run_source["collector_version"],
        evaluator_version=run_source["evaluator_version"],
        started_at=dt(run_source["started_at"]),
        ended_at=evaluated_at,
        status=terminal_run_status(list(results)),
        manifest_digest=None,
        estimated_cost_cad=run_source["cost"]["total_estimate"],
        prior_run_id=run_source.get("prior_run_id"),
    )
    return AssessmentPackage(
        run=run,
        system=SystemRecord.model_validate(load(SYSTEM_RECORD_PATH)),
        objectives=objectives,
        evidence=evidence,
        test_results=results,
        assessments=assessments,
        **lifecycle,
    )


def write_package_and_manifest(name: str, signer: LocalEs256Signer) -> None:
    root = RUN_ROOT / name
    run_source = load(root / "run.json")
    package = build_package(name)
    package_path = root / "package.json"
    package_path.write_bytes(canonical_json_bytes(package))
    artifact_paths = sorted(
        path for path in root.iterdir() if path.is_file() and path.name != "run-manifest.json"
    )
    run = package.run
    artifacts = tuple(
        ManifestArtifact(
            path=path.relative_to(root).as_posix(),
            media_type="application/json",
            sha256=sha256_file(path),
            size_bytes=path.stat().st_size,
            classification="PUBLIC",
        )
        for path in artifact_paths
    )
    generated_at = dt("2026-06-01T12:30:00Z" if name == "baseline" else "2026-06-08T12:30:00Z")
    unsigned = UnsignedManifest(
        run_id=run.id,
        generated_at=generated_at,
        git_commit=run.git_commit,
        collector_version=run.collector_version,
        evaluator_version=run.evaluator_version,
        artifacts=artifacts,
        cost_estimate_cad=run.estimated_cost_cad,
        cost_breakdown=CadCostBreakdown(
            currency="CAD",
            model_estimate_cad=run_source["cost"]["model_estimate"],
            compute_estimate_cad=run_source["cost"]["compute_estimate"],
            storage_estimate_cad=run_source["cost"]["storage_estimate"],
            telemetry_estimate_cad=run_source["cost"]["telemetry_estimate"],
            total_estimate_cad=run_source["cost"]["total_estimate"],
        ),
    )
    signed = sign_manifest(unsigned, signer)
    (root / "run-manifest.json").write_bytes(canonical_json_bytes(signed))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--key",
        type=Path,
        default=Path(tempfile.gettempdir()) / "aica-public-sample-signing.pem",
        help="Local CI/sample-only P-256 key. Never use this option for a deployed package.",
    )
    args = parser.parse_args()
    signer = LocalEs256Signer(args.key)
    for name in ("baseline", "remediated"):
        write_package_and_manifest(name, signer)
    print("assembled and locally signed baseline/remediated sample packages")


if __name__ == "__main__":
    main()
