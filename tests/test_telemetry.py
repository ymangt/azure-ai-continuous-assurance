from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import respx
from httpx import Response
from jsonschema import Draft202012Validator

from aica.assistant.contracts import OperationalEvent
from aica.domain.models import AssessmentRun, Classification, RunStatus
from aica.telemetry import (
    ASSURANCE_STREAM,
    OPERATIONAL_STREAM,
    LogsIngestionPublisher,
)


class FakeCredential:
    def __init__(self) -> None:
        self.closed = False

    async def get_token(self, _scope: str) -> SimpleNamespace:
        return SimpleNamespace(token="test-token")

    async def close(self) -> None:
        self.closed = True


def _publisher() -> tuple[LogsIngestionPublisher, FakeCredential]:
    publisher = object.__new__(LogsIngestionPublisher)
    publisher.endpoint = "https://example.ingest.monitor.azure.com"
    publisher.immutable_dcr_id = "dcr-immutable-id"
    credential = FakeCredential()
    publisher.credential = credential  # type: ignore[assignment]
    return publisher, credential


@pytest.mark.asyncio
@respx.mock
async def test_interaction_telemetry_uses_complete_content_minimized_schema() -> None:
    publisher, credential = _publisher()
    route = respx.post(
        "https://example.ingest.monitor.azure.com/dataCollectionRules/"
        f"dcr-immutable-id/streams/{OPERATIONAL_STREAM}?api-version=2023-01-01"
    ).mock(return_value=Response(204))
    event = OperationalEvent(
        correlation_id="corr-1",
        evaluation_id="eval-1",
        pseudonymous_user_id="usr-hash",
        pseudonymous_session_id="ses-hash",
        model="ReplayModelAdapter",
        model_version="1.0.0",
        retrieval_document_ids=("POL-016",),
        retrieval_classifications=(Classification.INTERNAL,),
        latency_ms=12,
        status="REJECTED",
        input_tokens=None,
        output_tokens=None,
        guardrail_outcomes=("CONFIRMATION_REQUIRED",),
        requested_tool="create_access_exception",
        authorization_decision="ALLOWED",
        confirmation_state="MISSING",
        tool_result_status="REJECTED",
        occurred_at=datetime(2026, 7, 16, 12, tzinfo=UTC),
    )

    await publisher.publish_operational_event(event)
    await publisher.close()

    payload = json.loads(route.calls[0].request.content)[0]
    schema = json.loads(Path("schemas/operational-telemetry.schema.json").read_text())
    Draft202012Validator(schema, format_checker=None).validate(payload)
    assert payload["SchemaVersion"] == "1.0.0"
    assert payload["EventName"] == "tool_authorization"
    assert payload["EvaluationId"] == "eval-1"
    assert payload["Model"] == "ReplayModelAdapter"
    assert payload["ModelVersion"] == "1.0.0"
    assert payload["RetrievalDocumentIds"] == ["POL-016"]
    assert payload["RetrievalClassifications"] == ["INTERNAL"]
    assert payload["LatencyMs"] == 12
    assert payload["InputTokens"] is None
    assert payload["OutputTokens"] is None
    assert payload["Status"] == "REJECTED"
    assert payload["GuardrailOutcomes"] == ["CONFIRMATION_REQUIRED"]
    assert payload["ToolName"] == "create_access_exception"
    assert payload["AuthorizationDecision"] == "ALLOWED"
    assert payload["ConfirmationState"] == "MISSING"
    assert payload["ToolResultStatus"] == "REJECTED"
    assert payload["Decision"] == "REJECTED"
    assert payload["UserPseudonym"] == "usr-hash"
    assert not {"prompt", "response", "message", "answer"}.intersection(payload)
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"
    assert credential.closed is True


@pytest.mark.asyncio
@respx.mock
async def test_non_tool_interaction_is_persisted_with_explicit_null_tool_state() -> None:
    publisher, _ = _publisher()
    route = respx.post(
        "https://example.ingest.monitor.azure.com/dataCollectionRules/"
        f"dcr-immutable-id/streams/{OPERATIONAL_STREAM}?api-version=2023-01-01"
    ).mock(return_value=Response(204))
    event = OperationalEvent(
        correlation_id="corr-2",
        evaluation_id="eval-2",
        pseudonymous_user_id="usr-hash",
        pseudonymous_session_id="ses-hash",
        model="Phi-4-mini-instruct",
        model_version="2026-01-01",
        retrieval_document_ids=(),
        retrieval_classifications=(),
        latency_ms=8,
        status="SUCCESS",
        input_tokens=9,
        output_tokens=4,
        guardrail_outcomes=(),
        requested_tool=None,
        authorization_decision=None,
        confirmation_state=None,
        tool_result_status=None,
        occurred_at=datetime(2026, 7, 16, 12, 1, tzinfo=UTC),
    )

    await publisher.publish_operational_event(event)

    payload = json.loads(route.calls[0].request.content)[0]
    assert payload["EventName"] == "assistant_interaction"
    assert payload["Status"] == "SUCCESS"
    assert payload["InputTokens"] == 9
    assert payload["OutputTokens"] == 4
    assert payload["ToolName"] is None
    assert payload["AuthorizationDecision"] is None
    assert payload["ConfirmationState"] is None
    assert payload["ToolResultStatus"] is None


@pytest.mark.asyncio
@respx.mock
async def test_assurance_run_telemetry_matches_dcr_contract() -> None:
    publisher, _ = _publisher()
    route = respx.post(
        "https://example.ingest.monitor.azure.com/dataCollectionRules/"
        f"dcr-immutable-id/streams/{ASSURANCE_STREAM}?api-version=2023-01-01"
    ).mock(return_value=Response(204))
    started = datetime(2026, 7, 16, 12, tzinfo=UTC)
    run = AssessmentRun(
        id="run-telemetry",
        trigger="scheduled",
        scope=("rg-aica-sut-eus2",),
        observation_window_start=started - timedelta(hours=24),
        observation_window_end=started,
        git_commit="abcdef0",
        collector_version="1.0.0",
        evaluator_version="1.0.0",
        started_at=started,
        ended_at=started + timedelta(minutes=1),
        status=RunStatus.COMPLETED,
    )

    await publisher.publish_assurance_run(run)

    payload = json.loads(route.calls[0].request.content)[0]
    assert payload == {
        "TimeGenerated": "2026-07-16T12:01:00+00:00",
        "RunId": "run-telemetry",
        "Status": "COMPLETED",
        "Scope": "rg-aica-sut-eus2",
        "CorrelationId": "run-telemetry",
        "GitCommit": "abcdef0",
    }


@pytest.mark.asyncio
async def test_telemetry_rejects_unknown_streams_and_raw_content() -> None:
    publisher, _ = _publisher()
    with pytest.raises(ValueError, match="unapproved DCR stream"):
        await publisher.publish("Custom-Unapproved_CL", {"TimeGenerated": "now"})
    with pytest.raises(ValueError, match="raw content fields"):
        await publisher.publish(OPERATIONAL_STREAM, {"Prompt": "must not be logged"})
    with pytest.raises(ValueError, match="raw content fields"):
        await publisher.publish(OPERATIONAL_STREAM, {"rawPromptText": "must not be logged"})
    with pytest.raises(ValueError, match="raw content fields"):
        await publisher.publish(
            OPERATIONAL_STREAM, {"retrievedContent": "must not be logged"}
        )


def test_operational_payload_columns_match_dcr_and_table_contract() -> None:
    bicep = Path("infra/modules/sentinel-content.bicep").read_text(encoding="utf-8")
    schema = json.loads(Path("schemas/operational-telemetry.schema.json").read_text())
    table_block = bicep.split("resource toolSecurityTable", 1)[1].split(
        "resource dcr", 1
    )[0]
    stream_block = bicep.split("'Custom-AicaToolSecurity_CL':", 1)[1].split(
        "destinations:", 1
    )[0]
    column_types = {
        "SchemaVersion": "string",
        "TimeGenerated": "datetime",
        "EventName": "string",
        "CorrelationId": "string",
        "EvaluationId": "string",
        "UserPseudonym": "string",
        "SessionId": "string",
        "Model": "string",
        "ModelVersion": "string",
        "RetrievalDocumentIds": "dynamic",
        "RetrievalClassifications": "dynamic",
        "LatencyMs": "long",
        "InputTokens": "long",
        "OutputTokens": "long",
        "Status": "string",
        "GuardrailOutcomes": "dynamic",
        "ToolName": "string",
        "AuthorizationDecision": "string",
        "ConfirmationState": "string",
        "ToolResultStatus": "string",
        "Decision": "string",
        "Reason": "string",
    }
    assert set(column_types) == set(schema["required"])
    for column, column_type in column_types.items():
        declaration = f"{{ name: '{column}', type: '{column_type}' }}"
        assert table_block.count(declaration) == 1
        assert stream_block.count(declaration) == 1


def test_rejected_tool_fixture_and_workbook_use_operational_contract() -> None:
    schema = json.loads(Path("schemas/operational-telemetry.schema.json").read_text())
    fixture = json.loads(
        Path("sentinel/tests/fixtures/rejected-tool-events.json").read_text()
    )
    validator = Draft202012Validator(schema, format_checker=None)
    for event in fixture:
        validator.validate(event)

    workbook = Path("sentinel/workbook.json").read_text(encoding="utf-8")
    for field in (
        "ModelVersion",
        "GuardrailOutcomes",
        "LatencyMs",
        "InputTokens",
        "OutputTokens",
        "ToolResultStatus",
        "AuthorizationDecision",
        "EvaluationId",
    ):
        assert field in workbook


def test_sentinel_queries_consume_the_published_terminal_statuses() -> None:
    alert_query = Path("sentinel/queries/failed-or-stale-assurance-run.kql").read_text(
        encoding="utf-8"
    )
    workbook = Path("sentinel/workbook.json").read_text(encoding="utf-8")
    assert "'COMPLETED', 'REVIEW_REQUIRED'" in alert_query
    assert "Status in~ ('FAILED', 'STALE')" in alert_query
    for status in ("COMPLETED", "REVIEW_REQUIRED", "FAILED"):
        assert status in workbook
    assert "SUCCEEDED" not in alert_query
    assert "SUCCEEDED" not in workbook
