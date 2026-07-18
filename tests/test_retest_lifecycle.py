from __future__ import annotations

import json
from pathlib import Path

import pytest

from aica.config import Settings
from aica.domain.models import (
    AssessmentPackage,
    Effectiveness,
    EvidenceFreshness,
    ResultStatus,
    ReviewState,
)
from aica.evaluation.diff import build_retests
from aica.evaluation.engine import Rule, RuleEngine
from aica.evidence.manifest import load_signed_manifest, verify_manifest
from aica.pipeline import AssessmentPipeline, PriorRunIntegrityError
from aica.profiles import AssessmentProfile
from aica.util.canonical import sha256_file


def _profile(tmp_path: Path) -> AssessmentProfile:
    fixture_dir = tmp_path / "fixtures"
    fixture_dir.mkdir()
    (fixture_dir / "control.json").write_text(
        json.dumps(
            {
                "source": "synthetic.control",
                "query": {"fixture": "control"},
                "classification": "INTERNAL",
                "payload": {"condition": "bounded"},
            }
        ),
        encoding="utf-8",
    )
    objective_path = tmp_path / "objectives.json"
    objective_path.write_text(
        json.dumps(
            {
                "objectives": [
                    {
                        "id": "SC-7.1",
                        "source_control": "SC-7",
                        "title": "Boundary protection",
                        "objective": "No unrestricted administrative ingress is permitted.",
                        "methods": ["TEST"],
                        "subject_selector": "synthetic/network-boundary",
                        "cadence": "daily and on change",
                        "evidence_requirements": ["synthetic control evidence"],
                        "owner": "Cloud Security Owner",
                        "automated": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return AssessmentProfile(
        name="retest-lifecycle",
        description="One-objective lifecycle fixture",
        trigger="manual",
        scope=("synthetic/network-boundary",),
        collectors=("replay",),
        fixture_dir=fixture_dir,
        objective_path=objective_path,
    )


def _engine(*, passed: bool) -> RuleEngine:
    return RuleEngine(
        (
            Rule(
                id="R-SC-7-RETEST",
                objective_id="SC-7.1",
                title="Boundary protection",
                required_sources=("synthetic.control",),
                check=lambda evidence: (
                    passed,
                    "No unrestricted ingress was found."
                    if passed
                    else "Unrestricted ingress remains present.",
                    {"evidence_count": len(evidence)},
                ),
            ),
        )
    )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        env="test",
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=tmp_path / "policies",
        signing_key_path=tmp_path / "signing.pem",
        pseudonymization_secret="test-only-secret",
    )


@pytest.mark.asyncio
async def test_retest_verifies_prior_preserves_history_and_emits_signed_diff(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    profile = _profile(tmp_path)
    baseline, baseline_root = await AssessmentPipeline(
        settings,
        engine=_engine(passed=False),
    ).execute(profile)
    assert len(baseline.findings) == 1
    historical_finding = baseline.findings[0]
    assert historical_finding.objective_id == "SC-7.1"
    assert historical_finding.status == "OPEN"

    package_path = baseline_root / "package.json"
    original_package = package_path.read_bytes()
    original_digest = sha256_file(package_path)
    package_path.write_bytes(original_package + b"\n")
    with pytest.raises(PriorRunIntegrityError, match="integrity verification"):
        await AssessmentPipeline(settings, engine=_engine(passed=True)).execute(
            profile,
            prior_run_id=baseline.run.id,
        )
    assert len(list((settings.artifact_dir / "private").iterdir())) == 1
    package_path.write_bytes(original_package)

    retest, retest_root = await AssessmentPipeline(
        settings,
        engine=_engine(passed=True),
    ).execute(
        profile,
        prior_run_id=baseline.run.id,
        finding_ids=(historical_finding.id,),
    )
    assert sha256_file(package_path) == original_digest
    assert retest.run.prior_run_id == baseline.run.id
    assert retest.run.trigger == "retest"
    assert retest.findings[0] == historical_finding
    assert retest.findings[0].status == "OPEN"
    assert len(retest.retests) == 1
    outcome = retest.retests[0]
    assert outcome.finding_id == historical_finding.id
    assert outcome.objective_id == "SC-7.1"
    assert outcome.result == ResultStatus.PASS
    assert outcome.decision == "CLOSE"
    assert outcome.evidence_freshness == EvidenceFreshness.FRESH
    assert outcome.review_state == ReviewState.SUGGESTED
    assert outcome.review_decision_id is None

    diff = json.loads((retest_root / "assessment-diff.json").read_text(encoding="utf-8"))
    assert diff["from_run_id"] == baseline.run.id
    assert diff["to_run_id"] == retest.run.id
    assert diff["counts"] == {"resolved": 1}
    assert (settings.artifact_dir / "public" / retest.run.id / "assessment-diff.json").is_file()

    private_manifest = load_signed_manifest(retest_root / "run-manifest.json")
    assert verify_manifest(private_manifest, retest_root) == []
    assert "assessment-diff.json" in {
        artifact.path for artifact in private_manifest.manifest.artifacts
    }
    public_root = settings.artifact_dir / "public" / retest.run.id
    assert (
        verify_manifest(load_signed_manifest(public_root / "run-manifest.json"), public_root) == []
    )


@pytest.mark.asyncio
async def test_stale_nominal_pass_cannot_suggest_closure(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    profile = _profile(tmp_path)
    baseline, _ = await AssessmentPipeline(settings, engine=_engine(passed=False)).execute(profile)
    current, _ = await AssessmentPipeline(settings, engine=_engine(passed=True)).execute(
        profile,
        prior_run_id=baseline.run.id,
    )

    raw = current.model_dump(mode="python")
    raw["evidence"][0]["freshness"] = EvidenceFreshness.STALE
    raw["assessments"][0].update(
        {
            "design_effectiveness": Effectiveness.NOT_CONCLUDED,
            "operating_effectiveness": Effectiveness.NOT_CONCLUDED,
            "coverage_percent": 0,
            "conclusion": Effectiveness.NOT_CONCLUDED,
            "evidence_freshness": EvidenceFreshness.STALE,
        }
    )
    raw["retests"] = ()
    stale_current = AssessmentPackage.model_validate(raw)
    outcomes = build_retests(
        baseline,
        stale_current,
        finding_ids=(baseline.findings[0].id,),
    )
    assert len(outcomes) == 1
    assert outcomes[0].result == ResultStatus.NOT_RUN
    assert outcomes[0].decision == "REOPEN"
    assert outcomes[0].evidence_freshness == EvidenceFreshness.STALE
    assert outcomes[0].review_state == ReviewState.SUGGESTED

    with pytest.raises(ValueError, match="unknown prior finding IDs"):
        build_retests(baseline, stale_current, finding_ids=("finding-does-not-exist",))


@pytest.mark.asyncio
async def test_azure_prior_loader_verifies_every_manifest_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    profile = _profile(tmp_path)
    baseline, baseline_root = await AssessmentPipeline(
        settings,
        engine=_engine(passed=False),
    ).execute(profile)
    prefix = f"runs/{baseline.run.id}"
    blobs = {
        f"{prefix}/{path.relative_to(baseline_root).as_posix()}": path.read_bytes()
        for path in baseline_root.rglob("*")
        if path.is_file()
    }

    class Download:
        def __init__(self, content: bytes):
            self.content = content

        def readall(self) -> bytes:
            return self.content

    class Client:
        def download_blob(self, name: str) -> Download:
            return Download(blobs[name])

    class Store:
        client = Client()

    pipeline = AssessmentPipeline(settings)
    monkeypatch.setattr(pipeline, "_artifact_store", lambda container: Store())
    loaded = pipeline._load_verified_azure_prior_from_container(
        baseline.run.id,
        "aica-evidence",
    )
    assert loaded == baseline

    artifact_name = f"{prefix}/executive-summary.json"
    blobs[artifact_name] += b"tampered"
    with pytest.raises(PriorRunIntegrityError, match="artifact digest mismatch"):
        pipeline._load_verified_azure_prior_from_container(
            baseline.run.id,
            "aica-evidence",
        )


@pytest.mark.asyncio
async def test_verified_prior_projects_only_integrity_bound_remediation_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    profile = _profile(tmp_path)
    package, package_root = await AssessmentPipeline(
        settings,
        engine=_engine(passed=False),
    ).execute(profile)
    pipeline = AssessmentPipeline(settings)
    evidence_id = package.evidence[0].id
    manifest_digest = load_signed_manifest(package_root / "run-manifest.json").manifest_sha256
    event = {
        "_event_type": "REMEDIATION",
        "id": "remediation-live-1",
        "finding_id": package.findings[0].id,
        "owner": "Cloud Owner",
        "action": "Remove the broad ingress rule through reviewed infrastructure code.",
        "target_date": "2026-08-01T00:00:00Z",
        "commit_or_pr": "PR-101",
        "evidence_refs": [evidence_id],
        "status": "READY_FOR_RETEST",
        "recorded_by": "reviewer-1",
        "recorded_at": "2026-07-17T12:00:00Z",
        "artifact_run_id": package.run.id,
        "artifact_hash": manifest_digest,
        "expected_version": 1,
        "version": 2,
    }
    monkeypatch.setattr(pipeline, "_prior_review_events", lambda: [event])

    projected = pipeline._project_verified_prior_events(package, manifest_digest)

    assert projected.remediations[-1].id == "remediation-live-1"
    assert projected.remediations[-1].evidence_refs == (evidence_id,)
    assert projected.findings[0].status == "READY_FOR_RETEST"

    retest_pipeline = AssessmentPipeline(settings, engine=_engine(passed=True))
    monkeypatch.setattr(retest_pipeline, "_prior_review_events", lambda: [event])
    retest, retest_root = await retest_pipeline.execute(
        profile,
        prior_run_id=package.run.id,
        finding_ids=(package.findings[0].id,),
    )
    assert [item.id for item in retest.remediations] == ["remediation-live-1"]
    second_digest = load_signed_manifest(retest_root / "run-manifest.json").manifest_sha256
    second_pipeline = AssessmentPipeline(settings)
    monkeypatch.setattr(second_pipeline, "_prior_review_events", lambda: [event])
    projected_second_hop = second_pipeline._project_verified_prior_events(
        retest,
        second_digest,
    )
    assert [item.id for item in projected_second_hop.remediations] == ["remediation-live-1"]

    bad_event = {**event, "id": "remediation-bad", "evidence_refs": ["EVD-UNKNOWN"]}
    monkeypatch.setattr(pipeline, "_prior_review_events", lambda: [bad_event])
    with pytest.raises(PriorRunIntegrityError, match="invalid bound review events"):
        pipeline._project_verified_prior_events(package, manifest_digest)
