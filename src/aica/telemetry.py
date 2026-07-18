"""Content-minimized Azure Monitor Logs Ingestion publisher."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

import httpx
from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential

from aica.assistant.contracts import OperationalEvent
from aica.domain.models import AssessmentRun

MONITOR_SCOPE = "https://monitor.azure.com/.default"
OPERATIONAL_SCHEMA_VERSION = "1.0.0"
OPERATIONAL_STREAM = "Custom-AicaToolSecurity_CL"
# Compatibility alias for existing callers and deployed DCR parameters.
TOOL_STREAM = OPERATIONAL_STREAM
ASSURANCE_STREAM = "Custom-AicaAssurance_CL"
ALLOWED_STREAMS = frozenset({OPERATIONAL_STREAM, ASSURANCE_STREAM})
FORBIDDEN_CONTENT_MARKERS = frozenset({"prompt", "response", "message", "answer", "excerpt"})
FORBIDDEN_SECRET_FIELDS = frozenset(
    {"accesstoken", "confirmationtoken", "retrievedcontent", "secret"}
)


class OperationalTelemetrySink(Protocol):
    async def publish_operational_event(self, event: OperationalEvent) -> None: ...


def _assert_content_minimized(value: Any) -> None:
    if isinstance(value, Mapping):
        normalized_keys = {
            "".join(character for character in str(key).casefold() if character.isalnum())
            for key in value
        }
        forbidden = {
            key
            for key in normalized_keys
            if key in FORBIDDEN_SECRET_FIELDS
            or any(marker in key for marker in FORBIDDEN_CONTENT_MARKERS)
        }
        if forbidden:
            raise ValueError(f"raw content fields are forbidden in operational logs: {sorted(forbidden)}")
        for child in value.values():
            _assert_content_minimized(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            _assert_content_minimized(child)


def operational_record(event: OperationalEvent) -> dict[str, Any]:
    """Map one interaction to the bounded operational ingestion contract."""

    return {
        "SchemaVersion": OPERATIONAL_SCHEMA_VERSION,
        "TimeGenerated": event.occurred_at.isoformat(),
        "EventName": "tool_authorization" if event.requested_tool else "assistant_interaction",
        "CorrelationId": event.correlation_id,
        "EvaluationId": event.evaluation_id,
        "UserPseudonym": event.pseudonymous_user_id,
        "SessionId": event.pseudonymous_session_id,
        "Model": event.model,
        "ModelVersion": event.model_version,
        "RetrievalDocumentIds": list(event.retrieval_document_ids),
        "RetrievalClassifications": [
            classification.value for classification in event.retrieval_classifications
        ],
        "LatencyMs": event.latency_ms,
        "InputTokens": event.input_tokens,
        "OutputTokens": event.output_tokens,
        "Status": event.status,
        "GuardrailOutcomes": list(event.guardrail_outcomes),
        "ToolName": event.requested_tool,
        "AuthorizationDecision": event.authorization_decision,
        "ConfirmationState": event.confirmation_state,
        "ToolResultStatus": event.tool_result_status,
        # Retained for the existing collector and analytic content during schema evolution.
        "Decision": event.tool_result_status or event.status,
        "Reason": event.confirmation_state or event.authorization_decision,
    }


class LogsIngestionPublisher:
    def __init__(
        self,
        endpoint: str,
        immutable_dcr_id: str,
        *,
        managed_identity_client_id: str | None,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.immutable_dcr_id = immutable_dcr_id
        self.credential = (
            ManagedIdentityCredential(client_id=managed_identity_client_id)
            if managed_identity_client_id
            else DefaultAzureCredential(exclude_interactive_browser_credential=True)
        )

    async def publish(self, stream: str, record: dict[str, Any]) -> None:
        if stream not in ALLOWED_STREAMS:
            raise ValueError(f"unapproved DCR stream: {stream}")
        _assert_content_minimized(record)
        token = await self.credential.get_token(MONITOR_SCOPE)
        url = (
            f"{self.endpoint}/dataCollectionRules/{self.immutable_dcr_id}/streams/{stream}"
        )
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                url,
                params={"api-version": "2023-01-01"},
                headers={"Authorization": f"Bearer {token.token}"},
                json=[record],
            )
            response.raise_for_status()

    async def publish_operational_event(self, event: OperationalEvent) -> None:
        await self.publish(OPERATIONAL_STREAM, operational_record(event))

    async def publish_assurance_run(self, run: AssessmentRun) -> None:
        await self.publish(
            ASSURANCE_STREAM,
            {
                "TimeGenerated": (run.ended_at or run.started_at).isoformat(),
                "RunId": run.id,
                "Status": run.status.value,
                "Scope": ",".join(run.scope),
                "CorrelationId": run.id,
                "GitCommit": run.git_commit,
            },
        )

    async def close(self) -> None:
        await self.credential.close()
