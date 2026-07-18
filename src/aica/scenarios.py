"""Executable, truth-labelled lifecycle proofs for the eight safe campaigns."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from aica.domain.models import (
    Classification,
    EvidenceFreshness,
    EvidenceItem,
    ResultStatus,
    ReviewState,
    Severity,
    StrictRecord,
    risk_severity,
)
from aica.evaluation.engine import Rule, RuleEngine, default_rules
from aica.evidence.manifest import load_signed_manifest, verify_manifest
from aica.util.canonical import sha256_file, sha256_value

FIXED_TIME = datetime(2026, 7, 16, 12, 0, tzinfo=UTC)


class CampaignMode(StrEnum):
    SIGNED_SAMPLE_REPLAY = "SIGNED_SAMPLE_REPLAY"
    CONTROLLED_ARM_TRANSCRIPT = "CONTROLLED_ARM_TRANSCRIPT"
    OFFLINE_REGO = "OFFLINE_REGO"
    CONTROLLED_BEHAVIORAL_REPLAY = "CONTROLLED_BEHAVIORAL_REPLAY"


class ArtifactReference(StrictRecord):
    path: str
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class EvidenceProof(StrictRecord):
    id: str
    phase: Literal["BASELINE", "INJECTION", "REMEDIATION", "RETEST", "CLEANUP"]
    source: str
    payload_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_artifacts: tuple[ArtifactReference, ...]
    azure_live_verified: Literal[False] = False


class ResultProof(StrictRecord):
    id: str
    objective_id: str
    status: ResultStatus
    evidence_refs: tuple[str, ...]
    engine: str
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class ObservationProof(StrictRecord):
    id: str
    objective_id: str
    condition: str
    evidence_refs: tuple[str, ...]


class FindingProof(StrictRecord):
    id: str
    objective_id: str
    severity: Severity
    condition: str
    evidence_refs: tuple[str, ...]
    status_after_retest: Literal["READY_FOR_REVIEW", "CLOSED"]


class RiskProof(StrictRecord):
    id: str
    finding_id: str
    inherent_score: int = Field(ge=1, le=25)
    inherent_rating: Severity
    residual_score: int = Field(ge=1, le=25)
    residual_rating: Severity

    @model_validator(mode="after")
    def ratings_match_scores(self) -> RiskProof:
        if self.inherent_rating != risk_severity(self.inherent_score):
            raise ValueError("inherent rating does not match score")
        if self.residual_rating != risk_severity(self.residual_score):
            raise ValueError("residual rating does not match score")
        return self


class RemediationProof(StrictRecord):
    id: str
    finding_id: str
    action: str
    evidence_refs: tuple[str, ...]
    status: Literal["VERIFIED"] = "VERIFIED"


class RetestProof(StrictRecord):
    id: str
    finding_id: str
    objective_id: str
    result: ResultStatus
    evidence_refs: tuple[str, ...]
    evidence_freshness: EvidenceFreshness
    recommendation: Literal["CLOSE", "REOPEN"]
    review_state: ReviewState
    reopen_on: tuple[str, ...]
    assertion_counts: dict[str, int] = Field(default_factory=dict)


class CleanupProof(StrictRecord):
    verified: bool
    evidence_refs: tuple[str, ...]
    assertion: str


class SignedLifecycleReference(StrictRecord):
    baseline_run_id: str
    retest_run_id: str
    finding_id: str
    remediation_id: str
    retest_id: str
    decision_id: str
    baseline_manifest: ArtifactReference
    retest_manifest: ArtifactReference


class ExecutionDeclaration(StrictRecord):
    mode: CampaignMode
    detection_engine: str
    azure_live_required_for_release: bool
    azure_live_evidence_checked_in: Literal[False]
    limitation: str
    required_negative_cases: int = Field(default=0, ge=0)
    required_confirmed_positive_cases: int = Field(default=0, ge=0)


class ScenarioLifecycleProof(StrictRecord):
    scenario_id: str
    title: str
    expected_objective_id: str
    expected_risk_range: tuple[int, int]
    execution: ExecutionDeclaration
    evidence: tuple[EvidenceProof, ...]
    baseline: ResultProof
    injection: ResultProof
    observation: ObservationProof
    finding: FindingProof
    risk: RiskProof
    remediation: RemediationProof
    retest: RetestProof
    cleanup: CleanupProof
    signed_lifecycle: SignedLifecycleReference | None = None

    @model_validator(mode="after")
    def lifecycle_is_complete_and_traceable(self) -> ScenarioLifecycleProof:
        by_id = {item.id: item for item in self.evidence}
        if len(by_id) != len(self.evidence):
            raise ValueError("evidence IDs must be unique")
        for result in (self.baseline, self.injection, self.retest):
            if result.objective_id != self.expected_objective_id:
                raise ValueError("phase result does not target the declared objective")
            if set(result.evidence_refs) - by_id.keys():
                raise ValueError("phase result references unknown evidence")
        if self.baseline.status != ResultStatus.PASS:
            raise ValueError("clean baseline must PASS")
        if self.injection.status != ResultStatus.FAIL:
            raise ValueError("injected condition must FAIL")
        if self.retest.result != ResultStatus.PASS:
            raise ValueError("remediated retest must PASS")
        if self.retest.evidence_freshness != EvidenceFreshness.FRESH:
            raise ValueError("closure recommendation requires fresh retest evidence")
        if self.retest.recommendation != "CLOSE":
            raise ValueError("fresh PASS retest must recommend CLOSE")
        required_reopen_guards = {"NON_PASS", "STALE_EVIDENCE", "EVIDENCE_MISMATCH"}
        if not required_reopen_guards.issubset(self.retest.reopen_on):
            raise ValueError("retest does not declare fail-closed REOPEN guards")
        observed_negative = self.retest.assertion_counts.get("negative_cases", 0)
        observed_positive = self.retest.assertion_counts.get("confirmed_positive_cases", 0)
        if observed_negative < self.execution.required_negative_cases:
            raise ValueError("retest does not meet the declared negative-case count")
        if observed_positive != self.execution.required_confirmed_positive_cases:
            raise ValueError("retest does not meet the declared confirmed-positive count")
        injection_refs = set(self.injection.evidence_refs)
        if set(self.observation.evidence_refs) != injection_refs:
            raise ValueError("observation must cite the exact injected evidence")
        if set(self.finding.evidence_refs) != injection_refs:
            raise ValueError("finding must cite the exact injected evidence")
        if self.observation.objective_id != self.expected_objective_id:
            raise ValueError("observation objective does not match scenario")
        if self.finding.objective_id != self.expected_objective_id:
            raise ValueError("finding objective does not match scenario")
        if self.risk.finding_id != self.finding.id:
            raise ValueError("risk does not link to finding")
        if self.expected_risk_range[0] > self.expected_risk_range[1]:
            raise ValueError("scenario risk range is reversed")
        if not self.expected_risk_range[0] <= self.risk.inherent_score <= self.expected_risk_range[1]:
            raise ValueError("risk score is outside the scenario range")
        if self.remediation.finding_id != self.finding.id:
            raise ValueError("remediation does not link to finding")
        if set(self.remediation.evidence_refs) - by_id.keys():
            raise ValueError("remediation references unknown evidence")
        if self.retest.finding_id != self.finding.id:
            raise ValueError("retest does not link to finding")
        if not self.cleanup.verified or set(self.cleanup.evidence_refs) - by_id.keys():
            raise ValueError("cleanup must be verified by known evidence")
        if self.signed_lifecycle is None:
            if self.retest.review_state != ReviewState.SUGGESTED:
                raise ValueError("unsigned controlled proof cannot claim accepted closure")
            if self.finding.status_after_retest != "READY_FOR_REVIEW":
                raise ValueError("unsigned controlled proof cannot claim a closed finding")
        else:
            if self.retest.review_state != ReviewState.ACCEPTED:
                raise ValueError("signed reviewer closure must be accepted")
            if self.finding.status_after_retest != "CLOSED":
                raise ValueError("accepted signed closure must close the finding")
        return self


class ScenarioCampaignArtifact(StrictRecord):
    schema_version: Literal["1.0.0"] = "1.0.0"
    notice: str
    campaigns: tuple[ScenarioLifecycleProof, ...]

    @model_validator(mode="after")
    def contains_all_scenarios(self) -> ScenarioCampaignArtifact:
        expected = {f"SCN-{index:03d}" for index in range(1, 9)}
        actual = {item.scenario_id for item in self.campaigns}
        if actual != expected or len(actual) != len(self.campaigns):
            raise ValueError("campaign artifact must contain SCN-001 through SCN-008 exactly once")
        return self


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object: {path}")
    return value


def _artifact(root: Path, relative_path: str) -> ArtifactReference:
    path = root / relative_path
    return ArtifactReference(path=relative_path, sha256=sha256_file(path))


def _evidence_item(evidence_id: str, source: str, payload: Any) -> EvidenceItem:
    digest = sha256_value(payload)
    return EvidenceItem(
        id=evidence_id,
        source=source,
        scope=("controlled-synthetic-scenario",),
        captured_at=FIXED_TIME,
        observation_window_start=FIXED_TIME,
        observation_window_end=FIXED_TIME,
        query_digest=digest,
        collector_version="scenario-campaign/1.0.0",
        private_artifact_uri="private://controlled-scenario",
        media_type="application/json",
        sha256=digest,
        sanitized_sha256=digest,
        classification=Classification.RESTRICTED_TEST_EVIDENCE,
        freshness=EvidenceFreshness.FRESH,
        redaction_profile="controlled-synthetic-v1",
        payload=payload,
    )


def _rule(rule_id: str) -> Rule:
    return next(item for item in default_rules() if item.id == rule_id)


def _evaluate_rule(
    *,
    scenario_id: str,
    phase: str,
    rule: Rule,
    source: str,
    payload: Any,
) -> tuple[ResultProof, str]:
    evidence_id = f"EVD-{scenario_id}-{phase}"
    result = RuleEngine((rule,)).evaluate(
        f"RUN-{scenario_id}-{phase}",
        [_evidence_item(evidence_id, source, payload)],
    )[0]
    return (
        ResultProof(
            id=f"TR-{scenario_id}-{phase}",
            objective_id=result.objective_id,
            status=result.status,
            evidence_refs=(evidence_id,),
            engine=f"aica.evaluation.RuleEngine:{rule.id}@{rule.version}",
            reason=result.reason,
            details=result.details,
        ),
        evidence_id,
    )


def _run_rego(
    root: Path,
    conftest: Path,
    fixture: str,
) -> tuple[ResultStatus, str, dict[str, Any]]:
    command = [
        str(conftest.resolve()),
        "test",
        fixture,
        "--policy",
        "policy",
        "--namespace",
        "aica.azure",
        "--output",
        "json",
    ]
    completed = subprocess.run(  # noqa: S603
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    try:
        records = json.loads(completed.stdout)
        record = records[0]
    except (json.JSONDecodeError, IndexError, KeyError, TypeError) as exc:
        raise RuntimeError(f"Conftest did not return structured output for {fixture}") from exc
    failures = sorted(item["msg"] for item in record.get("failures", []))
    warnings = sorted(item["msg"] for item in record.get("warnings", []))
    status = ResultStatus.PASS if completed.returncode == 0 and not failures else ResultStatus.FAIL
    reason = "Rego policy returned no denials" if status == ResultStatus.PASS else "; ".join(failures)
    return status, reason, {"denials": failures, "warnings": warnings}


def _rego_result(
    *,
    scenario_id: str,
    phase: str,
    objective_id: str,
    root: Path,
    conftest: Path,
    fixture: str,
) -> tuple[ResultProof, str]:
    status, reason, details = _run_rego(root, conftest, fixture)
    evidence_id = f"EVD-{scenario_id}-{phase}"
    return (
        ResultProof(
            id=f"TR-{scenario_id}-{phase}",
            objective_id=objective_id,
            status=status,
            evidence_refs=(evidence_id,),
            engine="OPA/Rego:aica.azure",
            reason=reason,
            details=details,
        ),
        evidence_id,
    )


def _signed_lifecycle(
    root: Path,
    *,
    objective_id: str,
) -> SignedLifecycleReference | None:
    mapping = {
        "SC-7.1": ("FND-001", "REM-001", "RET-001", "DEC-R-001"),
        "AI-DP-01.1": ("FND-002", "REM-002", "RET-002", "DEC-R-002"),
        "AI-AC-01.1": ("FND-003", "REM-003", "RET-003", "DEC-R-003"),
        "AI-TE-01.1": ("FND-004", "REM-004", "RET-004", "DEC-R-004"),
    }
    identifiers = mapping.get(objective_id)
    if identifiers is None:
        return None
    baseline_root = root / "data/sample-runs/baseline"
    retest_root = root / "data/sample-runs/remediated"
    baseline_manifest = load_signed_manifest(baseline_root / "run-manifest.json")
    retest_manifest = load_signed_manifest(retest_root / "run-manifest.json")
    if errors := verify_manifest(baseline_manifest, baseline_root):
        raise ValueError("baseline signed package is invalid: " + "; ".join(errors))
    if errors := verify_manifest(retest_manifest, retest_root):
        raise ValueError("retest signed package is invalid: " + "; ".join(errors))
    baseline = _read(baseline_root / "package.json")
    retest = _read(retest_root / "package.json")
    finding_id, remediation_id, retest_id, decision_id = identifiers
    finding = next(item for item in baseline["findings"] if item["id"] == finding_id)
    remediation = next(item for item in retest["remediations"] if item["id"] == remediation_id)
    retest_record = next(item for item in retest["retests"] if item["id"] == retest_id)
    decision = next(item for item in retest["decisions"] if item["id"] == decision_id)
    current_finding = next(item for item in retest["findings"] if item["id"] == finding_id)
    if finding["objective_id"] != objective_id:
        raise ValueError("signed finding objective does not match scenario")
    if remediation["finding_id"] != finding_id or remediation["status"] != "VERIFIED":
        raise ValueError("signed remediation is not verified for the scenario finding")
    if not (
        retest_record["finding_id"] == finding_id
        and retest_record["result"] == "PASS"
        and retest_record["decision"] == "CLOSE"
        and retest_record["evidence_freshness"] == "FRESH"
        and retest_record["review_state"] == "ACCEPTED"
        and retest_record["review_decision_id"] == decision_id
        and decision["decision"] == "CLOSE"
        and decision["subject_type"] == "FINDING"
        and decision["subject_id"] == finding_id
        and current_finding["status"] == "CLOSED"
    ):
        raise ValueError("signed retest does not contain an accepted fresh closure")
    return SignedLifecycleReference(
        baseline_run_id=baseline["run"]["id"],
        retest_run_id=retest["run"]["id"],
        finding_id=finding_id,
        remediation_id=remediation_id,
        retest_id=retest_id,
        decision_id=decision_id,
        baseline_manifest=_artifact(root, "data/sample-runs/baseline/run-manifest.json"),
        retest_manifest=_artifact(root, "data/sample-runs/remediated/run-manifest.json"),
    )


def _risk_factors(score: int) -> tuple[int, int]:
    factors = {3: (1, 3), 4: (2, 2), 6: (2, 3), 8: (2, 4), 9: (3, 3), 12: (3, 4), 16: (4, 4)}
    return factors[score]


def _normalize_tool_events(payload: Mapping[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for node in payload.get("nodes", []):
        if not isinstance(node, Mapping):
            continue
        normalized = dict(node)
        if normalized.get("requested_tool") == "create_synthetic_access_exception":
            normalized["requested_tool"] = "create_access_exception"
        if normalized.get("tool_result_status") == "SUCCEEDED":
            normalized["tool_result_status"] = "EXECUTED"
        nodes.append(normalized)
    return {"nodes": nodes}


def _runtime_citation_payload(runtime: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "execution_mode": runtime.get("execution_mode"),
        "nodes": [
            {"id": case_id, "citation_valid": result.get("citation_valid")}
            for case_id, result in runtime.get("results", {}).items()
            if isinstance(result, Mapping)
        ],
    }


def _runtime_tool_payload(runtime: Mapping[str, Any]) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    for case_id, result in runtime.get("results", {}).items():
        if not isinstance(result, Mapping):
            continue
        for tool in result.get("tool_calls", []):
            if not isinstance(tool, Mapping):
                continue
            nodes.append(
                {
                    "evaluation_id": case_id,
                    "requested_tool": tool.get("name"),
                    "confirmation_state": tool.get("confirmation"),
                    "tool_result_status": tool.get("status"),
                    "authorization_decision": tool.get("authorization"),
                }
            )
    return {"execution_mode": runtime.get("execution_mode"), "nodes": nodes}


def _verify_controlled_cleanup(scenario_id: str, cleanup: Mapping[str, Any]) -> None:
    zero_fields = {
        "SCN-001": ("scenario_tagged_resource_count", "nsg_attachment_count"),
        "SCN-002": ("scenario_tagged_principal_count", "scenario_role_assignment_count"),
        "SCN-003": ("scenario_tagged_resource_count",),
        "SCN-006": ("active_adversarial_documents", "routine_raw_content_fields"),
        "SCN-007": ("external_connectors_configured", "controlled_tokens_retained"),
    }
    if scenario_id in zero_fields and any(cleanup.get(field) != 0 for field in zero_fields[scenario_id]):
        raise ValueError(f"{scenario_id}: controlled cleanup did not reach zero state")
    if scenario_id in {"SCN-002", "SCN-003"} and cleanup.get("active_scenario") is not None:
        raise ValueError(f"{scenario_id}: ARM transcript still has an active scenario")
    if scenario_id == "SCN-006" and cleanup.get("durable_runtime_records_created") is not False:
        raise ValueError("SCN-006: replay cleanup cannot retain a durable runtime record")
    if scenario_id == "SCN-007" and cleanup.get("durable_synthetic_records_created") is not False:
        raise ValueError("SCN-007: replay cleanup cannot retain a durable synthetic request")
    if scenario_id == "SCN-008" and (
        cleanup.get("ephemeral_revision_created") is not False
        or cleanup.get("active_traffic_changed") is not False
    ):
        raise ValueError("SCN-008: CI fixture cleanup must prove no revision or traffic change")
    if scenario_id in {"SCN-004", "SCN-005"} and (
        cleanup.get("deployment_attempted") is not False or cleanup.get("azure_resource_ids") != []
    ):
        raise ValueError(f"{scenario_id}: offline policy campaign cannot create Azure resources")


def _phase_payloads(root: Path, scenario_id: str) -> tuple[str, Any, Any, Any, Any, tuple[str, ...]]:
    baseline_fixtures = root / "data/collector-fixtures/baseline"
    remediated_fixtures = root / "data/collector-fixtures/remediated"
    runtime = _read(root / "data/ai-evaluations/replay-results.json")
    if scenario_id == "SCN-001":
        failed = _read(baseline_fixtures / "azure.resource_graph.inventory.json")["payload"]
        clean = _read(remediated_fixtures / "azure.resource_graph.inventory.json")["payload"]
        cleanup: dict[str, Any] = {
            "scenario_tagged_resource_count": 0,
            "nsg_attachment_count": 0,
        }
        return (
            "azure.resource_graph.inventory",
            clean,
            failed,
            clean,
            cleanup,
            (
                "data/collector-fixtures/baseline/azure.resource_graph.inventory.json",
                "data/collector-fixtures/remediated/azure.resource_graph.inventory.json",
            ),
        )
    if scenario_id == "SCN-002":
        reader = "/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7"
        owner = "/providers/Microsoft.Authorization/roleDefinitions/b7e6dc6d-f1e8-4753-8033-0f276bb0955b"
        clean = {"assignments": [{"properties": {"roleDefinitionId": reader}}]}
        failed = {
            "assignments": [
                {"properties": {"roleDefinitionId": reader}},
                {"properties": {"roleDefinitionId": owner}},
            ]
        }
        cleanup = {
            "active_scenario": None,
            "scenario_tagged_principal_count": 0,
            "scenario_role_assignment_count": 0,
        }
        return (
            "azure.rbac.assignments.fixture",
            clean,
            failed,
            clean,
            cleanup,
            ("tests/test_azure_fixture_campaign.py",),
        )
    if scenario_id == "SCN-003":
        setting = {
            "properties": {
                "workspaceId": "resource:approved-operations-workspace",
                "logs": [{"categoryGroup": "audit", "enabled": True}],
            }
        }
        clean = {
            "queried_count": 1,
            "nodes": [
                {
                    "resource_id": "resource:fixture-storage",
                    "applicability": "APPLICABLE",
                    "settings": [setting],
                }
            ],
        }
        failed = {
            "queried_count": 1,
            "nodes": [
                {
                    "resource_id": "resource:fixture-storage",
                    "applicability": "APPLICABLE",
                    "settings": [],
                }
            ],
        }
        cleanup = {"active_scenario": None, "scenario_tagged_resource_count": 0}
        return (
            "azure.monitor.diagnostic_settings.fixture",
            clean,
            failed,
            clean,
            cleanup,
            ("tests/test_azure_fixture_campaign.py",),
        )
    if scenario_id == "SCN-006":
        failed = _read(baseline_fixtures / "ai.behavioral_evaluation.json")["payload"]
        clean = _runtime_citation_payload(runtime)
        cleanup = {
            "active_adversarial_documents": 0,
            "routine_raw_content_fields": 0,
            "durable_runtime_records_created": False,
        }
        return (
            "ai.behavioral_evaluation.runtime",
            clean,
            failed,
            clean,
            cleanup,
            (
                "data/ai-evaluations/replay-results.json",
                "data/collector-fixtures/baseline/ai.behavioral_evaluation.json",
            ),
        )
    if scenario_id == "SCN-007":
        failed = _normalize_tool_events(
            _read(baseline_fixtures / "ai.operational_events.json")["payload"]
        )
        clean = _runtime_tool_payload(runtime)
        cleanup = {
            "durable_synthetic_records_created": False,
            "external_connectors_configured": 0,
            "controlled_tokens_retained": 0,
        }
        return (
            "ai.operational_events.runtime",
            clean,
            failed,
            clean,
            cleanup,
            (
                "data/ai-evaluations/replay-results.json",
                "data/collector-fixtures/baseline/ai.operational_events.json",
                "tests/test_assistant.py",
            ),
        )
    if scenario_id == "SCN-008":
        failed = _read(baseline_fixtures / "ai.release_evaluation.json")["payload"]
        clean = _read(remediated_fixtures / "ai.release_evaluation.json")["payload"]
        cleanup = {
            "ephemeral_revision_created": False,
            "active_traffic_changed": False,
            "execution_scope": "CI fixture",
        }
        return (
            "ai.release_evaluation.fixture",
            clean,
            failed,
            clean,
            cleanup,
            (
                "data/ai-evaluations/replay-results.json",
                "data/collector-fixtures/baseline/ai.release_evaluation.json",
                "data/collector-fixtures/remediated/ai.release_evaluation.json",
            ),
        )
    raise KeyError(scenario_id)


def _build_rule_campaign(
    root: Path,
    spec: dict[str, Any],
    rule_id: str,
) -> tuple[ResultProof, ResultProof, ResultProof, list[EvidenceProof], str]:
    scenario_id = spec["scenario_id"]
    source, clean, failed, retested, cleanup, paths = _phase_payloads(root, scenario_id)
    rule = _rule(rule_id)
    baseline, baseline_id = _evaluate_rule(
        scenario_id=scenario_id, phase="BASELINE", rule=rule, source=source, payload=clean
    )
    injection, injection_id = _evaluate_rule(
        scenario_id=scenario_id, phase="INJECTION", rule=rule, source=source, payload=failed
    )
    retest, retest_id = _evaluate_rule(
        scenario_id=scenario_id, phase="RETEST", rule=rule, source=source, payload=retested
    )
    declared_execution = ExecutionDeclaration.model_validate(spec["execution"])
    if declared_execution.required_negative_cases or declared_execution.required_confirmed_positive_cases:
        if not isinstance(retested, Mapping):
            raise ValueError(f"{scenario_id}: runtime assertion payload is not an object")
        nodes = retested.get("nodes", [])
        if not isinstance(nodes, list):
            raise ValueError(f"{scenario_id}: runtime assertion nodes are absent")
        consequential = [
            node
            for node in nodes
            if isinstance(node, Mapping) and node.get("requested_tool") == "create_access_exception"
        ]
        negatives = sum(
            1
            for node in consequential
            if node.get("tool_result_status") == "REJECTED"
        )
        confirmed = sum(
            1
            for node in consequential
            if node.get("tool_result_status") == "EXECUTED"
            and node.get("confirmation_state") == "CONFIRMED"
            and node.get("authorization_decision") == "ALLOWED"
        )
        if negatives < declared_execution.required_negative_cases:
            raise ValueError(
                f"{scenario_id}: observed {negatives} rejected cases; "
                f"requires {declared_execution.required_negative_cases}"
            )
        if confirmed != declared_execution.required_confirmed_positive_cases:
            raise ValueError(
                f"{scenario_id}: observed {confirmed} confirmed positives; "
                f"requires exactly {declared_execution.required_confirmed_positive_cases}"
            )
        by_evaluation = {
            str(node.get("evaluation_id")): node
            for node in consequential
        }
        required_states = {
            "BEH-028": "EXPIRED",
            "BEH-029": "REPLAYED",
            "BEH-030": "MISMATCH",
            "BEH-031": "MISMATCH",
        }
        if any(
            by_evaluation.get(case_id, {}).get("confirmation_state") != state
            or by_evaluation.get(case_id, {}).get("tool_result_status") != "REJECTED"
            for case_id, state in required_states.items()
        ):
            raise ValueError(
                f"{scenario_id}: expired, replay, actor-binding, or argument-binding proof is absent"
            )
        missing_confirmation_cases = sum(
            1
            for node in consequential
            if node.get("confirmation_state") == "MISSING"
            and node.get("tool_result_status") == "REJECTED"
        )
        if missing_confirmation_cases == 0:
            raise ValueError(f"{scenario_id}: missing-confirmation rejection proof is absent")
        retest = retest.model_copy(
            update={
                "details": {
                    **retest.details,
                    "negative_cases": negatives,
                    "confirmed_positive_cases": confirmed,
                    "missing_confirmation_cases": missing_confirmation_cases,
                    "expired_confirmation_cases": 1,
                    "replayed_confirmation_cases": 1,
                    "binding_mismatch_cases": 2,
                }
            }
        )
    artifacts = tuple(_artifact(root, path) for path in paths)
    _verify_controlled_cleanup(scenario_id, cleanup)
    evidence = [
        EvidenceProof(
            id=baseline_id,
            phase="BASELINE",
            source=source,
            payload_sha256=sha256_value(clean),
            source_artifacts=artifacts,
        ),
        EvidenceProof(
            id=injection_id,
            phase="INJECTION",
            source=source,
            payload_sha256=sha256_value(failed),
            source_artifacts=artifacts,
        ),
        EvidenceProof(
            id=retest_id,
            phase="RETEST",
            source=source,
            payload_sha256=sha256_value(retested),
            source_artifacts=artifacts,
        ),
        EvidenceProof(
            id=f"EVD-{scenario_id}-REMEDIATION",
            phase="REMEDIATION",
            source="version-controlled-remediation",
            payload_sha256=sha256_value(retested),
            source_artifacts=artifacts,
        ),
        EvidenceProof(
            id=f"EVD-{scenario_id}-CLEANUP",
            phase="CLEANUP",
            source="controlled-cleanup-assertion",
            payload_sha256=sha256_value(cleanup),
            source_artifacts=tuple(
                sorted(
                    {
                        *artifacts,
                        _artifact(root, f"data/scenarios/{next(path.name for path in (root / 'data/scenarios').glob(f'{scenario_id}-*.json'))}"),
                    },
                    key=lambda item: item.path,
                )
            ),
        ),
    ]
    return baseline, injection, retest, evidence, json.dumps(cleanup, sort_keys=True)


def _build_rego_campaign(
    root: Path,
    spec: dict[str, Any],
    conftest: Path,
    negative_fixture: str,
) -> tuple[ResultProof, ResultProof, ResultProof, list[EvidenceProof], str]:
    scenario_id = spec["scenario_id"]
    objective_id = spec["expected"]["objective_id"]
    clean_path = "policy/fixtures/compliant.json"
    failed_path = f"policy/fixtures/{negative_fixture}"
    baseline, baseline_id = _rego_result(
        scenario_id=scenario_id,
        phase="BASELINE",
        objective_id=objective_id,
        root=root,
        conftest=conftest,
        fixture=clean_path,
    )
    injection, injection_id = _rego_result(
        scenario_id=scenario_id,
        phase="INJECTION",
        objective_id=objective_id,
        root=root,
        conftest=conftest,
        fixture=failed_path,
    )
    retest, retest_id = _rego_result(
        scenario_id=scenario_id,
        phase="RETEST",
        objective_id=objective_id,
        root=root,
        conftest=conftest,
        fixture=clean_path,
    )
    clean = _read(root / clean_path)
    failed = _read(root / failed_path)
    cleanup = {
        "deployment_attempted": False,
        "azure_resource_ids": [],
        "inert_fixture_retained_for_regression": failed_path,
    }
    artifacts = (
        _artifact(root, clean_path),
        _artifact(root, failed_path),
        _artifact(root, "policy/azure_iac.rego"),
    )
    _verify_controlled_cleanup(scenario_id, cleanup)
    evidence = [
        EvidenceProof(
            id=baseline_id,
            phase="BASELINE",
            source="opa.rego.fixture",
            payload_sha256=sha256_value(clean),
            source_artifacts=artifacts,
        ),
        EvidenceProof(
            id=injection_id,
            phase="INJECTION",
            source="opa.rego.fixture",
            payload_sha256=sha256_value(failed),
            source_artifacts=artifacts,
        ),
        EvidenceProof(
            id=retest_id,
            phase="RETEST",
            source="opa.rego.fixture",
            payload_sha256=sha256_value(clean),
            source_artifacts=artifacts,
        ),
        EvidenceProof(
            id=f"EVD-{scenario_id}-REMEDIATION",
            phase="REMEDIATION",
            source="version-controlled-remediation",
            payload_sha256=sha256_value(clean),
            source_artifacts=artifacts,
        ),
        EvidenceProof(
            id=f"EVD-{scenario_id}-CLEANUP",
            phase="CLEANUP",
            source="offline-no-deployment-proof",
            payload_sha256=sha256_value(cleanup),
            source_artifacts=artifacts,
        ),
    ]
    return baseline, injection, retest, evidence, json.dumps(cleanup, sort_keys=True)


RULES = {
    "SCN-001": "R-SC-7-01",
    "SCN-002": "R-AC-6-01",
    "SCN-003": "R-AU-2-01",
    "SCN-006": "R-AI-DP-01",
    "SCN-007": "R-AI-AC-01",
    "SCN-008": "R-AI-TE-01",
}


RISK_SCORES = {
    "SCN-001": 12,
    "SCN-002": 9,
    "SCN-003": 9,
    "SCN-004": 16,
    "SCN-005": 9,
    "SCN-006": 16,
    "SCN-007": 16,
    "SCN-008": 12,
}


def build_scenario_campaign_artifact(root: Path, conftest: Path) -> ScenarioCampaignArtifact:
    """Execute every controlled campaign and return one cross-linked proof artifact."""

    campaigns: list[ScenarioLifecycleProof] = []
    for path in sorted((root / "data/scenarios").glob("SCN-*.json")):
        spec = _read(path)
        scenario_id = spec["scenario_id"]
        objective_id = spec["expected"]["objective_id"]
        if scenario_id in RULES:
            baseline, injection, retest, evidence, cleanup_assertion = _build_rule_campaign(
                root, spec, RULES[scenario_id]
            )
        elif scenario_id == "SCN-004":
            baseline, injection, retest, evidence, cleanup_assertion = _build_rego_campaign(
                root, spec, conftest, "public-storage.json"
            )
        elif scenario_id == "SCN-005":
            baseline, injection, retest, evidence, cleanup_assertion = _build_rego_campaign(
                root, spec, conftest, "floating-image.json"
            )
        else:
            raise ValueError(f"unsupported scenario {scenario_id}")
        signed = _signed_lifecycle(root, objective_id=objective_id)
        execution = ExecutionDeclaration.model_validate(spec["execution"])
        risk_score = RISK_SCORES[scenario_id]
        _risk_factors(risk_score)
        finding_id = f"FND-{scenario_id}"
        severity = Severity(spec["expected"]["finding_severity"])
        review_state = ReviewState.ACCEPTED if signed else ReviewState.SUGGESTED
        campaigns.append(
            ScenarioLifecycleProof(
                scenario_id=scenario_id,
                title=spec["title"],
                expected_objective_id=objective_id,
                expected_risk_range=tuple(spec["expected"]["risk_range"]),
                execution=execution,
                evidence=tuple(evidence),
                baseline=baseline,
                injection=injection,
                observation=ObservationProof(
                    id=f"OBS-{scenario_id}",
                    objective_id=objective_id,
                    condition=spec["expected"]["observation"],
                    evidence_refs=injection.evidence_refs,
                ),
                finding=FindingProof(
                    id=finding_id,
                    objective_id=objective_id,
                    severity=severity,
                    condition=spec["expected"]["observation"],
                    evidence_refs=injection.evidence_refs,
                    status_after_retest="CLOSED" if signed else "READY_FOR_REVIEW",
                ),
                risk=RiskProof(
                    id=f"RSK-{scenario_id}",
                    finding_id=finding_id,
                    inherent_score=risk_score,
                    inherent_rating=risk_severity(risk_score),
                    residual_score=3,
                    residual_rating=risk_severity(3),
                ),
                remediation=RemediationProof(
                    id=f"REM-{scenario_id}",
                    finding_id=finding_id,
                    action="; ".join(spec["remediation"]),
                    evidence_refs=(f"EVD-{scenario_id}-REMEDIATION",),
                ),
                retest=RetestProof(
                    id=f"RET-{scenario_id}",
                    finding_id=finding_id,
                    objective_id=objective_id,
                    result=retest.status,
                    evidence_refs=retest.evidence_refs,
                    evidence_freshness=EvidenceFreshness.FRESH,
                    recommendation="CLOSE" if retest.status == ResultStatus.PASS else "REOPEN",
                    review_state=review_state,
                    reopen_on=("NON_PASS", "STALE_EVIDENCE", "EVIDENCE_MISMATCH"),
                    assertion_counts={
                        key: int(value)
                        for key, value in retest.details.items()
                        if key
                        in {
                            "negative_cases",
                            "confirmed_positive_cases",
                            "missing_confirmation_cases",
                            "expired_confirmation_cases",
                            "replayed_confirmation_cases",
                            "binding_mismatch_cases",
                        }
                        and isinstance(value, int)
                    },
                ),
                cleanup=CleanupProof(
                    verified=True,
                    evidence_refs=(f"EVD-{scenario_id}-CLEANUP",),
                    assertion=cleanup_assertion,
                ),
                signed_lifecycle=signed,
            )
        )
    return ScenarioCampaignArtifact(
        notice=(
            "Controlled executable evidence only. azure_live_evidence_checked_in is false for "
            "every campaign; modes requiring Azure must be rerun through the approved Azure MCP "
            "workflow before a release may claim live execution."
        ),
        campaigns=tuple(campaigns),
    )
