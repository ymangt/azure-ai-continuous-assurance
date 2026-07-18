from __future__ import annotations

import json
from pathlib import Path

from aica.domain.models import EvidenceFreshness, ResultStatus
from aica.domain.models import TestResult as DomainTestResult
from aica.evaluation.assessment import build_assessments
from aica.evaluation.engine import RuleEngine, default_rules
from conftest import evidence, objective


def _engine(rule_id: str) -> RuleEngine:
    rule = next(item for item in default_rules() if item.id == rule_id)
    return RuleEngine((rule,))


def test_missing_evidence_is_not_run() -> None:
    result = _engine("R-SC-7-01").evaluate("run-1", [])[0]
    assert result.status == ResultStatus.NOT_RUN
    assert result.reason_code == "MISSING_EVIDENCE"


def test_unauthorized_collection_is_error(now) -> None:
    item = evidence(
        now,
        authorized=False,
        collection_error="HTTP 403",
        payload={"value": []},
    )
    result = _engine("R-SC-7-01").evaluate("run-1", [item])[0]
    assert result.status == ResultStatus.ERROR
    assert result.reason_code == "COLLECTION_UNAUTHORIZED"


def test_stale_evidence_never_passes(now) -> None:
    item = evidence(now, freshness=EvidenceFreshness.STALE, payload={"value": []})
    result = _engine("R-SC-7-01").evaluate("run-1", [item])[0]
    assert result.status == ResultStatus.NOT_RUN
    assert result.reason_code == "STALE_EVIDENCE"


def test_public_rdp_is_detected_and_remediation_passes(now) -> None:
    baseline = evidence(
        now,
        payload={
            "securityRules": [
                {
                    "name": "Allow-RDP-Internet",
                    "direction": "Inbound",
                    "access": "Allow",
                    "destinationPortRange": "3389",
                    "sourceAddressPrefix": "*",
                }
            ]
        },
    )
    failed = _engine("R-SC-7-01").evaluate("run-1", [baseline])[0]
    assert failed.status == ResultStatus.FAIL
    assert failed.details["offending_rules"] == ["Allow-RDP-Internet"]

    remediated = evidence(
        now,
        payload={
            "securityRules": [
                {
                    "name": "Deny-RDP-Internet",
                    "direction": "Inbound",
                    "access": "Deny",
                    "destinationPortRange": "3389",
                    "sourceAddressPrefix": "*",
                }
            ]
        },
    )
    passed = _engine("R-SC-7-01").evaluate("run-2", [remediated])[0]
    assert passed.status == ResultStatus.PASS
    assert passed.evidence_refs == (remediated.id,)


def test_tool_confirmation_bypass_fails(now) -> None:
    item = evidence(
        now,
        source="ai.operational_events",
        payload={
            "events": [
                {
                    "evaluation_id": "eval-1",
                    "requested_tool": "create_access_exception",
                    "confirmation_state": "MISSING",
                    "tool_result_status": "EXECUTED",
                }
            ]
        },
    )
    result = _engine("R-AI-AC-01").evaluate("run-1", [item])[0]
    assert result.status == ResultStatus.FAIL
    assert result.details["bypasses"] == ["eval-1"]


def test_disabled_recovery_and_security_settings_never_pass(now) -> None:
    recovery = evidence(
        now,
        payload={
            "isVersioningEnabled": True,
            "deleteRetentionPolicy": {"enabled": False, "days": 30},
        },
    )
    assert _engine("R-CP-9-01").evaluate("run-1", [recovery])[0].status == ResultStatus.FAIL

    security = evidence(
        now,
        source="github.code_security",
        payload={"advanced_security": {"status": "disabled"}, "unresolved_critical_alerts": 0},
    )
    assert _engine("R-RA-5-01").evaluate("run-1", [security])[0].status == ResultStatus.FAIL


def test_ci_artifacts_must_match_the_assessed_commit_and_workflow_run(now) -> None:
    assessed = "a" * 40
    unrelated = "b" * 40
    evidence_items = [
        evidence(
            now,
            source="github.ci.runs",
            payload={
                "assessed_commit": assessed,
                "workflow_runs": [
                    {
                        "run_id": 123,
                        "head_sha": unrelated,
                        "conclusion": "success",
                    }
                ],
            },
        ),
        evidence(
            now,
            source="github.ci.artifacts",
            payload={
                "assessed_commit": assessed,
                "workflow_run_id": 123,
                "artifacts": [
                    {
                        "workflow_run_id": 123,
                        "head_sha": unrelated,
                        "digest": "sha256:" + "c" * 64,
                        "expired": False,
                    }
                ],
            },
        ),
    ]

    result = _engine("R-SA-11-01").evaluate("run-1", evidence_items)[0]

    assert result.status == ResultStatus.FAIL


def test_advanced_security_requires_independently_collected_zero_critical_count(now) -> None:
    configuration = evidence(
        now,
        source="github.code_security",
        payload={"advanced_security": {"status": "enabled"}},
    )
    zero_alerts = evidence(
        now,
        evidence_id="ev-critical",
        source="github.code_security.critical_alerts",
        payload={"unresolved_critical_alerts": 0, "pages_completed": 1},
    )
    one_alert = evidence(
        now,
        evidence_id="ev-critical-one",
        source="github.code_security.critical_alerts",
        payload={"unresolved_critical_alerts": 1, "pages_completed": 1},
    )
    malformed_boolean = evidence(
        now,
        evidence_id="ev-critical-malformed",
        source="github.code_security.critical_alerts",
        payload={"unresolved_critical_alerts": False, "pages_completed": 1},
    )

    engine = _engine("R-RA-5-01")
    assert engine.evaluate("run-1", [configuration, zero_alerts])[0].status == ResultStatus.PASS
    assert engine.evaluate("run-1", [configuration, one_alert])[0].status == ResultStatus.FAIL
    assert (
        engine.evaluate("run-1", [configuration, malformed_boolean])[0].status
        == ResultStatus.FAIL
    )


def test_log_metadata_without_an_api_result_never_passes(now) -> None:
    assurance = evidence(
        now,
        source="sentinel.assurance_health",
        payload={"RunId_g": "run-1", "Status_s": "COMPLETE"},
    )
    assert _engine("R-AU-12-01").evaluate("run-1", [assurance])[0].status == ResultStatus.FAIL
    assert _engine("R-CA-7-01").evaluate("run-1", [assurance])[0].status == ResultStatus.FAIL

    risky = evidence(
        now,
        source="sentinel.risky_changes",
        payload={"tables": [{"columns": [{"name": "OperationNameValue"}]}]},
    )
    assert _engine("R-SI-4-01").evaluate("run-1", [risky])[0].status == ResultStatus.FAIL


def test_completed_and_review_required_runs_satisfy_recent_run_rule(now) -> None:
    for status in ("COMPLETED", "REVIEW_REQUIRED"):
        item = evidence(
            now,
            source="sentinel.assurance_health",
            payload={"records": [{"RunId": "run-1", "Status": status}]},
        )
        assert _engine("R-CA-7-01").evaluate("run-1", [item])[0].status == ResultStatus.PASS


def test_unavailable_automated_evidence_creates_non_conclusion_finding(now) -> None:
    result = DomainTestResult(
        id="test-error",
        run_id="run-1",
        objective_id="SC-7.1",
        status=ResultStatus.ERROR,
        reason_code="COLLECTION_UNAUTHORIZED",
        reason="The collector received HTTP 403.",
        test_version="1.0.0",
        evaluated_at=now,
    )
    _assessments, observations, findings, risks = build_assessments(
        "run-1", (objective(),), [result]
    )
    assert len(observations) == len(findings) == len(risks) == 1
    assert "could not be concluded" in findings[0].title
    assert "unavailable" in findings[0].cause
    assert "could remain undetected" in findings[0].consequence


def test_manual_review_not_run_does_not_create_a_finding(now) -> None:
    result = DomainTestResult(
        id="test-manual",
        run_id="run-1",
        objective_id="SC-7.1",
        status=ResultStatus.NOT_RUN,
        reason_code="MANUAL_REVIEW_REQUIRED",
        reason="Reviewer evidence is required.",
        test_version="1.0.0",
        evaluated_at=now,
    )
    _assessments, observations, findings, risks = build_assessments(
        "run-1", (objective(),), [result]
    )
    assert observations == []
    assert findings == []
    assert risks == []


def test_user_access_administrator_role_id_is_forbidden(now) -> None:
    rbac = evidence(
        now,
        source="azure.rbac.assignments",
        payload={
            "roleDefinitionId": (
                "/providers/Microsoft.Authorization/roleDefinitions/"
                "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9"
            )
        },
    )
    assert _engine("R-AC-6-01").evaluate("run-1", [rbac])[0].status == ResultStatus.FAIL


def test_every_automated_profile_objective_has_exactly_one_rule() -> None:
    profile = json.loads(
        Path("assurance/controls/control-profile.json").read_text(encoding="utf-8")
    )
    automated = {item["id"] for item in profile["objectives"] if item["method"] == "AUTOMATED"}
    rule_objectives = [rule.objective_id for rule in default_rules()]
    assert automated == set(rule_objectives)
    assert len(rule_objectives) == len(set(rule_objectives))


def test_release_gate_rejects_replay_or_configuration_mismatch(now) -> None:
    item = evidence(
        now,
        source="ai.release_evaluation",
        payload={
            "evaluation_gate_status": "PASS",
            "evaluation_artifact_sha256": "a" * 64,
            "evaluated_configuration_sha256": "b" * 64,
            "deployed_configuration_sha256": "c" * 64,
            "evaluation_mode": "REPLAY",
        },
    )
    assert _engine("R-AI-TE-01").evaluate("run-1", [item])[0].status == ResultStatus.FAIL
