from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from aica.assistant.adapters import ModelAnswer, ReplayModelAdapter
from aica.assistant.contracts import Citation
from aica.collectors.ai import AiEvaluationCollector
from aica.collectors.base import CollectionRequest
from aica.config import Settings
from aica.evaluation.behavioral import (
    BehavioralEvaluationError,
    configured_adapter_provenance,
    configured_deployment_provenance,
    local_corpus_provenance,
    runtime_evaluation_configuration,
)
from aica.util.canonical import sha256_value


class ControlledFoundryAdapter:
    """Live-labelled deterministic test double; production never selects this class."""

    closed = False
    calls = 0
    transient_failures = 0

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        *,
        max_output_tokens: int,
        managed_identity_client_id: str | None,
    ) -> None:
        del endpoint, max_output_tokens, managed_identity_client_id
        self.deployment = deployment
        self.delegate = ReplayModelAdapter()

    async def answer(self, question: str, citations: tuple[Citation, ...]) -> ModelAnswer:
        type(self).calls += 1
        if type(self).transient_failures:
            type(self).transient_failures -= 1
            request = httpx.Request("POST", "https://foundry.test.invalid/chat")
            response = httpx.Response(
                429,
                request=request,
                headers={"retry-after-ms": "0"},
            )
            raise httpx.HTTPStatusError(
                "controlled throttle",
                request=request,
                response=response,
            )
        replay = await self.delegate.answer(question, citations)
        return ModelAnswer(
            text=replay.text,
            model=self.deployment,
            version="controlled-live-test",
        )

    async def close(self) -> None:
        type(self).closed = True


def _settings(**updates: object) -> Settings:
    values: dict[str, object] = {
        "env": "test",
        "ai_evaluation_mode": "live",
        "ai_evaluation_dir": Path("data/ai-evaluations"),
        "policy_corpus_dir": Path("data/policy-corpus"),
        "model_adapter": "foundry",
        "model_deployment": "policy-gpt-test",
        "foundry_endpoint": "https://foundry.test.invalid",
        "deployed_configuration_url": "https://assistant.test.invalid/healthz",
        "confirmation_ttl_seconds": 7,
        "request_limit_per_user_per_hour": 4,
        "deployed_source_commit": "a" * 40,
        "assurance_api_image_sha256": "1" * 64,
        "assistant_ui_image_sha256": "2" * 64,
        "assurance_job_image_sha256": "3" * 64,
    }
    values.update(updates)
    return Settings(**values)


def _request(tmp_path: Path) -> CollectionRequest:
    now = datetime.now(UTC)
    return CollectionRequest(
        run_id="run-live-controlled-evaluation",
        observation_window_start=now - timedelta(hours=1),
        observation_window_end=now,
        scope=("synthetic-policy-assistant",),
        output_dir=tmp_path / "output",
    )


def _deployment(settings: Settings) -> dict[str, object]:
    provenance = configured_deployment_provenance(
        source_commit=settings.deployed_source_commit,
        assurance_api_image_sha256=settings.assurance_api_image_sha256,
        assistant_ui_image_sha256=settings.assistant_ui_image_sha256,
        assurance_job_image_sha256=settings.assurance_job_image_sha256,
        required=True,
    )
    assert provenance is not None
    return provenance


@pytest.mark.asyncio
async def test_live_mode_generates_ephemeral_result_and_binds_deployed_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    provenance = configured_adapter_provenance(
        kind="foundry",
        deployment=settings.model_deployment,
        endpoint=settings.foundry_endpoint,
    )
    configuration = runtime_evaluation_configuration(
        adapter=provenance,
        max_output_tokens=settings.model_max_output_tokens,
        confirmation_ttl_seconds=settings.confirmation_ttl_seconds,
        requests_per_user_hour=settings.request_limit_per_user_per_hour,
        corpus=local_corpus_provenance(settings.policy_corpus_dir),
        deployment=_deployment(settings),
    )
    digest = sha256_value(configuration)

    def deployed_configuration(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == settings.deployed_configuration_url
        return httpx.Response(
            200,
            json={"evaluation_configuration_sha256": digest},
        )

    monkeypatch.setattr("aica.collectors.ai.FoundryModelAdapter", ControlledFoundryAdapter)
    ControlledFoundryAdapter.closed = False
    ControlledFoundryAdapter.calls = 0
    ControlledFoundryAdapter.transient_failures = 0
    evidence = await AiEvaluationCollector(
        settings.ai_evaluation_dir,
        settings=settings,
        http_transport=httpx.MockTransport(deployed_configuration),
    ).collect(_request(tmp_path))

    behavioral, release = evidence
    generated = tmp_path / "output" / "controlled-ai" / "live-results.json"
    assert generated.is_file()
    assert behavioral.raw_payload["evaluation_mode"] == "LIVE"
    assert behavioral.raw_payload["runtime"]["selected_model_result_count"] > 0
    assert behavioral.raw_payload["runtime"]["confirmation_ttl_seconds"] == 7
    assert behavioral.raw_payload["runtime"]["requests_per_user_hour"] == 4
    gate = release.raw_payload["nodes"][0]
    assert gate["evaluation_gate_status"] == "PASS"
    assert gate["evaluated_configuration_sha256"] == digest
    assert gate["deployed_configuration_sha256"] == digest
    assert ControlledFoundryAdapter.closed is True


@pytest.mark.asyncio
async def test_live_mode_retries_throttling_without_replay_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    configuration = runtime_evaluation_configuration(
        adapter=configured_adapter_provenance(
            kind="foundry",
            deployment=settings.model_deployment,
            endpoint=settings.foundry_endpoint,
        ),
        max_output_tokens=settings.model_max_output_tokens,
        confirmation_ttl_seconds=settings.confirmation_ttl_seconds,
        requests_per_user_hour=settings.request_limit_per_user_per_hour,
        corpus=local_corpus_provenance(settings.policy_corpus_dir),
        deployment=_deployment(settings),
    )
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"evaluation_configuration_sha256": sha256_value(configuration)},
        )
    )
    monkeypatch.setattr("aica.collectors.ai.FoundryModelAdapter", ControlledFoundryAdapter)
    ControlledFoundryAdapter.calls = 0
    ControlledFoundryAdapter.transient_failures = 1

    behavioral, release = await AiEvaluationCollector(
        settings.ai_evaluation_dir,
        settings=settings,
        http_transport=transport,
    ).collect(_request(tmp_path))

    assert (
        ControlledFoundryAdapter.calls
        > behavioral.raw_payload["runtime"]["selected_model_result_count"]
    )
    assert ControlledFoundryAdapter.transient_failures == 0
    assert (
        "policy-gpt-test@controlled-live-test"
        in behavioral.raw_payload["runtime"]["models_observed"]
    )
    assert release.raw_payload["nodes"][0]["evaluation_gate_status"] == "PASS"


@pytest.mark.asyncio
async def test_live_mode_never_falls_back_when_deployed_digest_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(deployed_configuration_url=None)
    monkeypatch.setattr("aica.collectors.ai.FoundryModelAdapter", ControlledFoundryAdapter)
    ControlledFoundryAdapter.closed = False
    ControlledFoundryAdapter.transient_failures = 0

    with pytest.raises(
        BehavioralEvaluationError,
        match="live evaluation requires AICA_DEPLOYED_CONFIGURATION_URL",
    ):
        await AiEvaluationCollector(
            settings.ai_evaluation_dir,
            settings=settings,
        ).collect(_request(tmp_path))

    assert not (tmp_path / "output" / "controlled-ai" / "live-results.json").exists()
    assert ControlledFoundryAdapter.closed is True


@pytest.mark.asyncio
async def test_production_live_mode_requires_deployment_provenance_before_inference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(
        env="production",
        deployed_source_commit="",
        assurance_api_image_sha256="",
        assistant_ui_image_sha256="",
        assurance_job_image_sha256="",
    )
    monkeypatch.setattr("aica.collectors.ai.FoundryModelAdapter", ControlledFoundryAdapter)
    ControlledFoundryAdapter.calls = 0

    with pytest.raises(
        BehavioralEvaluationError,
        match="requires exact deployed source and image provenance",
    ):
        await AiEvaluationCollector(
            settings.ai_evaluation_dir,
            settings=settings,
        ).collect(_request(tmp_path))

    assert ControlledFoundryAdapter.calls == 0
    assert not (tmp_path / "output" / "controlled-ai" / "live-results.json").exists()


@pytest.mark.asyncio
async def test_live_mode_preserves_configuration_mismatch_as_release_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings()
    monkeypatch.setattr("aica.collectors.ai.FoundryModelAdapter", ControlledFoundryAdapter)
    ControlledFoundryAdapter.transient_failures = 0
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"evaluation_configuration_sha256": "0" * 64},
        )
    )

    _, release = await AiEvaluationCollector(
        settings.ai_evaluation_dir,
        settings=settings,
        http_transport=transport,
    ).collect(_request(tmp_path))

    gate = release.raw_payload["nodes"][0]
    assert gate["evaluation_gate_status"] == "FAIL"
    assert gate["deployed_configuration_sha256"] == "0" * 64
    assert gate["evaluated_configuration_sha256"] != "0" * 64


@pytest.mark.asyncio
async def test_explicit_replay_mode_ignores_a_stale_live_file(tmp_path: Path) -> None:
    root = tmp_path / "ai-evaluations"
    root.mkdir()
    for name in ("behavioral-cases.json", "replay-results.json"):
        (root / name).write_bytes((Path("data/ai-evaluations") / name).read_bytes())
    (root / "live-results.json").write_text("not valid JSON", encoding="utf-8")
    settings = _settings(ai_evaluation_dir=root, ai_evaluation_mode="replay")

    behavioral, release = await AiEvaluationCollector(root, settings=settings).collect(
        _request(tmp_path)
    )

    assert behavioral.raw_payload["evaluation_mode"] == "REPLAY"
    assert release.raw_payload["nodes"][0]["evaluation_gate_status"] == "FAIL"
