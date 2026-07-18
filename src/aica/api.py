"""FastAPI read model and append-only command surface."""

import base64
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, cast

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from aica.api_store import (
    AzureBlobRunStore,
    CompositeRunStore,
    PackageIntegrityError,
    PackageNotFoundError,
    RunStore,
)
from aica.assistant.adapters import (
    FoundryModelAdapter,
    ModelAdapter,
    PhiModelAdapter,
    ReplayModelAdapter,
    ResilientModelAdapter,
)
from aica.assistant.contracts import ChatRequest, ChatResponse
from aica.assistant.retrieval import PolicyIndex
from aica.assistant.service import (
    AzureTableSlidingWindowRateLimiter,
    PolicyAssistantService,
    RateLimitExceeded,
)
from aica.commands import AzureTableCommandQueue, Command, CommandQueue, LocalCommandQueue
from aica.config import Settings, get_settings
from aica.evaluation.behavioral import (
    configured_adapter_provenance,
    configured_deployment_provenance,
    runtime_evaluation_configuration,
)
from aica.evaluation.diff import diff_packages
from aica.evidence.redaction import sanitize
from aica.observability import configure_azure_observability
from aica.review_store import (
    AzureTableReviewEventStore,
    EmptyReviewEventStore,
    ReviewEventStore,
    overlay_review_events,
)
from aica.telemetry import LogsIngestionPublisher
from aica.util.canonical import sha256_value


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunRequest(StrictInput):
    profile: str = "azure-dev"
    reason: str = Field(min_length=8, max_length=500)


class RetestRequest(StrictInput):
    prior_run_id: str
    finding_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=8, max_length=500)


class ReviewDecisionInput(StrictInput):
    subject_type: Literal["CONTROL", "FINDING", "RISK", "AI_SUGGESTION"]
    subject_id: str
    artifact_run_id: str
    prior_state: str
    decision: str
    rationale: str = Field(min_length=12, max_length=2_000)
    expected_version: int = Field(ge=0)


class ExceptionInput(StrictInput):
    finding_id: str
    artifact_run_id: str
    rationale: str = Field(min_length=12, max_length=2_000)
    compensating_controls: list[str] = Field(min_length=1)
    expires_at: str
    review_cadence: str
    expected_version: int = Field(ge=0)


class RemediationInput(StrictInput):
    finding_id: str = Field(min_length=1)
    artifact_run_id: str = Field(min_length=1)
    owner: str = Field(min_length=2, max_length=200)
    action: str = Field(min_length=12, max_length=2_000)
    target_date: datetime
    commit_or_pr: str = Field(min_length=1, max_length=500)
    evidence_refs: list[Annotated[str, Field(min_length=1)]] = Field(min_length=1)
    expected_version: int = Field(ge=0)


@dataclass(frozen=True)
class Actor:
    subject: str
    roles: frozenset[str]


def _evaluation_summary_from_package(package: dict[str, Any], requested_id: str) -> dict[str, Any]:
    """Project AI evidence only after its containing assessment package is verified."""

    run = cast(dict[str, Any], package.get("run", {}))
    run_id = str(run.get("id", ""))
    candidate: dict[str, Any] | None = None
    for evidence in package.get("evidence", []):
        source = "".join(
            character
            for character in str(evidence.get("source", "")).lower()
            if character.isalnum()
        )
        if source != "aibehavioralevaluation":
            continue
        payload = evidence.get("payload")
        if not isinstance(payload, dict):
            continue
        if requested_id in {
            run_id,
            str(payload.get("evaluation_id", "")),
            str(payload.get("dataset_id", "")),
        }:
            candidate = payload
            break
    if candidate is None:
        raise PackageNotFoundError(
            f"signed run {run_id or 'unknown'} does not contain evaluation {requested_id}"
        )

    nodes = candidate.get("nodes")
    summary = candidate.get("summary")
    adapter = candidate.get("adapter")
    evaluator = candidate.get("evaluator")
    metrics = candidate.get("mapping_metrics")
    if not all(isinstance(value, dict) for value in (summary, adapter, evaluator, metrics)):
        raise PackageIntegrityError("signed AI evaluation summary metadata is incomplete")
    if not isinstance(nodes, list):
        raise PackageIntegrityError("signed AI evaluation cases are unavailable")
    summary = cast(dict[str, Any], summary)
    adapter = cast(dict[str, Any], adapter)
    evaluator = cast(dict[str, Any], evaluator)
    metrics = cast(dict[str, Any], metrics)

    category_map = {
        "grounded_answer": "Grounding",
        "citation_integrity": "Grounding",
        "service_fault": "Grounding",
        "indirect_prompt_injection": "Prompt injection",
        "direct_prompt_injection": "Prompt injection",
        "content_filter": "Prompt injection",
        "release_gate": "Tool authorization",
        "tool_authorization": "Tool authorization",
        "rate_limit": "Tool authorization",
        "sensitive_data": "Data handling",
        "telemetry_contract": "Data handling",
        "scope_control": "Abstention",
        "policy_conflict": "Abstention",
        "stale_policy": "Abstention",
    }
    result_cases: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise PackageIntegrityError("signed AI evaluation contains a malformed case")
        disposition = str(node.get("disposition", ""))
        tool_calls = node.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            raise PackageIntegrityError("signed AI evaluation contains malformed tool observations")
        prompt_digest = str(node.get("prompt_sha256", ""))
        if len(prompt_digest) != 64 or any(
            value not in "0123456789abcdef" for value in prompt_digest
        ):
            raise PackageIntegrityError("signed AI evaluation contains an invalid input digest")
        latency = node.get("latency_ms")
        if not isinstance(latency, (int, float)) or latency < 0:
            raise PackageIntegrityError(
                "signed AI evaluation contains an invalid latency observation"
            )
        result_cases.append(
            {
                "id": str(node.get("id", "")),
                "category": category_map.get(str(node.get("category", "")), "Grounding"),
                "inputSha256": prompt_digest,
                "result": "PASS" if node.get("passed") is True else "FAIL",
                "baselineResult": str(node.get("baseline_result", "NOT_RUN")),
                "guardrail": (
                    "ABSTAINED"
                    if disposition == "CLARIFY"
                    else "BLOCKED"
                    if disposition in {"REFUSE", "WARN_AND_ANSWER", "REQUEST_CONFIRMATION"}
                    else "ALLOWED"
                ),
                "responseSha256": node.get("response_sha256"),
                "retrievedDocuments": node.get("retrieved_documents", []),
                "toolCalls": [
                    str(item.get("name", "")) for item in tool_calls if isinstance(item, dict)
                ],
                "toolObservations": tool_calls,
                "controlIds": node.get("control_ids", []),
                "correlationId": node.get("correlation_id"),
                "interactionEvaluationId": node.get("interaction_evaluation_id"),
                "latencyMs": latency,
                "model": node.get("model"),
                "modelVersion": node.get("model_version"),
                "guardrailOutcomes": node.get("guardrail_outcomes", []),
            }
        )

    suggestion = candidate.get("suggested_mapping")
    suggested_mapping: dict[str, Any] | None = None
    if suggestion is not None:
        if not isinstance(suggestion, dict) or suggestion.get("artifact_run_id") != run_id:
            raise PackageIntegrityError("AI mapping suggestion is not bound to the signed run")
        suggestion_id = str(suggestion.get("id", ""))
        state = str(suggestion.get("state", "SUGGESTED"))
        version = int(suggestion.get("review_version", 0))
        decisions = sorted(
            (
                item
                for item in package.get("decisions", [])
                if item.get("subject_type") == "AI_SUGGESTION"
                and item.get("subject_id") == suggestion_id
            ),
            key=lambda item: int(item.get("version", 0)),
        )
        if decisions:
            latest = decisions[-1]
            decision = str(latest.get("decision", "")).upper()
            if decision in {"ACCEPT", "ACCEPTED"}:
                state = "ACCEPTED"
            elif decision in {"REJECT", "REJECTED"}:
                state = "REJECTED"
            version = int(latest.get("version", version))
        if state not in {"SUGGESTED", "ACCEPTED", "REJECTED"}:
            raise PackageIntegrityError("AI mapping suggestion has an invalid review state")
        suggested_mapping = {
            "id": suggestion_id,
            "text": str(suggestion.get("text", "")),
            "state": state,
            "reviewVersion": version,
        }

    response = {
        "id": candidate.get("evaluation_id"),
        "datasetId": candidate.get("dataset_id"),
        "model": adapter.get("name"),
        "adapterProvenance": adapter,
        "evaluatorProvenance": evaluator,
        "executionMode": candidate.get("evaluation_mode"),
        "promptVersion": f"sha256:{candidate.get('configuration_sha256')}",
        "configurationSha256": candidate.get("configuration_sha256"),
        "datasetVersion": candidate.get("dataset_version"),
        "createdAt": candidate.get("evaluated_at"),
        "total": summary.get("cases"),
        "passed": summary.get("passed"),
        "precision": metrics.get("precision"),
        "recall": metrics.get("recall"),
        "f1": metrics.get("f1"),
        "citationValidity": metrics.get("citation_validity"),
        "abstentionQuality": metrics.get("abstention_f1"),
        "reviewerRejectionRate": metrics.get("reviewer_rejection_rate"),
        "cases": result_cases,
    }
    if suggested_mapping is not None:
        response["suggestedMapping"] = suggested_mapping
    return response


def _decode_client_principal(value: str | None) -> tuple[str | None, frozenset[str]]:
    if not value:
        return None, frozenset()
    try:
        padding = "=" * (-len(value) % 4)
        payload = json.loads(base64.b64decode(value + padding))
        claims = payload.get("claims", [])
        subject: str | None = None
        roles: set[str] = set()
        for claim in claims:
            claim_type = str(claim.get("typ", ""))
            claim_value = str(claim.get("val", ""))
            if claim_type in {"roles", "role"} or claim_type.endswith("/claims/role"):
                roles.add(claim_value)
            if claim_type.endswith("/claims/nameidentifier") or claim_type in {"sub", "oid"}:
                subject = claim_value
        return subject, frozenset(roles)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None, frozenset()


def _store(settings: Settings) -> RunStore:
    trusted_fingerprints = frozenset(
        value.strip()
        for value in settings.trusted_signing_key_fingerprints.split(",")
        if value.strip()
    )
    if settings.env == "production" and settings.assurance_enabled and not trusted_fingerprints:
        raise RuntimeError("AICA_TRUSTED_SIGNING_KEY_FINGERPRINTS is required in production")
    if settings.azure_blob_endpoint:
        container = (
            settings.azure_public_evidence_container
            if settings.public_mode
            else settings.azure_private_evidence_container
        )
        return AzureBlobRunStore(
            settings.azure_blob_endpoint,
            container,
            managed_identity_client_id=settings.azure_client_id,
            trusted_key_fingerprints=trusted_fingerprints,
            trusted_key_id_prefix=settings.trusted_signing_key_id_prefix,
        )
    roots = [settings.artifact_dir / "public", settings.data_dir]
    return CompositeRunStore(
        roots,
        trusted_key_fingerprints=trusted_fingerprints,
        trusted_key_id_prefix=settings.trusted_signing_key_id_prefix,
    )


def _queue(settings: Settings) -> CommandQueue:
    if settings.azure_table_endpoint:
        return AzureTableCommandQueue(
            settings.azure_table_endpoint,
            settings.azure_command_table,
            managed_identity_client_id=settings.azure_client_id,
        )
    return LocalCommandQueue(settings.artifact_dir / "requests")


def _review_events(settings: Settings) -> ReviewEventStore:
    if settings.public_mode or not settings.azure_table_endpoint:
        return EmptyReviewEventStore()
    return AzureTableReviewEventStore(
        settings.azure_table_endpoint,
        settings.azure_review_table,
        managed_identity_client_id=settings.azure_client_id,
    )


def _artifact_hash_for_subject(
    repository: RunStore,
    *,
    run_id: str,
    subject_type: str,
    subject_id: str,
) -> str:
    package = repository.get_raw(run_id)
    run = package.get("run", package.get("assessment_run", {}))
    digest = str(run.get("manifest_digest", ""))
    if len(digest) != 64:
        raise PackageIntegrityError(f"run {run_id} has no verified manifest digest")
    if subject_type == "CONTROL":
        matched = any(
            subject_id in {str(item.get("id")), str(item.get("source_control"))}
            for item in package.get("objectives", [])
        )
    elif subject_type == "FINDING":
        matched = any(subject_id == str(item.get("id")) for item in package.get("findings", []))
    elif subject_type == "RISK":
        matched = any(subject_id == str(item.get("id")) for item in package.get("risks", []))
    elif subject_type == "AI_SUGGESTION":
        matched_decision = any(
            subject_id == str(item.get("subject_id"))
            and str(item.get("subject_type")) == "AI_SUGGESTION"
            for item in package.get("decisions", [])
        )
        matched_evidence = any(
            isinstance(item.get("payload"), dict)
            and isinstance(item["payload"].get("suggested_mapping"), dict)
            and subject_id == str(item["payload"]["suggested_mapping"].get("id"))
            and str(item["payload"]["suggested_mapping"].get("artifact_run_id")) == run_id
            for item in package.get("evidence", [])
        )
        matched = matched_decision or matched_evidence
    else:
        matched = False
    if not matched:
        raise PackageNotFoundError(
            f"signed run {run_id} does not contain {subject_type} {subject_id}"
        )
    return digest


def _validate_retest_targets(package: dict[str, Any], finding_ids: list[str]) -> None:
    available = {str(item.get("id")) for item in package.get("findings", [])}
    missing = sorted(set(finding_ids) - available)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"prior signed package does not contain findings: {', '.join(missing)}",
        )


def _validate_remediation_evidence(package: dict[str, Any], evidence_refs: list[str]) -> None:
    if len(set(evidence_refs)) != len(evidence_refs):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="remediation evidence references must be unique",
        )
    available = {str(item.get("id")) for item in package.get("evidence", [])}
    missing = sorted(set(evidence_refs) - available)
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"signed package does not contain remediation evidence: {', '.join(missing)}",
        )


def _validate_finding_disposition(
    package: dict[str, Any], *, finding_id: str, decision: str
) -> None:
    disposition = decision.upper()
    if disposition not in {"CLOSE", "CLOSED", "REOPEN", "REOPENED"}:
        return
    expected = "CLOSE" if disposition in {"CLOSE", "CLOSED"} else "REOPEN"
    candidates = [
        item
        for item in package.get("retests", [])
        if str(item.get("finding_id", item.get("finding_ref", ""))) == finding_id
        and str(item.get("decision", "")).upper() == expected
    ]
    supported = bool(candidates)
    if expected == "CLOSE":
        supported = any(
            str(item.get("result", "")).upper() == "PASS"
            and str(item.get("evidence_freshness", "")).upper() == "FRESH"
            and bool(item.get("evidence_refs", item.get("new_evidence_refs", [])))
            for item in candidates
        )
    if not supported:
        requirement = (
            "a fresh passing retest with evidence and a CLOSE recommendation"
            if expected == "CLOSE"
            else "a retest with a REOPEN recommendation"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"finding {finding_id} cannot be {expected.lower()}d without {requirement}",
        )


def _assistant(settings: Settings) -> PolicyAssistantService:
    if not settings.assistant_enabled:
        return PolicyAssistantService(
            index=PolicyIndex([]),
            model=ReplayModelAdapter(),
            pseudonymization_secret="assistant-capability-disabled",  # noqa: S106 -- inert
            requests_per_hour=1,
        )
    if settings.corpus_blob_endpoint:
        index = PolicyIndex.from_blob(
            settings.corpus_blob_endpoint,
            prefix=settings.corpus_blob_prefix,
            managed_identity_client_id=settings.azure_client_id,
        )
    elif settings.env == "production":
        raise RuntimeError("AICA_CORPUS_BLOB_ENDPOINT is required for the production assistant")
    elif (settings.policy_corpus_dir / "manifest.json").is_file():
        index = PolicyIndex.from_verified_directory(settings.policy_corpus_dir)
    else:
        index = PolicyIndex.from_directory(settings.policy_corpus_dir)
    model: ModelAdapter
    if settings.model_adapter == "foundry":
        if not settings.foundry_endpoint:
            raise RuntimeError("AICA_FOUNDRY_ENDPOINT is required for the Foundry adapter")
        model = ResilientModelAdapter(
            FoundryModelAdapter(
                settings.foundry_endpoint,
                settings.model_deployment,
                max_output_tokens=settings.model_max_output_tokens,
                managed_identity_client_id=(
                    settings.azure_client_id if settings.env == "production" else None
                ),
            ),
            name="foundry",
        )
    elif settings.model_adapter == "phi":
        if not settings.phi_endpoint:
            raise RuntimeError("AICA_PHI_ENDPOINT is required for the Phi adapter")
        if (
            settings.env == "production"
            and not settings.phi_bearer_token
            and not settings.phi_token_scope
        ):
            raise RuntimeError(
                "AICA_PHI_TOKEN_SCOPE is required for managed-identity Phi authentication"
            )
        model = ResilientModelAdapter(
            PhiModelAdapter(
                settings.phi_endpoint,
                bearer_token=settings.phi_bearer_token,
                max_output_tokens=settings.model_max_output_tokens,
                managed_identity_client_id=(
                    settings.azure_client_id if settings.env == "production" else None
                ),
                token_scope=settings.phi_token_scope,
            ),
            name="phi",
        )
    else:
        model = ReplayModelAdapter()
    telemetry = None
    if settings.sentinel_dcr_endpoint and settings.sentinel_dcr_immutable_id:
        telemetry = LogsIngestionPublisher(
            settings.sentinel_dcr_endpoint,
            settings.sentinel_dcr_immutable_id,
            managed_identity_client_id=settings.azure_client_id,
        )
    elif settings.env == "production":
        raise RuntimeError(
            "AICA_SENTINEL_DCR_ENDPOINT and AICA_SENTINEL_DCR_IMMUTABLE_ID are required"
        )
    rate_limiter = None
    if settings.env == "production":
        if not settings.azure_table_endpoint:
            raise RuntimeError("AICA_AZURE_TABLE_ENDPOINT is required for production rate limiting")
        rate_limiter = AzureTableSlidingWindowRateLimiter(
            settings.azure_table_endpoint,
            settings.azure_rate_limit_table,
            limit=settings.request_limit_per_user_per_hour,
            managed_identity_client_id=settings.azure_client_id,
        )
    return PolicyAssistantService(
        index=index,
        model=model,
        pseudonymization_secret=settings.pseudonymization_secret,
        requests_per_hour=settings.request_limit_per_user_per_hour,
        rate_limiter=rate_limiter,
        confirmation_ttl=timedelta(seconds=settings.confirmation_ttl_seconds),
        telemetry_sink=telemetry,
    )


def _effective_evaluation_configuration(
    settings: Settings, assistant: PolicyAssistantService
) -> dict[str, Any]:
    endpoint = (
        settings.foundry_endpoint
        if settings.model_adapter == "foundry"
        else settings.phi_endpoint
        if settings.model_adapter == "phi"
        else None
    )
    deployment = (
        settings.model_deployment if settings.model_adapter == "foundry" else "Phi-4-mini-instruct"
    )
    adapter_provenance = configured_adapter_provenance(
        kind=settings.model_adapter,
        deployment=deployment,
        endpoint=endpoint,
    )
    corpus_provenance = assistant.index.provenance
    corpus = (
        {
            "id": corpus_provenance.corpus_id,
            "version": corpus_provenance.version,
            "manifest_sha256": corpus_provenance.manifest_sha256,
            "document_count": corpus_provenance.document_count,
        }
        if corpus_provenance is not None
        else None
    )
    return runtime_evaluation_configuration(
        adapter=adapter_provenance,
        max_output_tokens=settings.model_max_output_tokens,
        confirmation_ttl_seconds=settings.confirmation_ttl_seconds,
        requests_per_user_hour=settings.request_limit_per_user_per_hour,
        corpus=corpus,
        deployment=configured_deployment_provenance(
            source_commit=settings.deployed_source_commit,
            assurance_api_image_sha256=settings.assurance_api_image_sha256,
            assistant_ui_image_sha256=settings.assistant_ui_image_sha256,
            assurance_job_image_sha256=settings.assurance_job_image_sha256,
            required=settings.env == "production",
        ),
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    if settings.assistant_enabled and settings.env == "production":
        configured_deployment_provenance(
            source_commit=settings.deployed_source_commit,
            assurance_api_image_sha256=settings.assurance_api_image_sha256,
            assistant_ui_image_sha256=settings.assistant_ui_image_sha256,
            assurance_job_image_sha256=settings.assurance_job_image_sha256,
            required=True,
        )
    configure_azure_observability()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        yield
        assistant = cast(PolicyAssistantService, application.state.assistant)
        sink = assistant.telemetry_sink
        if isinstance(sink, LogsIngestionPublisher):
            await sink.close()
        model = assistant.model
        if isinstance(model, ResilientModelAdapter):
            model = model.primary
        if isinstance(model, (FoundryModelAdapter, PhiModelAdapter)):
            await model.close()

    app = FastAPI(
        title="Azure AI Continuous Assurance API",
        version="0.1.0",
        description="Read evidence; append review and assessment commands. No automatic remediation.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = _store(settings)
    app.state.queue = _queue(settings)
    app.state.review_events = _review_events(settings)
    app.state.assistant = _assistant(settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:5174"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=[
            "Content-Type",
            "X-AICA-Reviewer",
            "X-AICA-Roles",
            "X-MS-CLIENT-PRINCIPAL",
            "X-MS-CLIENT-PRINCIPAL-ID",
        ],
    )

    @app.middleware("http")
    async def capability_boundary(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if path.startswith("/api/v1/assistant/") and not settings.assistant_enabled:
            return JSONResponse(
                status_code=404, content={"detail": "assistant interface is disabled"}
            )
        if (
            path.startswith("/api/v1/")
            and not path.startswith("/api/v1/assistant/")
            and not settings.assurance_enabled
        ):
            return JSONResponse(
                status_code=404, content={"detail": "assurance interface is disabled"}
            )
        return await call_next(request)

    def store(request: Request) -> RunStore:
        return cast(RunStore, request.app.state.store)

    def queue(request: Request) -> CommandQueue:
        return cast(CommandQueue, request.app.state.queue)

    def review_events(request: Request) -> ReviewEventStore:
        return cast(ReviewEventStore, request.app.state.review_events)

    def reviewed_package(
        repository: RunStore, event_store: ReviewEventStore, run_id: str
    ) -> dict[str, Any]:
        return overlay_review_events(repository.get_raw(run_id), event_store.list_events())

    def require_private(request: Request) -> None:
        if request.app.state.settings.public_mode:
            raise HTTPException(
                status_code=403, detail="command interfaces are disabled in public mode"
            )

    def actor_identity(
        request: Request,
        x_ms_client_principal_id: Annotated[str | None, Header()] = None,
        x_ms_client_principal: Annotated[str | None, Header()] = None,
        x_aica_reviewer: Annotated[str | None, Header()] = None,
        x_aica_roles: Annotated[str | None, Header()] = None,
    ) -> Actor:
        require_private(request)
        principal_subject, principal_roles = _decode_client_principal(x_ms_client_principal)
        identity = x_ms_client_principal_id or principal_subject
        roles = principal_roles
        if settings.env != "production":
            identity = identity or x_aica_reviewer
            if x_aica_roles:
                roles = frozenset(item.strip() for item in x_aica_roles.split(",") if item.strip())
        if not identity:
            raise HTTPException(
                status_code=401, detail="an authenticated reviewer identity is required"
            )
        return Actor(identity, roles)

    def require_roles(*allowed: str) -> Callable[..., Actor]:
        def dependency(actor: Annotated[Actor, Depends(actor_identity)]) -> Actor:
            if actor.roles.isdisjoint(allowed):
                raise HTTPException(
                    status_code=403, detail="the caller lacks the required app role"
                )
            return actor

        return dependency

    require_assessor = require_roles("Assurance.Assessor")
    require_reviewer = require_roles("Assurance.Reviewer", "Assurance.RiskApprover")
    require_risk_approver = require_roles("Assurance.RiskApprover")

    @app.exception_handler(PackageNotFoundError)
    async def not_found(_request: Request, exc: PackageNotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"assessment run not found: {exc}"})

    @app.exception_handler(PackageIntegrityError)
    async def integrity_error(_request: Request, exc: PackageIntegrityError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"detail": f"assessment integrity failure: {exc}"},
        )

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    @app.get("/healthz")
    def health(response: Response) -> dict[str, str]:
        response.headers["Cache-Control"] = "no-store"
        result = {
            "status": "healthy",
            "mode": "public" if settings.public_mode else "private",
        }
        if settings.assistant_enabled:
            assistant = cast(PolicyAssistantService, app.state.assistant)
            result["evaluation_configuration_sha256"] = sha256_value(
                _effective_evaluation_configuration(settings, assistant)
            )
        return result

    @app.get("/api/v1/runs")
    def runs(repository: Annotated[RunStore, Depends(store)]) -> list[dict[str, Any]]:
        return repository.list_runs_raw()

    @app.get("/api/v1/runs/{run_id}")
    def run(
        run_id: str,
        repository: Annotated[RunStore, Depends(store)],
        event_store: Annotated[ReviewEventStore, Depends(review_events)],
    ) -> dict[str, Any]:
        package = reviewed_package(repository, event_store, run_id)
        return sanitize(package) if settings.public_mode else package

    @app.get("/api/v1/runs/{run_id}/controls")
    def run_controls(
        run_id: str,
        repository: Annotated[RunStore, Depends(store)],
        event_store: Annotated[ReviewEventStore, Depends(review_events)],
    ) -> Any:
        package = reviewed_package(repository, event_store, run_id)
        return package.get("assessments", package.get("control_assessments", []))

    @app.get("/api/v1/controls/{control_id}")
    def control(
        control_id: str,
        run_id: Annotated[str, Query()],
        repository: Annotated[RunStore, Depends(store)],
        event_store: Annotated[ReviewEventStore, Depends(review_events)],
    ) -> dict[str, Any]:
        package = reviewed_package(repository, event_store, run_id)
        objectives = package.get("objectives", package.get("control_objectives", []))
        results = package.get("test_results", [])
        assessments = package.get("assessments", package.get("control_assessments", []))
        matches = [
            item
            for item in objectives
            if item.get("id") == control_id or item.get("source_control") == control_id
        ]
        if not matches:
            raise HTTPException(status_code=404, detail="control was not assessed in this run")
        objective_ids = {item["id"] for item in matches}
        return {
            "objectives": matches,
            "test_results": [item for item in results if item.get("objective_id") in objective_ids],
            "assessments": [
                item for item in assessments if item.get("objective_id") in objective_ids
            ],
        }

    @app.get("/api/v1/evidence/{sha256}/metadata")
    def evidence_metadata(
        sha256: str, repository: Annotated[RunStore, Depends(store)]
    ) -> dict[str, Any]:
        for run_summary in repository.list_runs_raw():
            run_id = str(run_summary.get("id", run_summary.get("run_id")))
            package = repository.get_raw(run_id)
            for item in package.get("evidence", []):
                if item.get("sha256") == sha256 or item.get("sanitized_sha256") == sha256:
                    result = dict(item)
                    result.pop("payload", None)
                    if settings.public_mode:
                        result["private_artifact_uri"] = "private://withheld"
                        result.pop("blob_version", None)
                    return sanitize(result) if settings.public_mode else result
        raise HTTPException(status_code=404, detail="evidence digest not found")

    def _latest_collection(
        key: str, repository: RunStore, event_store: ReviewEventStore
    ) -> list[dict[str, Any]]:
        package = repository.latest_raw()
        reviewed = overlay_review_events(package, event_store.list_events())
        return cast(list[dict[str, Any]], reviewed.get(key, []))

    @app.get("/api/v1/findings")
    def findings(
        repository: Annotated[RunStore, Depends(store)],
        event_store: Annotated[ReviewEventStore, Depends(review_events)],
    ) -> list[dict[str, Any]]:
        return _latest_collection("findings", repository, event_store)

    @app.get("/api/v1/risks")
    def risks(
        repository: Annotated[RunStore, Depends(store)],
        event_store: Annotated[ReviewEventStore, Depends(review_events)],
    ) -> list[dict[str, Any]]:
        return _latest_collection("risks", repository, event_store)

    @app.get("/api/v1/evaluations/{evaluation_id}")
    def evaluation(
        evaluation_id: str,
        repository: Annotated[RunStore, Depends(store)],
        event_store: Annotated[ReviewEventStore, Depends(review_events)],
        run_id: Annotated[str | None, Query()] = None,
    ) -> dict[str, Any]:
        if run_id is not None:
            package = reviewed_package(repository, event_store, run_id)
            summary = _evaluation_summary_from_package(package, evaluation_id)
            return cast(dict[str, Any], sanitize(summary) if settings.public_mode else summary)

        # The Console passes its selected signed run ID. Exact evaluation IDs remain
        # supported for API clients, but are resolved only inside verified packages.
        try:
            package = reviewed_package(repository, event_store, evaluation_id)
            summary = _evaluation_summary_from_package(package, evaluation_id)
            return cast(dict[str, Any], sanitize(summary) if settings.public_mode else summary)
        except PackageNotFoundError:
            pass
        for run in repository.list_runs_raw():
            candidate_run_id = str(run.get("id", run.get("run_id", "")))
            if not candidate_run_id:
                continue
            package = reviewed_package(repository, event_store, candidate_run_id)
            try:
                summary = _evaluation_summary_from_package(package, evaluation_id)
            except PackageNotFoundError:
                continue
            return cast(dict[str, Any], sanitize(summary) if settings.public_mode else summary)
        raise PackageNotFoundError(f"evaluation {evaluation_id} was not found in a signed run")

    @app.get("/api/v1/diffs")
    def diffs(
        from_run: Annotated[str, Query(alias="from")],
        to_run: Annotated[str, Query(alias="to")],
        repository: Annotated[RunStore, Depends(store)],
    ) -> Any:
        return diff_packages(repository.get(from_run), repository.get(to_run))

    @app.post("/api/v1/run-requests", response_model=Command, status_code=status.HTTP_202_ACCEPTED)
    def request_run(
        body: RunRequest,
        request: Request,
        actor: Annotated[Actor, Depends(require_assessor)],
        command_queue: Annotated[CommandQueue, Depends(queue)],
    ) -> Command:
        require_private(request)
        return command_queue.enqueue("RUN_ASSESSMENT", actor.subject, body.model_dump())

    @app.post(
        "/api/v1/retest-requests", response_model=Command, status_code=status.HTTP_202_ACCEPTED
    )
    def request_retest(
        body: RetestRequest,
        request: Request,
        actor: Annotated[Actor, Depends(require_assessor)],
        command_queue: Annotated[CommandQueue, Depends(queue)],
        repository: Annotated[RunStore, Depends(store)],
    ) -> Command:
        require_private(request)
        prior_package = repository.get_raw(body.prior_run_id)
        _validate_retest_targets(prior_package, body.finding_ids)
        return command_queue.enqueue("RUN_RETEST", actor.subject, body.model_dump())

    @app.post(
        "/api/v1/review-decisions", response_model=Command, status_code=status.HTTP_202_ACCEPTED
    )
    def review_decision(
        body: ReviewDecisionInput,
        request: Request,
        actor: Annotated[Actor, Depends(require_reviewer)],
        command_queue: Annotated[CommandQueue, Depends(queue)],
        repository: Annotated[RunStore, Depends(store)],
    ) -> Command:
        require_private(request)
        package = repository.get_raw(body.artifact_run_id)
        if body.subject_type == "FINDING":
            _validate_finding_disposition(
                package, finding_id=body.subject_id, decision=body.decision
            )
        payload = body.model_dump()
        payload["artifact_hash"] = _artifact_hash_for_subject(
            repository,
            run_id=body.artifact_run_id,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
        )
        return command_queue.enqueue(
            "RECORD_REVIEW_DECISION",
            actor.subject,
            payload,
            expected_version=body.expected_version,
        )

    @app.post("/api/v1/exceptions", response_model=Command, status_code=status.HTTP_202_ACCEPTED)
    def create_exception(
        body: ExceptionInput,
        request: Request,
        actor: Annotated[Actor, Depends(require_risk_approver)],
        command_queue: Annotated[CommandQueue, Depends(queue)],
        repository: Annotated[RunStore, Depends(store)],
    ) -> Command:
        require_private(request)
        payload = body.model_dump()
        payload["artifact_hash"] = _artifact_hash_for_subject(
            repository,
            run_id=body.artifact_run_id,
            subject_type="FINDING",
            subject_id=body.finding_id,
        )
        return command_queue.enqueue(
            "CREATE_EXCEPTION",
            actor.subject,
            payload,
            expected_version=body.expected_version,
        )

    @app.post("/api/v1/remediations", response_model=Command, status_code=status.HTTP_202_ACCEPTED)
    def mark_remediation_ready(
        body: RemediationInput,
        request: Request,
        actor: Annotated[Actor, Depends(require_reviewer)],
        command_queue: Annotated[CommandQueue, Depends(queue)],
        repository: Annotated[RunStore, Depends(store)],
    ) -> Command:
        require_private(request)
        package = repository.get_raw(body.artifact_run_id)
        _validate_remediation_evidence(package, body.evidence_refs)
        payload = body.model_dump(mode="json")
        payload["artifact_hash"] = _artifact_hash_for_subject(
            repository,
            run_id=body.artifact_run_id,
            subject_type="FINDING",
            subject_id=body.finding_id,
        )
        return command_queue.enqueue(
            "MARK_REMEDIATION_READY",
            actor.subject,
            payload,
            expected_version=body.expected_version,
        )

    @app.post("/api/v1/assistant/chat", response_model=ChatResponse)
    async def assistant_chat(
        body: ChatRequest,
        request: Request,
        x_ms_client_principal_id: Annotated[str | None, Header()] = None,
        x_ms_client_principal: Annotated[str | None, Header()] = None,
        x_aica_reviewer: Annotated[str | None, Header()] = None,
        x_aica_roles: Annotated[str | None, Header()] = None,
    ) -> ChatResponse:
        principal_subject, roles = _decode_client_principal(x_ms_client_principal)
        subject = x_ms_client_principal_id or principal_subject
        if settings.env != "production":
            subject = subject or x_aica_reviewer
            if x_aica_roles:
                roles = frozenset(item.strip() for item in x_aica_roles.split(",") if item.strip())
        if settings.env == "production" and not subject:
            raise HTTPException(status_code=401, detail="authenticated assistant identity required")
        subject = subject or "public-demo-user"
        assistant = cast(PolicyAssistantService, request.app.state.assistant)
        return await assistant.chat(body, user_subject=subject, app_roles=roles)

    return app


app = create_app()


def run() -> None:
    uvicorn.run("aica.api:app", host="0.0.0.0", port=8000, proxy_headers=True)  # noqa: S104
