"""Checked, deterministic AI evaluation artifacts used by CI and release gates."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import httpx

from aica.assistant.adapters import (
    FoundryModelAdapter,
    ModelAdapter,
    ModelAnswer,
    PhiModelAdapter,
)
from aica.assistant.contracts import Citation
from aica.collectors.base import CollectedEvidence, CollectionRequest, envelope
from aica.config import Settings
from aica.domain.models import Classification
from aica.evaluation.behavioral import (
    FOUNDRY_ADAPTER_VERSION,
    PHI_ADAPTER_VERSION,
    BehavioralEvaluationError,
    EvaluationAdapter,
    configured_adapter_provenance,
    configured_deployment_provenance,
    load_behavioral_result,
    local_corpus_provenance,
    run_behavioral_evaluation,
    runtime_evaluation_configuration,
    write_behavioral_result,
)
from aica.util.canonical import sha256_value

MAPPING_METRICS = (
    "precision",
    "recall",
    "f1",
    "citation_validity",
    "abstention_f1",
    "reviewer_rejection_rate",
)


def load_mapping_metrics(path: Path) -> dict[str, float]:
    """Load only the measured, public-safe mapping metrics used by the Console."""

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        measured = document["measured_results"]
        metrics = {name: float(measured[name]) for name in MAPPING_METRICS}
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BehavioralEvaluationError(
            "mapping benchmark metrics are unavailable or invalid"
        ) from exc
    if any(value < 0 or value > 1 for value in metrics.values()):
        raise BehavioralEvaluationError("mapping benchmark metrics must be between zero and one")
    return metrics


def load_mapping_suggestion(path: Path, *, run_id: str, evaluation_id: str) -> dict[str, Any]:
    """Bind one reviewable mapping candidate to the current signed assessment run."""

    try:
        template = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BehavioralEvaluationError(
            "mapping suggestion template is unavailable or invalid"
        ) from exc
    expected_keys = {
        "schema_version",
        "template_id",
        "text",
        "suggested_control_ids",
        "case_ids",
        "provenance",
    }
    if not isinstance(template, dict) or set(template) != expected_keys:
        raise BehavioralEvaluationError("mapping suggestion template has an unexpected shape")
    if template.get("schema_version") != "1.0.0":
        raise BehavioralEvaluationError("mapping suggestion template version is unsupported")
    template_id = template.get("template_id")
    text = template.get("text")
    controls = template.get("suggested_control_ids")
    case_ids = template.get("case_ids")
    provenance = template.get("provenance")
    if (
        not isinstance(template_id, str)
        or not template_id
        or not isinstance(text, str)
        or len(text) < 20
        or not isinstance(controls, list)
        or not controls
        or not all(isinstance(value, str) and value for value in controls)
        or not isinstance(case_ids, list)
        or not case_ids
        or not all(isinstance(value, str) and value for value in case_ids)
        or not isinstance(provenance, dict)
        or set(provenance) != {"name", "version"}
        or not all(isinstance(value, str) and value for value in provenance.values())
    ):
        raise BehavioralEvaluationError("mapping suggestion template fields are invalid")
    return {
        "id": f"{template_id}:{run_id}",
        "artifact_run_id": run_id,
        "evaluation_id": evaluation_id,
        "text": text,
        "state": "SUGGESTED",
        "review_version": 0,
        "suggested_control_ids": controls,
        "case_ids": case_ids,
        "provenance": provenance,
    }


def compose_behavioral_evidence_payload(
    *,
    cases: dict[str, Any],
    results: dict[str, Any],
    mapping_metrics: dict[str, float],
    suggested_mapping: dict[str, Any] | None,
    baseline_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Project a content-minimized evaluation read model into signed evidence."""

    result_by_id = cast(dict[str, dict[str, Any]], results["results"])
    baseline_by_id = baseline_by_id or {}
    nodes: list[dict[str, Any]] = []
    for item in cases.get("cases", []):
        case_id = str(item["id"])
        actual = result_by_id[case_id]
        baseline = baseline_by_id.get(case_id)
        nodes.append(
            {
                "id": case_id,
                "category": item["category"],
                "control_ids": item.get("controls", []),
                "prompt_sha256": actual["prompt_sha256"],
                "response_sha256": actual.get("response_sha256"),
                "passed": actual["passed"],
                "baseline_result": (
                    "PASS"
                    if baseline and baseline.get("passed") is True
                    else "FAIL"
                    if baseline
                    else "NOT_RUN"
                ),
                "citation_valid": actual["citation_valid"],
                "disposition": actual["disposition"],
                "tool_execution": actual["tool_execution"],
                "scenario_valid": actual["scenario_valid"],
                "retrieved_documents": actual["retrieved_documents"],
                "tool_calls": actual["tool_calls"],
                "guardrail_outcomes": actual["guardrail_outcomes"],
                "correlation_id": actual.get("correlation_id"),
                "interaction_evaluation_id": actual.get("interaction_evaluation_id"),
                "latency_ms": actual.get("latency_ms"),
                "model": actual.get("model"),
                "model_version": actual.get("model_version"),
            }
        )
    return {
        "schema_version": "1.0.0",
        "evaluation_id": results["evaluation_id"],
        "dataset_id": results["dataset_id"],
        "dataset_version": results["dataset_version"],
        "evaluated_at": results["evaluated_at"],
        "configuration_sha256": results["configuration_sha256"],
        "evaluation_mode": results["execution_mode"],
        "adapter": results["adapter"],
        "evaluator": results["evaluator"],
        "runtime": results["runtime"],
        "summary": results["summary"],
        "mapping_metrics": mapping_metrics,
        "suggested_mapping": suggested_mapping,
        "nodes": nodes,
    }


class _RetryingLiveModelAdapter:
    """Retry bounded transient inference failures without substituting replay output."""

    def __init__(self, delegate: ModelAdapter, *, max_attempts: int = 6):
        self.delegate = delegate
        self.max_attempts = max_attempts

    @staticmethod
    def _delay(response: httpx.Response, attempt: int) -> float:
        retry_after_ms = response.headers.get("retry-after-ms")
        retry_after = response.headers.get("retry-after")
        try:
            if retry_after_ms is not None:
                delay = float(retry_after_ms) / 1000.0
                return min(max(delay, 0.0), 60.0)
            if retry_after is not None:
                delay = float(retry_after)
                return min(max(delay, 0.0), 60.0)
        except ValueError:
            pass
        return float(min(2**attempt, 30))

    async def answer(self, question: str, citations: tuple[Citation, ...]) -> ModelAnswer:
        for attempt in range(self.max_attempts):
            try:
                return await self.delegate.answer(question, citations)
            except httpx.HTTPStatusError as exc:
                transient = exc.response.status_code == 429 or exc.response.status_code >= 500
                if not transient or attempt + 1 == self.max_attempts:
                    raise
                await asyncio.sleep(self._delay(exc.response, attempt))
        raise AssertionError("unreachable live-model retry state")


class AiEvaluationCollector:
    name = "ai"
    version = "3.1.0"

    def __init__(
        self,
        root: Path,
        *,
        settings: Settings | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.root = root
        self.settings = settings
        self.http_transport = http_transport

    def _read(self, name: str) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            json.loads((self.root / name).read_text(encoding="utf-8")),
        )

    async def _deployed_configuration_sha256(self) -> str:
        settings = self.settings
        if settings is None or not settings.deployed_configuration_url:
            raise BehavioralEvaluationError(
                "live evaluation requires AICA_DEPLOYED_CONFIGURATION_URL"
            )
        parsed = urlparse(settings.deployed_configuration_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path != "/healthz"
            or parsed.query
            or parsed.fragment
        ):
            raise BehavioralEvaluationError(
                "AICA_DEPLOYED_CONFIGURATION_URL must be an HTTPS /healthz URL without "
                "userinfo, query, or fragment"
            )
        try:
            async with httpx.AsyncClient(
                timeout=15,
                follow_redirects=False,
                transport=self.http_transport,
            ) as client:
                response = await client.get(settings.deployed_configuration_url)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise BehavioralEvaluationError(
                "cannot obtain the deployed evaluation configuration digest"
            ) from exc
        digest = body.get("evaluation_configuration_sha256") if isinstance(body, dict) else None
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise BehavioralEvaluationError(
                "the deployed workload returned an invalid evaluation configuration digest"
            )
        return digest

    async def _generate_live_result(self, request: CollectionRequest) -> Path:
        settings = self.settings
        if settings is None:
            raise BehavioralEvaluationError("live evaluation requires runtime settings")
        if settings.model_adapter == "replay":
            raise BehavioralEvaluationError(
                "live evaluation cannot use the deterministic replay adapter"
            )
        deployment_provenance = configured_deployment_provenance(
            source_commit=settings.deployed_source_commit,
            assurance_api_image_sha256=settings.assurance_api_image_sha256,
            assistant_ui_image_sha256=settings.assistant_ui_image_sha256,
            assurance_job_image_sha256=settings.assurance_job_image_sha256,
            required=settings.env == "production",
        )
        model: ModelAdapter
        if settings.model_adapter == "foundry":
            provenance = configured_adapter_provenance(
                kind="foundry",
                deployment=settings.model_deployment,
                endpoint=settings.foundry_endpoint,
            )
            model = FoundryModelAdapter(
                cast(str, settings.foundry_endpoint),
                settings.model_deployment,
                max_output_tokens=settings.model_max_output_tokens,
                managed_identity_client_id=(
                    settings.azure_client_id if settings.env == "production" else None
                ),
            )
            adapter = EvaluationAdapter(
                model=_RetryingLiveModelAdapter(model),
                kind="foundry",
                name="FoundryModelAdapter",
                version=FOUNDRY_ADAPTER_VERSION,
                deployment=settings.model_deployment,
                endpoint_sha256=provenance["endpoint_sha256"],
            )
        else:
            if (
                settings.env == "production"
                and not settings.phi_bearer_token
                and not settings.phi_token_scope
            ):
                raise BehavioralEvaluationError(
                    "live Phi evaluation requires AICA_PHI_TOKEN_SCOPE or a protected token"
                )
            provenance = configured_adapter_provenance(
                kind="phi",
                deployment="Phi-4-mini-instruct",
                endpoint=settings.phi_endpoint,
            )
            model = PhiModelAdapter(
                cast(str, settings.phi_endpoint),
                bearer_token=settings.phi_bearer_token,
                max_output_tokens=settings.model_max_output_tokens,
                managed_identity_client_id=(
                    settings.azure_client_id if settings.env == "production" else None
                ),
                token_scope=settings.phi_token_scope,
            )
            adapter = EvaluationAdapter(
                model=_RetryingLiveModelAdapter(model),
                kind="phi",
                name="PhiModelAdapter",
                version=PHI_ADAPTER_VERSION,
                deployment="Phi-4-mini-instruct",
                endpoint_sha256=provenance["endpoint_sha256"],
            )
        configuration = runtime_evaluation_configuration(
            adapter=provenance,
            max_output_tokens=settings.model_max_output_tokens,
            confirmation_ttl_seconds=settings.confirmation_ttl_seconds,
            requests_per_user_hour=settings.request_limit_per_user_per_hour,
            corpus=local_corpus_provenance(settings.policy_corpus_dir),
            deployment=deployment_provenance,
        )
        try:
            deployed_digest = await self._deployed_configuration_sha256()
            artifact = await run_behavioral_evaluation(
                cases_path=self.root / "behavioral-cases.json",
                corpus_dir=settings.policy_corpus_dir,
                controlled_fixtures_path=self.root / "controlled-fixtures.json",
                configuration=configuration,
                configuration_source="generated-runtime-configuration",
                adapter=adapter,
                deployed_configuration_sha256=deployed_digest,
            )
        finally:
            if isinstance(model, (FoundryModelAdapter, PhiModelAdapter)):
                await model.close()
        destination = request.output_dir / "controlled-ai" / "live-results.json"
        write_behavioral_result(destination, artifact)
        return destination

    async def collect(self, request: CollectionRequest) -> list[CollectedEvidence]:
        cases = self._read("behavioral-cases.json")
        mode = self.settings.ai_evaluation_mode if self.settings is not None else "auto"
        if mode == "live":
            result_path = await self._generate_live_result(request)
        elif mode == "replay":
            result_path = self.root / "replay-results.json"
        else:
            result_path = (
                self.root / "live-results.json"
                if (self.root / "live-results.json").is_file()
                else self.root / "replay-results.json"
            )
        results = load_behavioral_result(self.root / "behavioral-cases.json", result_path)
        evaluated_digest = str(results["configuration_sha256"])
        evaluated_at = datetime.fromisoformat(str(results["evaluated_at"]).replace("Z", "+00:00"))
        adapter = cast(dict[str, Any], results["adapter"])
        runtime = cast(dict[str, Any], results["runtime"])
        live = (
            results["execution_mode"] == "LIVE"
            and adapter["kind"] in {"foundry", "phi"}
            and int(runtime["selected_model_result_count"]) > 0
        )
        deployed_digest = results.get("deployed_configuration_sha256")
        summary = cast(dict[str, Any], results["summary"])
        baseline_by_id: dict[str, dict[str, Any]] = {}
        baseline_path = (
            self.root.parent / "collector-fixtures/baseline/ai.behavioral_evaluation.json"
        )
        if baseline_path.is_file():
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
            baseline_by_id = {
                str(item["id"]): item for item in baseline.get("payload", {}).get("nodes", [])
            }
        mapping_path = (
            self.settings.mapping_benchmark_path
            if self.settings is not None
            else Path("data/mapping-benchmark/human-labeled-examples.json")
        )
        suggestion_path = (
            self.settings.mapping_suggestion_path
            if self.settings is not None
            else Path("data/ai-evaluations/mapping-suggestion.json")
        )
        suggested_mapping = load_mapping_suggestion(
            suggestion_path,
            run_id=request.run_id,
            evaluation_id=str(results["evaluation_id"]),
        )
        behavioral_payload = compose_behavioral_evidence_payload(
            cases=cases,
            results=results,
            mapping_metrics=load_mapping_metrics(mapping_path),
            suggested_mapping=suggested_mapping,
            baseline_by_id=baseline_by_id,
        )
        behavioral = envelope(
            request=request,
            source="ai.behavioral_evaluation",
            collector_version=self.version,
            query={
                "dataset_id": cases.get("dataset_id"),
                "dataset_version": cases.get("version"),
                "evaluation_id": results["evaluation_id"],
                "adapter": adapter["name"],
                "evaluation_mode": "LIVE" if live else "REPLAY",
            },
            raw_payload=behavioral_payload,
            classification=Classification.RESTRICTED_TEST_EVIDENCE,
            captured_at=evaluated_at,
        )
        release = envelope(
            request=request,
            source="ai.release_evaluation",
            collector_version=self.version,
            query={
                "configuration_source": cast(dict[str, Any], results["configuration"])["source"],
                "evaluation_id": results["evaluation_id"],
            },
            raw_payload={
                "nodes": [
                    {
                        "evaluation_gate_status": (
                            "PASS"
                            if live
                            and summary["passed"] == summary["cases"]
                            and deployed_digest is not None
                            and deployed_digest == evaluated_digest
                            else "FAIL"
                        ),
                        "evaluation_artifact_sha256": sha256_value(results),
                        "evaluated_configuration_sha256": evaluated_digest,
                        "deployed_configuration_sha256": deployed_digest,
                        "evaluation_mode": "LIVE" if live else "REPLAY",
                    }
                ]
            },
            classification=Classification.INTERNAL,
            captured_at=evaluated_at,
        )
        return [behavioral, release]
