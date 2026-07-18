from __future__ import annotations

import json
from pathlib import Path

import pytest

from aica.api_store import CompositeRunStore
from aica.config import Settings
from aica.domain.models import ResultStatus, RunStatus
from aica.domain.models import TestResult as DomainTestResult
from aica.evaluation.engine import default_rules
from aica.evidence.manifest import load_signed_manifest, verify_manifest
from aica.pipeline import (
    AssessmentPipeline,
    load_objectives,
    load_system_record,
    release_gate_failed,
    terminal_run_status,
)
from aica.profiles import AssessmentProfile, load_profile


def _write_fixture(directory: Path, name: str, source: str, payload: object) -> None:
    directory.joinpath(f"{name}.json").write_text(
        json.dumps(
            {
                "source": source,
                "query": {"fixture": name},
                "classification": "INTERNAL",
                "payload": payload,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_replay_pipeline_produces_verified_private_and_public_packages(tmp_path) -> None:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    _write_fixture(
        fixture_dir,
        "authorization-tests",
        "application.authorization_tests",
        {"wrong_role_status": 403, "unauthenticated_status": 401},
    )
    _write_fixture(
        fixture_dir,
        "resource-graph",
        "azure.resource_graph.inventory",
        {
            "resources": [
                {
                    "identity": {"type": "UserAssigned"},
                    "unauthenticatedClientAction": False,
                    "supportsHttpsTrafficOnly": True,
                    "isVersioningEnabled": True,
                    "deleteRetentionPolicy": {"enabled": True, "days": 14},
                    "image": "ghcr.io/example/aica@sha256:" + "a" * 64,
                    "securityRules": [
                        {
                            "name": "Deny-RDP-Internet",
                            "direction": "Inbound",
                            "access": "Deny",
                            "destinationPortRange": "3389",
                            "sourceAddressPrefix": "*",
                        }
                    ],
                }
            ]
        },
    )
    _write_fixture(
        fixture_dir,
        "rbac",
        "azure.rbac.assignments",
        {"assignments": [{"roleDefinitionName": "Reader"}]},
    )
    _write_fixture(
        fixture_dir,
        "diagnostics",
        "azure.monitor.diagnostic_settings",
        {
            "resources": [
                {
                    "resource_id": "synthetic/test",
                    "applicability": "APPLICABLE",
                    "settings": [
                        {
                            "properties": {
                                "workspaceId": "synthetic-operations-workspace",
                                "logs": [{"categoryGroup": "allLogs", "enabled": True}],
                            }
                        }
                    ],
                }
            ],
            "queried_count": 1,
        },
    )
    _write_fixture(
        fixture_dir,
        "assurance-health",
        "sentinel.assurance_health",
        {
            "tables": [
                {
                    "name": "PrimaryResult",
                    "columns": [
                        {"name": "RunId", "type": "string"},
                        {"name": "Status", "type": "string"},
                    ],
                        "rows": [["run-synthetic", "COMPLETED"]],
                }
            ],
            "RunId_g": "run-synthetic",
            "Status_s": "COMPLETED",
        },
    )
    _write_fixture(
        fixture_dir,
        "risky-changes",
        "sentinel.risky_changes",
        {
            "tables": [
                {
                    "name": "PrimaryResult",
                    "columns": [
                        {"name": "OperationNameValue", "type": "string"},
                        {"name": "Changes", "type": "long"},
                    ],
                    "rows": [["synthetic/write", 1]],
                }
            ]
        },
    )
    _write_fixture(
        fixture_dir,
        "branch-protection",
        "github.branch_protection",
        {"required_pull_request_reviews": {"required_approving_review_count": 1}},
    )
    _write_fixture(
        fixture_dir,
        "code-security",
        "github.code_security",
        {"advanced_security": {"status": "enabled"}, "unresolved_critical_alerts": 0},
    )
    _write_fixture(
        fixture_dir,
        "ci-supply-chain",
        "github.ci.supply_chain",
        {
            "assessed_commit": "a" * 40,
            "workflow_runs": [
                {"run_id": 123, "head_sha": "a" * 40, "conclusion": "success"}
            ],
            "artifacts": [
                {
                    "workflow_run_id": 123,
                    "head_sha": "a" * 40,
                    "digest": "sha256:" + "c" * 64,
                    "expired": False,
                }
            ],
        },
    )
    _write_fixture(
        fixture_dir,
        "ai-behavior",
        "ai.behavioral_evaluation",
        {"cases": [{"id": "case-001", "citation_valid": True}]},
    )
    _write_fixture(
        fixture_dir,
        "ai-operations",
        "ai.operational_events",
        {
            "events": [
                {
                    "evaluation_id": "eval-001",
                    "requested_tool": "create_access_exception",
                    "confirmation_state": "CONFIRMED",
                    "tool_result_status": "EXECUTED",
                }
            ]
        },
    )
    _write_fixture(
        fixture_dir,
        "ai-release",
        "ai.release_evaluation",
        {
            "evaluation_gate_status": "PASS",
            "evaluation_artifact_sha256": "b" * 64,
            "evaluated_configuration_sha256": "d" * 64,
            "deployed_configuration_sha256": "d" * 64,
            "evaluation_mode": "LIVE",
        },
    )

    objectives = []
    for rule in default_rules():
        objectives.append(
            {
                "id": rule.objective_id,
                "source_control": rule.objective_id.rsplit(".", 1)[0],
                "title": rule.title,
                "objective": f"Verify {rule.title.lower()}.",
                "methods": ["TEST"],
                "subject_selector": "synthetic/test",
                "cadence": "daily and on change",
                "evidence_requirements": list(rule.required_sources),
                "owner": "Assurance Owner",
                "automated": True,
            }
        )
    objective_path = tmp_path / "objectives.json"
    objective_path.write_text(json.dumps({"objectives": objectives}), encoding="utf-8")
    profile = AssessmentProfile(
        name="integration-replay",
        description="Test profile",
        trigger="manual",
        scope=("synthetic/test",),
        collectors=("replay",),
        fixture_dir=fixture_dir,
        objective_path=objective_path,
        estimated_cost_cad=0,
    )
    settings = Settings(
        env="test",
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=tmp_path / "policies",
        signing_key_path=tmp_path / "signing.pem",
        pseudonymization_secret="test-only-secret",
    )
    package, private_root = await AssessmentPipeline(settings).execute(profile)
    assert len(package.test_results) == 19
    assert {item.status for item in package.test_results} == {ResultStatus.PASS}
    assert package.system.system_id == "aica-student-assurance"
    assert len(package.system.data_flows) == 7

    private_manifest = load_signed_manifest(private_root / "run-manifest.json")
    assert verify_manifest(private_manifest, private_root) == []
    assert private_manifest.manifest.cost_breakdown.total_estimate_cad == 0
    public_root = settings.artifact_dir / "public" / package.run.id
    public_manifest = load_signed_manifest(public_root / "run-manifest.json")
    assert verify_manifest(public_manifest, public_root) == []
    read_model = CompositeRunStore([settings.artifact_dir / "public"])
    assert read_model.get(package.run.id).run.manifest_digest == public_manifest.manifest_sha256
    public_text = (public_root / "package.json").read_text(encoding="utf-8")
    assert "private://withheld" in public_text
    assert "synthetic-operations-workspace" in public_text


def test_checked_in_profiles_reference_runnable_objectives(monkeypatch) -> None:
    monkeypatch.setenv("AICA_AZURE_SUBSCRIPTION_ID", "00000000-0000-4000-8000-000000000001")
    azure = load_profile("azure-dev")
    replay = load_profile("replay")
    assert len(load_objectives(azure.objective_path)) == 35
    assert len(load_objectives(replay.objective_path)) == 35
    assert load_system_record(azure.system_record_path).system_id == "aica-student-assurance"
    assert azure.cost_breakdown.total_estimate_cad == azure.estimated_cost_cad == 0.25
    assert replay.cost_breakdown.total_estimate_cad == replay.estimated_cost_cad == 0


def test_system_record_rejects_undeclared_fields(tmp_path) -> None:
    raw = json.loads(Path("config/system-record.json").read_text(encoding="utf-8"))
    raw["inferred_architecture"] = "must not be accepted"
    path = tmp_path / "system.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        load_system_record(path)


def test_profile_rejects_cost_total_without_matching_breakdown(tmp_path) -> None:
    with pytest.raises(ValueError, match="estimated_cost_cad must equal"):
        AssessmentProfile(
            name="bad-cost",
            description="Inconsistent cost profile",
            trigger="manual",
            scope=("synthetic/test",),
            collectors=("replay",),
            fixture_dir=tmp_path,
            objective_path=tmp_path / "objectives.json",
            estimated_cost_cad=0.01,
        )


@pytest.mark.asyncio
async def test_checked_in_replay_fixtures_run_with_sanitized_classifications(tmp_path) -> None:
    profile = load_profile("replay")
    settings = Settings(
        env="test",
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=Path("data/policy-corpus"),
        signing_key_path=tmp_path / "signing.pem",
        pseudonymization_secret="test-only-secret",
    )
    package, private_root = await AssessmentPipeline(settings).execute(profile)
    assert len(package.objectives) == 35
    assert len(package.evidence) == 12
    assert (
        verify_manifest(load_signed_manifest(private_root / "run-manifest.json"), private_root)
        == []
    )


def _terminal_result(status: ResultStatus, reason_code: str = "TEST") -> DomainTestResult:
    return DomainTestResult(
        id=f"test-{status.value}",
        run_id="run-status",
        objective_id="SC-7.1",
        status=status,
        reason_code=reason_code,
        reason="deterministic terminal-state test",
        test_version="1.0.0",
        evidence_refs=("ev-1",) if status == ResultStatus.PASS else (),
    )


def test_terminal_run_status_distinguishes_failure_review_and_completion() -> None:
    assert terminal_run_status([_terminal_result(ResultStatus.ERROR)]) == RunStatus.FAILED
    assert (
        terminal_run_status([_terminal_result(ResultStatus.NOT_RUN, "STALE_EVIDENCE")])
        == RunStatus.FAILED
    )
    assert (
        terminal_run_status([_terminal_result(ResultStatus.NOT_RUN, "MANUAL_REVIEW_REQUIRED")])
        == RunStatus.REVIEW_REQUIRED
    )
    assert terminal_run_status([_terminal_result(ResultStatus.FAIL)]) == RunStatus.REVIEW_REQUIRED
    assert terminal_run_status([_terminal_result(ResultStatus.PASS)]) == RunStatus.COMPLETED
    assert terminal_run_status([_terminal_result(ResultStatus.NOT_APPLICABLE)]) == RunStatus.COMPLETED


def test_release_gate_blocks_test_failures_but_not_pending_manual_review() -> None:
    assert release_gate_failed([_terminal_result(ResultStatus.FAIL)])
    assert release_gate_failed([_terminal_result(ResultStatus.ERROR)])
    assert release_gate_failed([_terminal_result(ResultStatus.NOT_RUN, "STALE_EVIDENCE")])
    assert not release_gate_failed(
        [_terminal_result(ResultStatus.NOT_RUN, "MANUAL_REVIEW_REQUIRED")]
    )
    assert not release_gate_failed([_terminal_result(ResultStatus.PASS)])
