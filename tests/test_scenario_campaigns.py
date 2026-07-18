from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import typer

from aica.cli import _scenario_path
from aica.domain.models import ResultStatus, ReviewState
from aica.scenarios import ScenarioLifecycleProof, build_scenario_campaign_artifact

ROOT = Path(__file__).resolve().parents[1]


def _conftest() -> Path:
    selected = shutil.which("conftest")
    if selected is None:
        pytest.skip("pinned Conftest is not installed")
    return Path(selected)


def test_all_scenario_campaigns_execute_and_link_the_full_lifecycle() -> None:
    artifact = build_scenario_campaign_artifact(ROOT, _conftest())

    assert len(artifact.campaigns) == 8
    assert all(item.baseline.status == ResultStatus.PASS for item in artifact.campaigns)
    assert all(item.injection.status == ResultStatus.FAIL for item in artifact.campaigns)
    assert all(item.retest.result == ResultStatus.PASS for item in artifact.campaigns)
    assert all(item.cleanup.verified for item in artifact.campaigns)
    assert all(not item.execution.azure_live_evidence_checked_in for item in artifact.campaigns)
    signed = [item for item in artifact.campaigns if item.signed_lifecycle is not None]
    assert {item.scenario_id for item in signed} == {"SCN-001", "SCN-006", "SCN-007", "SCN-008"}
    assert all(item.retest.review_state == ReviewState.ACCEPTED for item in signed)
    unsigned = [item for item in artifact.campaigns if item.signed_lifecycle is None]
    assert all(item.retest.review_state == ReviewState.SUGGESTED for item in unsigned)


def test_tool_campaign_executes_declared_negative_and_positive_counts() -> None:
    artifact = build_scenario_campaign_artifact(ROOT, _conftest())
    campaign = next(item for item in artifact.campaigns if item.scenario_id == "SCN-007")

    assert campaign.retest.assertion_counts["negative_cases"] >= 12
    assert campaign.retest.assertion_counts["confirmed_positive_cases"] == 2
    assert campaign.retest.assertion_counts["missing_confirmation_cases"] >= 1
    assert campaign.retest.assertion_counts["expired_confirmation_cases"] == 1
    assert campaign.retest.assertion_counts["replayed_confirmation_cases"] == 1
    assert campaign.retest.assertion_counts["binding_mismatch_cases"] == 2


def test_lifecycle_model_rejects_observation_evidence_substitution() -> None:
    artifact = build_scenario_campaign_artifact(ROOT, _conftest())
    raw = artifact.campaigns[0].model_dump(mode="python")
    raw["observation"]["evidence_refs"] = raw["baseline"]["evidence_refs"]

    with pytest.raises(ValueError, match="exact injected evidence"):
        ScenarioLifecycleProof.model_validate(raw)


def test_lifecycle_model_rejects_stale_closure_evidence() -> None:
    artifact = build_scenario_campaign_artifact(ROOT, _conftest())
    raw = artifact.campaigns[0].model_dump(mode="python")
    raw["retest"]["evidence_freshness"] = "STALE"

    with pytest.raises(ValueError, match="fresh retest evidence"):
        ScenarioLifecycleProof.model_validate(raw)


def test_azure_fixture_handoff_rejects_offline_or_replay_scenarios() -> None:
    with pytest.raises(typer.BadParameter, match="not an Azure fixture handoff"):
        _scenario_path("SCN-004", deployable_only=True)
    assert _scenario_path("SCN-002", deployable_only=True).name.startswith("SCN-002-")
