from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aica.api import create_app
from aica.config import Settings
from aica.evaluation.behavioral import (
    BehavioralEvaluationError,
    configured_adapter_provenance,
    runtime_evaluation_configuration,
)
from aica.evidence.manifest import CadCostBreakdown, LocalEs256Signer, build_manifest, sign_manifest
from aica.util.canonical import canonical_json_bytes, sha256_value
from conftest import package

ZERO_COST = CadCostBreakdown(
    model_estimate_cad=0,
    compute_estimate_cad=0,
    storage_estimate_cad=0,
    telemetry_estimate_cad=0,
    total_estimate_cad=0,
)


def test_public_api_reads_sanitized_run_and_rejects_commands(tmp_path, now) -> None:
    data_dir = tmp_path / "data"
    run_dir = data_dir / "run-1"
    run_dir.mkdir(parents=True)
    run_dir.joinpath("package.json").write_bytes(canonical_json_bytes(package(now)))
    manifest = build_manifest(
        run_id="run-1",
        root=run_dir,
        paths=[run_dir / "package.json"],
        git_commit="abcdef0",
        collector_version="1.0.0",
        evaluator_version="1.0.0",
        cost_estimate_cad=0,
        cost_breakdown=ZERO_COST,
        public=True,
    )
    run_dir.joinpath("run-manifest.json").write_bytes(
        canonical_json_bytes(sign_manifest(manifest, LocalEs256Signer(tmp_path / "key.pem")))
    )
    settings = Settings(
        env="test",
        data_dir=data_dir,
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=tmp_path / "policies",
        public_mode=True,
        pseudonymization_secret="test-only-secret",
        confirmation_ttl_seconds=17,
        request_limit_per_user_per_hour=6,
    )
    client = TestClient(create_app(settings))
    assistant = client.app.state.assistant
    assert assistant.confirmation_ttl.total_seconds() == 17
    assert assistant.rate_limiter.limit == 6
    expected_configuration = runtime_evaluation_configuration(
        adapter=configured_adapter_provenance(
            kind="replay",
            deployment="deterministic-replay",
        ),
        max_output_tokens=settings.model_max_output_tokens,
        confirmation_ttl_seconds=settings.confirmation_ttl_seconds,
        requests_per_user_hour=settings.request_limit_per_user_per_hour,
    )
    health = client.get("/healthz")
    assert health.headers["Cache-Control"] == "no-store"
    assert health.json() == {
        "status": "healthy",
        "mode": "public",
        "evaluation_configuration_sha256": sha256_value(expected_configuration),
    }
    assert client.get("/api/v1/runs").status_code == 200
    response = client.get("/api/v1/runs/run-1")
    assert response.status_code == 200
    assert response.json()["run"]["id"] == "run-1"

    command = client.post(
        "/api/v1/run-requests",
        json={"profile": "replay", "reason": "Verify the current synthetic baseline."},
        headers={"X-AICA-Reviewer": "reviewer-1"},
    )
    assert command.status_code == 403


def test_health_digest_independently_binds_source_and_three_deployed_images(tmp_path) -> None:
    base = {
        "deployed_source_commit": "a" * 40,
        "assurance_api_image_sha256": "1" * 64,
        "assistant_ui_image_sha256": "2" * 64,
        "assurance_job_image_sha256": "3" * 64,
    }
    variants = [base]
    for field, replacement in (
        ("deployed_source_commit", "b" * 40),
        ("assurance_api_image_sha256", "4" * 64),
        ("assistant_ui_image_sha256", "5" * 64),
        ("assurance_job_image_sha256", "6" * 64),
    ):
        variants.append({**base, field: replacement})

    health_bodies = []
    for provenance in variants:
        settings = Settings(
            env="test",
            data_dir=tmp_path / "data",
            artifact_dir=tmp_path / "artifacts",
            policy_corpus_dir=Path("data/policy-corpus"),
            public_mode=True,
            pseudonymization_secret="test-only-secret",
            **provenance,
        )
        health_bodies.append(TestClient(create_app(settings)).get("/healthz").json())

    digests = {body["evaluation_configuration_sha256"] for body in health_bodies}
    assert len(digests) == len(variants)
    for body in health_bodies:
        assert set(body) == {"status", "mode", "evaluation_configuration_sha256"}
        serialized = json.dumps(body)
        assert all(value not in serialized for value in base.values())


def test_production_policy_assistant_requires_deployed_image_provenance(tmp_path) -> None:
    settings = Settings(
        env="production",
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=Path("data/policy-corpus"),
        public_mode=True,
        assistant_enabled=True,
        assurance_enabled=False,
    )

    with pytest.raises(
        BehavioralEvaluationError,
        match="requires exact deployed source and image provenance",
    ):
        create_app(settings)


def test_private_command_requires_identity_and_is_queued(tmp_path) -> None:
    settings = Settings(
        env="test",
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=tmp_path / "policies",
        public_mode=False,
        pseudonymization_secret="test-only-secret",
    )
    client = TestClient(create_app(settings))
    body = {"profile": "replay", "reason": "Verify the current synthetic baseline."}
    assert client.post("/api/v1/run-requests", json=body).status_code == 401
    accepted = client.post(
        "/api/v1/run-requests",
        json=body,
        headers={
            "X-AICA-Reviewer": "reviewer-1",
            "X-AICA-Roles": "Assurance.Assessor",
        },
    )
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "QUEUED"
    assert list((tmp_path / "artifacts" / "requests").glob("*.json"))


def test_private_command_rejects_authenticated_wrong_role(tmp_path) -> None:
    settings = Settings(
        env="test",
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=tmp_path / "policies",
        public_mode=False,
        pseudonymization_secret="test-only-secret",
    )
    client = TestClient(create_app(settings))
    response = client.post(
        "/api/v1/run-requests",
        json={"profile": "replay", "reason": "Verify the current synthetic baseline."},
        headers={
            "X-AICA-Reviewer": "reviewer-1",
            "X-AICA-Roles": "Assurance.Reviewer",
        },
    )
    assert response.status_code == 403


def test_ai_suggestion_review_is_bound_to_a_signed_package_subject(tmp_path) -> None:
    settings = Settings(
        env="test",
        data_dir=Path("data/sample-runs"),
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=Path("data/policy-corpus"),
        public_mode=False,
        pseudonymization_secret="test-only-secret",
    )
    client = TestClient(create_app(settings))
    reviewer = {
        "X-AICA-Reviewer": "reviewer-1",
        "X-AICA-Roles": "Assurance.Reviewer",
    }
    body = {
        "subject_type": "AI_SUGGESTION",
        "subject_id": "AI-MAP-DP-01:018f6d9a-7b10-7c01-8000-000000000002",
        "artifact_run_id": "018f6d9a-7b10-7c01-8000-000000000002",
        "prior_state": "SUGGESTED",
        "decision": "ACCEPT",
        "rationale": "The reviewer verified the suggested mapping against signed evidence.",
        "expected_version": 0,
    }

    accepted = client.post("/api/v1/review-decisions", json=body, headers=reviewer)
    assert accepted.status_code == 202
    request_dir = tmp_path / "artifacts" / "requests"
    queued = json.loads(next(request_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert queued["payload"]["subject_id"].startswith("AI-MAP-DP-01:")
    assert len(queued["payload"]["artifact_hash"]) == 64

    rejected = client.post(
        "/api/v1/review-decisions",
        json={**body, "subject_id": "AI-SUGGESTION-UNKNOWN"},
        headers=reviewer,
    )
    assert rejected.status_code == 404
    assert len(list(request_dir.glob("*.json"))) == 1


def test_private_evaluation_endpoint_composes_fixed_behavior_and_mapping_metrics(tmp_path) -> None:
    settings = Settings(
        env="test",
        data_dir=Path("data/sample-runs"),
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=Path("data/policy-corpus"),
        public_mode=False,
        pseudonymization_secret="test-only-secret",
    )
    response = TestClient(create_app(settings)).get(
        "/api/v1/evaluations/018f6d9a-7b10-7c01-8000-000000000002"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 50
    assert body["passed"] == 50
    assert body["precision"] >= 0.9
    assert len(body["cases"]) == 50
    assert body["executionMode"] == "REPLAY"
    assert body["suggestedMapping"] == {
        "id": "AI-MAP-DP-01:018f6d9a-7b10-7c01-8000-000000000002",
        "text": (
            "Candidate mapping: citation-valid indirect-prompt-injection results support "
            "objective AI-DP-01.1; a reviewer must verify the evidence references and conclusion."
        ),
        "state": "SUGGESTED",
        "reviewVersion": 0,
    }
    source = json.loads(Path("data/ai-evaluations/replay-results.json").read_text())
    recorded = source["results"]["BEH-001"]
    projected = next(item for item in body["cases"] if item["id"] == "BEH-001")
    assert "response" not in projected
    assert "promptLabel" not in projected
    assert projected["inputSha256"] == recorded["prompt_sha256"]
    assert "findingId" not in projected
    assert projected["correlationId"] == recorded["correlation_id"]
    assert projected["latencyMs"] == recorded["latency_ms"]
    assert projected["retrievedDocuments"] == recorded["retrieved_documents"]
    exact = TestClient(create_app(settings)).get(f"/api/v1/evaluations/{source['evaluation_id']}")
    assert exact.status_code == 200
    assert exact.json()["id"] == source["evaluation_id"]


def test_evaluation_api_fails_closed_on_invalid_runtime_artifact(tmp_path) -> None:
    data_dir = tmp_path / "data"
    run_dir = data_dir / "invalid-evaluation"
    run_dir.mkdir(parents=True)
    package_value = json.loads(
        Path("data/sample-runs/remediated/package.json").read_text(encoding="utf-8")
    )
    evaluation_evidence = next(
        item for item in package_value["evidence"] if item["source"] == "AI_BEHAVIORAL_EVALUATION"
    )
    evaluation_evidence["payload"]["nodes"][0]["latency_ms"] = -1
    package_path = run_dir / "package.json"
    package_path.write_bytes(canonical_json_bytes(package_value))
    manifest = build_manifest(
        run_id=package_value["run"]["id"],
        root=run_dir,
        paths=[package_path],
        git_commit=package_value["run"]["git_commit"],
        collector_version=package_value["run"]["collector_version"],
        evaluator_version=package_value["run"]["evaluator_version"],
        cost_estimate_cad=0,
        cost_breakdown=ZERO_COST,
        public=False,
    )
    signed = sign_manifest(manifest, LocalEs256Signer(tmp_path / "invalid-eval-key.pem"))
    (run_dir / "run-manifest.json").write_bytes(canonical_json_bytes(signed))
    settings = Settings(
        env="test",
        data_dir=data_dir,
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=Path("data/policy-corpus"),
        public_mode=False,
        pseudonymization_secret="test-only-secret",
    )

    response = TestClient(create_app(settings)).get(
        f"/api/v1/evaluations/{package_value['run']['id']}"
    )
    assert response.status_code == 503
    assert "invalid latency observation" in response.json()["detail"]


def test_review_decision_is_bound_to_verified_assessment_manifest(tmp_path) -> None:
    settings = Settings(
        env="test",
        data_dir=Path("data/sample-runs"),
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=Path("data/policy-corpus"),
        public_mode=False,
        pseudonymization_secret="test-only-secret",
    )
    response = TestClient(create_app(settings)).post(
        "/api/v1/review-decisions",
        json={
            "subject_type": "CONTROL",
            "subject_id": "AC-2.1",
            "artifact_run_id": "018f6d9a-7b10-7c01-8000-000000000001",
            "prior_state": "SUGGESTED",
            "decision": "ACCEPTED",
            "rationale": "The signed evidence is current and sufficient for this conclusion.",
            "expected_version": 1,
        },
        headers={
            "X-AICA-Reviewer": "reviewer-1",
            "X-AICA-Roles": "Assurance.Reviewer",
        },
    )
    assert response.status_code == 202
    request_path = next((tmp_path / "artifacts" / "requests").glob("*.json"))
    queued = json.loads(request_path.read_text(encoding="utf-8"))
    baseline_manifest = json.loads(
        Path("data/sample-runs/baseline/run-manifest.json").read_text(encoding="utf-8")
    )
    assert queued["payload"]["artifact_hash"] == baseline_manifest["manifest_sha256"]
    assert queued["payload"]["artifact_run_id"] == "018f6d9a-7b10-7c01-8000-000000000001"


def _write_review_lifecycle_package(tmp_path) -> Path:
    data_dir = tmp_path / "review-data"
    run_dir = data_dir / "run-review"
    run_dir.mkdir(parents=True)
    raw = {
        "run": {
            "id": "run-review",
            "started_at": "2026-07-16T12:00:00Z",
            "git_commit": "abcdef0",
            "collector_version": "1.0.0",
            "evaluator_version": "1.0.0",
            "estimated_cost_cad": 0,
        },
        "objectives": [],
        "findings": [
            {"id": "FND-CLOSE", "status": "READY_FOR_RETEST"},
            {"id": "FND-NO-RETEST", "status": "READY_FOR_RETEST"},
        ],
        "risks": [],
        "evidence": [{"id": "EVD-NEW"}],
        "retests": [
            {
                "id": "RET-CLOSE",
                "finding_id": "FND-CLOSE",
                "result": "PASS",
                "decision": "CLOSE",
                "evidence_freshness": "FRESH",
                "evidence_refs": ["EVD-NEW"],
            }
        ],
    }
    package_path = run_dir / "package.json"
    package_path.write_bytes(canonical_json_bytes(raw))
    manifest = build_manifest(
        run_id="run-review",
        root=run_dir,
        paths=[package_path],
        git_commit="abcdef0",
        collector_version="1.0.0",
        evaluator_version="1.0.0",
        cost_estimate_cad=0,
        cost_breakdown=ZERO_COST,
        public=True,
    )
    run_dir.joinpath("run-manifest.json").write_bytes(
        canonical_json_bytes(sign_manifest(manifest, LocalEs256Signer(tmp_path / "review-key.pem")))
    )
    return data_dir


def test_retest_and_closure_commands_are_bound_to_signed_lifecycle_evidence(tmp_path) -> None:
    data_dir = _write_review_lifecycle_package(tmp_path)
    settings = Settings(
        env="test",
        data_dir=data_dir,
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=tmp_path / "policies",
        public_mode=False,
        pseudonymization_secret="test-only-secret",
    )
    client = TestClient(create_app(settings))
    assessor = {
        "X-AICA-Reviewer": "assessor-1",
        "X-AICA-Roles": "Assurance.Assessor",
    }
    reviewer = {
        "X-AICA-Reviewer": "reviewer-1",
        "X-AICA-Roles": "Assurance.Reviewer",
    }

    valid_retest = client.post(
        "/api/v1/retest-requests",
        json={
            "prior_run_id": "run-review",
            "finding_ids": ["FND-CLOSE"],
            "reason": "Collect fresh evidence for the selected finding.",
        },
        headers=assessor,
    )
    assert valid_retest.status_code == 202
    invalid_retest = client.post(
        "/api/v1/retest-requests",
        json={
            "prior_run_id": "run-review",
            "finding_ids": ["FND-UNKNOWN"],
            "reason": "Collect fresh evidence for the selected finding.",
        },
        headers=assessor,
    )
    assert invalid_retest.status_code == 422

    close_body = {
        "subject_type": "FINDING",
        "subject_id": "FND-CLOSE",
        "artifact_run_id": "run-review",
        "prior_state": "READY_FOR_RETEST",
        "decision": "CLOSE",
        "rationale": "Fresh signed retest evidence supports reviewer closure.",
        "expected_version": 1,
    }
    assert (
        client.post("/api/v1/review-decisions", json=close_body, headers=reviewer).status_code
        == 202
    )
    unsupported = {
        **close_body,
        "subject_id": "FND-NO-RETEST",
        "rationale": "Closure must fail because no fresh retest exists.",
    }
    response = client.post("/api/v1/review-decisions", json=unsupported, headers=reviewer)
    assert response.status_code == 409
    assert "fresh passing retest" in response.json()["detail"]


def test_remediation_ready_is_authorized_and_bound_to_signed_evidence(tmp_path) -> None:
    data_dir = _write_review_lifecycle_package(tmp_path)
    settings = Settings(
        env="test",
        data_dir=data_dir,
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=tmp_path / "policies",
        public_mode=False,
        pseudonymization_secret="test-only-secret",
    )
    client = TestClient(create_app(settings))
    body = {
        "finding_id": "FND-CLOSE",
        "artifact_run_id": "run-review",
        "owner": "Cloud Owner",
        "action": "Remove the broad ingress rule in version-controlled infrastructure.",
        "target_date": "2026-08-01T00:00:00Z",
        "commit_or_pr": "https://github.example/pull/101",
        "evidence_refs": ["EVD-NEW"],
        "expected_version": 1,
    }
    reviewer = {
        "X-AICA-Reviewer": "reviewer-1",
        "X-AICA-Roles": "Assurance.Reviewer",
    }

    response = client.post("/api/v1/remediations", json=body, headers=reviewer)
    assert response.status_code == 202
    queued = json.loads(next((tmp_path / "artifacts" / "requests").glob("*.json")).read_text())
    manifest = json.loads(
        (data_dir / "run-review" / "run-manifest.json").read_text(encoding="utf-8")
    )
    assert queued["type"] == "MARK_REMEDIATION_READY"
    assert queued["payload"]["artifact_run_id"] == "run-review"
    assert queued["payload"]["artifact_hash"] == manifest["manifest_sha256"]
    assert queued["payload"]["evidence_refs"] == ["EVD-NEW"]

    wrong_role = client.post(
        "/api/v1/remediations",
        json=body,
        headers={
            "X-AICA-Reviewer": "assessor-1",
            "X-AICA-Roles": "Assurance.Assessor",
        },
    )
    assert wrong_role.status_code == 403
    unknown_evidence = client.post(
        "/api/v1/remediations",
        json={**body, "evidence_refs": ["EVD-UNKNOWN"]},
        headers=reviewer,
    )
    assert unknown_evidence.status_code == 422
    assert "does not contain remediation evidence" in unknown_evidence.json()["detail"]


def test_policy_assistant_capability_does_not_expose_assurance_api(tmp_path) -> None:
    settings = Settings(
        env="test",
        data_dir=Path("data/sample-runs"),
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=Path("data/policy-corpus"),
        public_mode=False,
        assistant_enabled=True,
        assurance_enabled=False,
        pseudonymization_secret="test-only-secret",
    )
    client = TestClient(create_app(settings))

    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/runs").status_code == 404
    response = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "Who approves privileged access?",
            "session_id": "session-capability-test",
        },
    )
    assert response.status_code == 200
    assert response.json()["citations"]


def test_assurance_capability_does_not_expose_policy_assistant(tmp_path) -> None:
    settings = Settings(
        env="test",
        data_dir=Path("data/sample-runs"),
        artifact_dir=tmp_path / "artifacts",
        policy_corpus_dir=Path("data/policy-corpus"),
        public_mode=True,
        assistant_enabled=False,
        assurance_enabled=True,
        pseudonymization_secret="test-only-secret",
    )
    client = TestClient(create_app(settings))

    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/runs").status_code == 200
    response = client.post(
        "/api/v1/assistant/chat",
        json={
            "message": "Who approves privileged access?",
            "session_id": "session-capability-test",
        },
    )
    assert response.status_code == 404


def test_production_assurance_only_app_does_not_require_assistant_secrets(tmp_path) -> None:
    settings = Settings(
        env="production",
        data_dir=tmp_path / "data",
        artifact_dir=tmp_path / "artifacts",
        public_mode=False,
        assistant_enabled=False,
        assurance_enabled=True,
        trusted_signing_key_fingerprints="a" * 64,
    )

    client = TestClient(create_app(settings))
    assert client.get("/healthz").json() == {"status": "healthy", "mode": "private"}
    assert (
        client.post(
            "/api/v1/assistant/chat",
            json={"message": "disabled", "session_id": "session-capability-test"},
        ).status_code
        == 404
    )
