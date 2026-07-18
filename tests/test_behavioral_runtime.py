from __future__ import annotations

import copy
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from aica.assistant.adapters import ModelAnswer, ReplayModelAdapter
from aica.assistant.contracts import Citation
from aica.collectors.ai import (
    AiEvaluationCollector,
    compose_behavioral_evidence_payload,
    load_mapping_metrics,
    load_mapping_suggestion,
)
from aica.collectors.base import CollectionRequest
from aica.evaluation.behavioral import (
    BehavioralEvaluationError,
    EvaluationAdapter,
    load_behavioral_result,
    run_behavioral_evaluation,
    validate_behavioral_result,
    write_behavioral_result,
)
from aica.util.canonical import sha256_value

CASES = Path("data/ai-evaluations/behavioral-cases.json")
CORPUS = Path("data/policy-corpus")
FIXTURES = Path("data/ai-evaluations/controlled-fixtures.json")
CONFIGURATION = Path("data/ai-evaluations/replay-configuration.json")


class CountingReplayAdapter:
    def __init__(self) -> None:
        self.delegate = ReplayModelAdapter()
        self.calls = 0

    async def answer(self, question: str, citations: tuple[Citation, ...]) -> ModelAnswer:
        self.calls += 1
        return await self.delegate.answer(question, citations)


async def _artifact(
    adapter: CountingReplayAdapter | None = None,
    *,
    confirmation_ttl_seconds: int = 300,
    requests_per_user_hour: int = 10,
    corpus_dir: Path = CORPUS,
) -> dict[str, object]:
    selected = adapter or CountingReplayAdapter()
    adapter_name = "CountingReplayAdapter" if adapter else "ReplayModelAdapter"
    adapter_version = "test-1" if adapter else "2026-07-16"
    configuration = json.loads(CONFIGURATION.read_text(encoding="utf-8"))
    configuration["adapter"]["name"] = adapter_name
    configuration["adapter"]["version"] = adapter_version
    configuration["guardrails"]["confirmation_ttl_seconds"] = confirmation_ttl_seconds
    configuration["guardrails"]["requests_per_user_hour"] = requests_per_user_hour
    return await run_behavioral_evaluation(
        cases_path=CASES,
        corpus_dir=corpus_dir,
        controlled_fixtures_path=FIXTURES,
        configuration=configuration,
        configuration_source=CONFIGURATION.name,
        adapter=EvaluationAdapter(
            model=selected,
            kind="replay",
            name=adapter_name,
            version=adapter_version,
            deployment="deterministic-replay",
        ),
        now=datetime(2026, 7, 16, 12, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_fixed_cases_execute_through_service_and_record_observations() -> None:
    model = CountingReplayAdapter()
    artifact = await _artifact(model)

    assert artifact["summary"]["cases"] == 50  # type: ignore[index]
    assert artifact["summary"]["failed"] == 0  # type: ignore[index]
    assert model.calls >= 30
    results = artifact["results"]  # type: ignore[assignment]
    grounded = results["BEH-001"]  # type: ignore[index]
    assert grounded["correlation_id"].startswith("corr-")
    assert grounded["model"] == "replay"
    assert grounded["retrieved_documents"]
    assert grounded["latency_ms"] >= 0
    assert "response" not in grounded
    assert len(grounded["response_sha256"]) == 64
    assert results["BEH-028"]["tool_calls"][0]["confirmation"] == "EXPIRED"  # type: ignore[index]
    assert results["BEH-029"]["tool_calls"][0]["confirmation"] == "REPLAYED"  # type: ignore[index]
    assert results["BEH-030"]["tool_calls"][0]["confirmation"] == "MISMATCH"  # type: ignore[index]
    assert results["BEH-044"]["guardrail_outcomes"] == ["RATE_LIMIT_BLOCKED"]  # type: ignore[index]
    assert results["BEH-049"]["tool_calls"][0] == {  # type: ignore[index]
        "name": "create_access_exception",
        "authorization": "ALLOWED",
        "confirmation": "CONFIRMED",
        "status": "EXECUTED",
    }
    assert results["BEH-050"]["tool_calls"][0]["status"] == "EXECUTED"  # type: ignore[index]


@pytest.mark.asyncio
async def test_evaluation_exercises_effective_confirmation_and_rate_limits() -> None:
    artifact = await _artifact(
        confirmation_ttl_seconds=2,
        requests_per_user_hour=3,
    )

    assert artifact["runtime"]["confirmation_ttl_seconds"] == 2  # type: ignore[index]
    assert artifact["runtime"]["requests_per_user_hour"] == 3  # type: ignore[index]
    assert artifact["results"]["BEH-028"]["tool_calls"][0]["confirmation"] == "EXPIRED"  # type: ignore[index]
    assert artifact["results"]["BEH-044"]["guardrail_outcomes"] == [  # type: ignore[index]
        "RATE_LIMIT_BLOCKED"
    ]


@pytest.mark.asyncio
async def test_evaluation_rejects_unmanifested_local_corpus_file(tmp_path: Path) -> None:
    corpus = tmp_path / "policy-corpus"
    shutil.copytree(CORPUS, corpus)
    (corpus / "unreviewed.md").write_text("# Unreviewed policy", encoding="utf-8")

    with pytest.raises(BehavioralEvaluationError, match="unmanifested corpus"):
        await _artifact(corpus_dir=corpus)


def test_checked_in_result_is_runtime_schema_and_valid() -> None:
    artifact = load_behavioral_result(CASES, Path("data/ai-evaluations/replay-results.json"))
    assert artifact["schema_version"] == "1.0.0"
    assert artifact["execution_mode"] == "REPLAY"
    assert artifact["runtime"]["selected_model_result_count"] > 0


def test_signed_public_evaluation_matches_sources_and_detects_drift() -> None:
    package = json.loads(
        Path("data/sample-runs/remediated/package.json").read_text(encoding="utf-8")
    )
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    replay = json.loads(Path("data/ai-evaluations/replay-results.json").read_text(encoding="utf-8"))
    baseline = json.loads(
        Path("data/collector-fixtures/baseline/ai.behavioral_evaluation.json").read_text(
            encoding="utf-8"
        )
    )
    baseline_by_id = {str(item["id"]): item for item in baseline["payload"]["nodes"]}
    suggestion = load_mapping_suggestion(
        Path("data/ai-evaluations/mapping-suggestion.json"),
        run_id=package["run"]["id"],
        evaluation_id=replay["evaluation_id"],
    )

    def composed(results: dict[str, object]) -> dict[str, object]:
        return compose_behavioral_evidence_payload(
            cases=cases,
            results=results,
            mapping_metrics=load_mapping_metrics(
                Path("data/mapping-benchmark/human-labeled-examples.json")
            ),
            suggested_mapping=suggestion,
            baseline_by_id=baseline_by_id,
        )

    signed = next(
        item["payload"]
        for item in package["evidence"]
        if item["source"] == "AI_BEHAVIORAL_EVALUATION"
    )
    assert signed == composed(replay)

    drifted = copy.deepcopy(replay)
    drifted["results"]["BEH-001"]["passed"] = False
    assert signed != composed(drifted)


@pytest.mark.asyncio
async def test_validator_rejects_manual_live_claim_and_replay_disguised_as_live() -> None:
    artifact = await _artifact()
    dataset = json.loads(CASES.read_text(encoding="utf-8"))
    manually_claimed = copy.deepcopy(artifact)
    manually_claimed["live_endpoint_verified"] = True
    with pytest.raises(BehavioralEvaluationError, match="manual live verification"):
        validate_behavioral_result(dataset, manually_claimed)

    missing_deployment = copy.deepcopy(artifact)
    missing_deployment["execution_mode"] = "LIVE"
    missing_deployment["adapter"]["kind"] = "foundry"
    missing_deployment["adapter"]["endpoint_sha256"] = "e" * 64
    with pytest.raises(BehavioralEvaluationError, match="deployment provenance is missing"):
        validate_behavioral_result(dataset, missing_deployment)

    disguised = copy.deepcopy(artifact)
    disguised["execution_mode"] = "LIVE"
    disguised["adapter"]["kind"] = "foundry"
    disguised["adapter"]["endpoint_sha256"] = "e" * 64
    disguised["configuration"]["snapshot"]["deployment"] = {
        "source_commit": "a" * 40,
        "images": {
            "assurance_api_sha256": "1" * 64,
            "assistant_ui_sha256": "2" * 64,
            "assurance_job_sha256": "3" * 64,
        },
    }
    disguised_digest = sha256_value(disguised["configuration"]["snapshot"])
    disguised["configuration"]["sha256"] = disguised_digest
    disguised["configuration_sha256"] = disguised_digest
    with pytest.raises(BehavioralEvaluationError, match="replay selected-model"):
        validate_behavioral_result(dataset, disguised)


@pytest.mark.asyncio
async def test_validator_rejects_configuration_without_effective_limits() -> None:
    artifact = await _artifact()
    dataset = json.loads(CASES.read_text(encoding="utf-8"))
    missing_ttl = copy.deepcopy(artifact)
    snapshot = missing_ttl["configuration"]["snapshot"]
    del snapshot["guardrails"]["confirmation_ttl_seconds"]
    digest = sha256_value(snapshot)
    missing_ttl["configuration"]["sha256"] = digest
    missing_ttl["configuration_sha256"] = digest

    with pytest.raises(BehavioralEvaluationError, match="confirmation TTL"):
        validate_behavioral_result(dataset, missing_ttl)


@pytest.mark.asyncio
async def test_collector_validates_and_consumes_generated_result(tmp_path: Path) -> None:
    artifact = await _artifact()
    root = tmp_path / "ai-evaluations"
    root.mkdir()
    (root / "behavioral-cases.json").write_bytes(CASES.read_bytes())
    (root / "mapping-suggestion.json").write_bytes(
        Path("data/ai-evaluations/mapping-suggestion.json").read_bytes()
    )
    write_behavioral_result(root / "replay-results.json", artifact)
    now = datetime.now(UTC)
    evidence = await AiEvaluationCollector(root).collect(
        CollectionRequest(
            run_id="run-controlled-evaluation",
            observation_window_start=now - timedelta(hours=1),
            observation_window_end=now,
            scope=("synthetic-policy-assistant",),
            output_dir=tmp_path / "output",
        )
    )

    behavioral, release = evidence
    assert behavioral.raw_payload["evaluation_id"] == artifact["evaluation_id"]
    assert behavioral.raw_payload["evaluation_mode"] == "REPLAY"
    assert len(behavioral.raw_payload["nodes"]) == 50
    assert release.raw_payload["nodes"][0]["evaluation_gate_status"] == "FAIL"
