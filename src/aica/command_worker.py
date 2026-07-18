"""Idempotent Azure command consumer with optimistic review-event concurrency."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
from azure.core import MatchConditions
from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
from azure.data.tables import TableClient, TableTransactionError, UpdateMode
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.identity.aio import (
    DefaultAzureCredential as AsyncDefaultAzureCredential,
)
from azure.identity.aio import (
    ManagedIdentityCredential as AsyncManagedIdentityCredential,
)

from aica.commands import Command
from aica.domain.models import ExceptionRecord, Remediation, ReviewDecision
from aica.util.canonical import canonical_json_bytes, sha256_value
from aica.util.ids import new_id

ARM_SCOPE = "https://management.azure.com/.default"
JOB_API_VERSION = "2025-01-01"
COMMAND_LEASE_TIMEOUT = timedelta(minutes=15)


class CommandProcessingError(RuntimeError):
    pass


class OptimisticConcurrencyError(CommandProcessingError):
    pass


def assessment_job_args(command: Command) -> list[str]:
    args = ["collect", "--profile", str(command.payload.get("profile", "azure-dev"))]
    if command.type == "RUN_RETEST":
        args.extend(["--prior-run", str(command.payload["prior_run_id"])])
        for finding_id in command.payload.get("finding_ids", []):
            args.extend(["--finding", str(finding_id)])
    return args


def processing_lease_is_stale(entity: dict[str, Any], *, now: datetime) -> bool:
    value = entity.get("processingStartedAt")
    if isinstance(value, datetime):
        started = value
    elif isinstance(value, str):
        try:
            started = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return True
    else:
        return True
    if started.tzinfo is None:
        return True
    return now - started.astimezone(UTC) > COMMAND_LEASE_TIMEOUT


def build_review_event(command: Command, current_version: int) -> ReviewDecision:
    expected = command.expected_version
    if expected is None or expected != current_version:
        raise OptimisticConcurrencyError(
            f"expected subject version {expected}, current version is {current_version}"
        )
    payload = command.payload
    return ReviewDecision(
        id=new_id("decision"),
        reviewer=command.subject,
        subject_type=payload["subject_type"],
        subject_id=payload["subject_id"],
        prior_state=payload["prior_state"],
        decision=payload["decision"],
        rationale=payload["rationale"],
        timestamp=datetime.now(UTC),
        artifact_hash=payload["artifact_hash"],
        expected_version=expected,
        version=expected + 1,
    )


def build_exception_event(command: Command, current_version: int) -> tuple[ExceptionRecord, int]:
    expected = command.expected_version
    if expected is None or expected != current_version:
        raise OptimisticConcurrencyError(
            f"expected subject version {expected}, current version is {current_version}"
        )
    payload = command.payload
    event = ExceptionRecord(
        id=new_id("exception"),
        finding_id=payload["finding_id"],
        approver=command.subject,
        rationale=payload["rationale"],
        compensating_controls=tuple(payload["compensating_controls"]),
        approved_at=datetime.now(UTC),
        expires_at=payload["expires_at"],
        review_cadence=payload["review_cadence"],
        artifact_hash=payload.get("artifact_hash"),
    )
    return event, expected + 1


def build_remediation_event(command: Command, current_version: int) -> Remediation:
    expected = command.expected_version
    if expected is None or expected != current_version:
        raise OptimisticConcurrencyError(
            f"expected subject version {expected}, current version is {current_version}"
        )
    payload = command.payload
    recorded_at = datetime.now(UTC)
    return Remediation(
        id=new_id("remediation"),
        finding_id=payload["finding_id"],
        owner=payload["owner"],
        action=payload["action"],
        target_date=payload["target_date"],
        commit_or_pr=payload["commit_or_pr"],
        evidence_refs=tuple(payload["evidence_refs"]),
        status="READY_FOR_RETEST",
        recorded_by=command.subject,
        recorded_at=recorded_at,
        artifact_run_id=payload["artifact_run_id"],
        artifact_hash=payload["artifact_hash"],
        expected_version=expected,
        version=expected + 1,
    )


class AzureAssessmentJobDispatcher:
    def __init__(self, resource_id: str, *, managed_identity_client_id: str | None):
        self.resource_id = resource_id.rstrip("/")
        self.credential = (
            AsyncManagedIdentityCredential(client_id=managed_identity_client_id)
            if managed_identity_client_id
            else AsyncDefaultAzureCredential(exclude_interactive_browser_credential=True)
        )

    async def dispatch(self, command: Command) -> dict[str, str]:
        token = await self.credential.get_token(ARM_SCOPE)
        headers = {"Authorization": f"Bearer {token.token}"}
        resource_url = f"https://management.azure.com{self.resource_id}"
        async with httpx.AsyncClient(timeout=45) as client:
            response = await client.get(
                resource_url,
                params={"api-version": JOB_API_VERSION},
                headers=headers,
            )
            response.raise_for_status()
            template = cast(dict[str, Any], response.json()["properties"]["template"])
            containers = template.get("containers", [])
            assessor = next(
                (item for item in containers if item.get("name") == "assessor"),
                None,
            )
            if assessor is None:
                raise CommandProcessingError("assessment job has no assessor container")
            assessor["command"] = ["assure"]
            assessor["args"] = assessment_job_args(command)
            started = await client.post(
                f"{resource_url}/start",
                params={"api-version": JOB_API_VERSION},
                headers=headers,
                json=template,
            )
            started.raise_for_status()
        if started.content:
            body = started.json()
            return {
                "execution_id": str(body.get("id", "accepted")),
                "execution_name": str(body.get("name", "accepted")),
            }
        raise CommandProcessingError("Azure accepted the job start without an execution identity")

    async def execution_status(self, execution_name: str) -> str:
        token = await self.credential.get_token(ARM_SCOPE)
        resource_url = f"https://management.azure.com{self.resource_id}/executions"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                resource_url,
                params={"api-version": JOB_API_VERSION},
                headers={"Authorization": f"Bearer {token.token}"},
            )
            response.raise_for_status()
        for execution in response.json().get("value", []):
            if str(execution.get("name")) == execution_name:
                return str(execution.get("properties", {}).get("status", "Unknown"))
        return "NotFound"

    async def close(self) -> None:
        await self.credential.close()


class AzureCommandProcessor:
    """Claims queue rows by ETag, dispatches work, and records append-only results."""

    def __init__(
        self,
        endpoint: str,
        command_table: str,
        review_table: str,
        assessment_job_resource_id: str,
        *,
        managed_identity_client_id: str | None,
    ):
        credential = (
            ManagedIdentityCredential(client_id=managed_identity_client_id)
            if managed_identity_client_id
            else DefaultAzureCredential(exclude_interactive_browser_credential=True)
        )
        self.credential = credential
        self.commands = TableClient(endpoint, command_table, credential=credential)
        self.reviews = TableClient(endpoint, review_table, credential=credential)
        self.dispatcher = AzureAssessmentJobDispatcher(
            assessment_job_resource_id,
            managed_identity_client_id=managed_identity_client_id,
        )

    @staticmethod
    def _command(entity: dict[str, Any]) -> Command:
        payload = json.loads(str(entity["payload"]))
        if sha256_value(payload) != str(entity["payloadSha256"]):
            raise CommandProcessingError("queued command payload digest mismatch")
        return Command(
            id=str(entity["RowKey"]),
            type=str(entity["PartitionKey"]),
            subject=str(entity["subject"]),
            payload=payload,
            expected_version=(
                int(entity["expectedVersion"])
                if entity.get("expectedVersion") is not None
                else None
            ),
            status=str(entity["status"]),
            created_at=entity["createdAt"],
            payload_sha256=str(entity["payloadSha256"]),
        )

    def _claim(self, entity: Any) -> bool:
        update = {
            "PartitionKey": entity["PartitionKey"],
            "RowKey": entity["RowKey"],
            "status": "PROCESSING",
            "processingStartedAt": datetime.now(UTC).isoformat(),
        }
        try:
            self.commands.update_entity(
                update,
                mode=UpdateMode.MERGE,
                etag=entity.metadata["etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            return True
        except ResourceModifiedError:
            return False

    def _subject_state(self, subject_id: str, command_id: str) -> tuple[int, Any | None, bool]:
        try:
            self.reviews.get_entity(subject_id, f"EVENT-{command_id}")
            return 1, None, True
        except ResourceNotFoundError:
            pass
        try:
            state = self.reviews.get_entity(subject_id, "STATE")
            return int(state.get("version", 1)), state, False
        except ResourceNotFoundError:
            return 1, None, False

    def _append_event(
        self,
        *,
        subject_id: str,
        command: Command,
        event_type: str,
        version: int,
        event_json: str,
        recorded_at: str,
        state: Any | None,
    ) -> bool:
        event = {
            "PartitionKey": subject_id,
            "RowKey": f"EVENT-{command.id}",
            "commandId": command.id,
            "eventType": event_type,
            "version": version,
            "eventJson": event_json,
            "recordedAt": recorded_at,
        }
        next_state = {
            "PartitionKey": subject_id,
            "RowKey": "STATE",
            "version": version,
            "lastCommandId": command.id,
            "updatedAt": recorded_at,
        }
        operations: list[tuple[Any, ...]]
        if state is None:
            operations = [("create", next_state), ("create", event)]
        else:
            operations = [
                (
                    "update",
                    next_state,
                    {
                        "mode": UpdateMode.MERGE,
                        "etag": state.metadata["etag"],
                        "match_condition": MatchConditions.IfNotModified,
                    },
                ),
                ("create", event),
            ]
        try:
            self.reviews.submit_transaction(operations)
            return True
        except TableTransactionError as exc:
            try:
                self.reviews.get_entity(subject_id, f"EVENT-{command.id}")
                return False
            except ResourceNotFoundError:
                raise OptimisticConcurrencyError(
                    "subject was changed by another reviewer; reload before deciding"
                ) from exc

    def _record_review(self, command: Command) -> dict[str, str]:
        subject_id = str(command.payload["subject_id"])
        current, state, recorded = self._subject_state(subject_id, command.id)
        if recorded:
            return {"recorded": "already"}
        event = build_review_event(command, current)
        created = self._append_event(
            subject_id=subject_id,
            command=command,
            event_type="REVIEW_DECISION",
            version=event.version,
            event_json=canonical_json_bytes(event).decode("utf-8"),
            recorded_at=event.timestamp.isoformat(),
            state=state,
        )
        return {"recorded": event.id if created else "already"}

    def _record_exception(self, command: Command) -> dict[str, str]:
        subject_id = str(command.payload["finding_id"])
        current, state, recorded = self._subject_state(subject_id, command.id)
        if recorded:
            return {"recorded": "already"}
        event, version = build_exception_event(command, current)
        created = self._append_event(
            subject_id=subject_id,
            command=command,
            event_type="EXCEPTION",
            version=version,
            event_json=canonical_json_bytes(event).decode("utf-8"),
            recorded_at=event.approved_at.isoformat(),
            state=state,
        )
        return {"recorded": event.id if created else "already"}

    def _record_remediation(self, command: Command) -> dict[str, str]:
        subject_id = str(command.payload["finding_id"])
        current, state, recorded = self._subject_state(subject_id, command.id)
        if recorded:
            return {"recorded": "already"}
        event = build_remediation_event(command, current)
        created = self._append_event(
            subject_id=subject_id,
            command=command,
            event_type="REMEDIATION",
            version=cast(int, event.version),
            event_json=canonical_json_bytes(event).decode("utf-8"),
            recorded_at=cast(datetime, event.recorded_at).isoformat(),
            state=state,
        )
        return {"recorded": event.id if created else "already"}

    async def _handle(self, command: Command) -> dict[str, str]:
        if command.type in {"RUN_ASSESSMENT", "RUN_RETEST"}:
            result = await self.dispatcher.dispatch(command)
            result["command_status"] = "DISPATCHED"
            return result
        if command.type == "RECORD_REVIEW_DECISION":
            return await asyncio.to_thread(self._record_review, command)
        if command.type == "CREATE_EXCEPTION":
            return await asyncio.to_thread(self._record_exception, command)
        if command.type == "MARK_REMEDIATION_READY":
            return await asyncio.to_thread(self._record_remediation, command)
        if command.type in {"RUN_FIXTURE", "CLEANUP_FIXTURE"}:
            if command.payload.get("resource_group") != "rg-aica-fixture-eus2":
                raise CommandProcessingError("fixture request is outside the approved group")
            return {
                "command_status": "AWAITING_MCP_OPERATOR",
                "operator": "Azure MCP",
                "scenario_id": str(command.payload["scenario_id"]),
            }
        raise CommandProcessingError(f"unsupported command type {command.type}")

    def _finish(
        self,
        entity: dict[str, Any],
        *,
        status: str,
        result: dict[str, str],
    ) -> None:
        updated_at = datetime.now(UTC).isoformat()
        update = {
            "PartitionKey": entity["PartitionKey"],
            "RowKey": entity["RowKey"],
            "status": status,
            "result": json.dumps(result, separators=(",", ":"), sort_keys=True),
            "updatedAt": updated_at,
        }
        if status in {"SUCCEEDED", "FAILED"}:
            update["completedAt"] = updated_at
        self.commands.update_entity(update, mode=UpdateMode.MERGE)

    async def _reconcile_dispatched(self, *, limit: int) -> dict[str, int]:
        entities = await asyncio.to_thread(
            lambda: list(self.commands.query_entities("status eq 'DISPATCHED'"))[:limit]
        )
        result = {"reconciled": 0, "succeeded": 0, "failed": 0, "running": 0}
        for entity in entities:
            try:
                saved = json.loads(str(entity.get("result", "{}")))
                execution_name = str(saved["execution_name"])
                execution_status = await self.dispatcher.execution_status(execution_name)
                if execution_status.casefold() == "succeeded":
                    await asyncio.to_thread(
                        self._finish,
                        entity,
                        status="SUCCEEDED",
                        result={**saved, "execution_status": execution_status},
                    )
                    result["reconciled"] += 1
                    result["succeeded"] += 1
                elif execution_status.casefold() == "notfound" and not processing_lease_is_stale(
                    {"processingStartedAt": entity.get("updatedAt")},
                    now=datetime.now(UTC),
                ):
                    result["running"] += 1
                elif execution_status.casefold() in {"failed", "stopped", "notfound"}:
                    await asyncio.to_thread(
                        self._finish,
                        entity,
                        status="FAILED",
                        result={**saved, "execution_status": execution_status},
                    )
                    result["reconciled"] += 1
                    result["failed"] += 1
                else:
                    result["running"] += 1
            except (KeyError, TypeError, ValueError, json.JSONDecodeError, httpx.HTTPError):
                await asyncio.to_thread(
                    self._finish,
                    entity,
                    status="FAILED",
                    result={"error_type": "ExecutionReconciliationError"},
                )
                result["reconciled"] += 1
                result["failed"] += 1
        return result

    async def _expire_stale_leases(self, *, limit: int) -> int:
        entities = await asyncio.to_thread(
            lambda: list(self.commands.query_entities("status eq 'PROCESSING'"))[:limit]
        )
        expired = 0
        now = datetime.now(UTC)
        for entity in entities:
            if processing_lease_is_stale(entity, now=now):
                await asyncio.to_thread(
                    self._finish,
                    entity,
                    status="FAILED",
                    result={"error_type": "CommandLeaseExpired", "replayed": "false"},
                )
                expired += 1
        return expired

    async def process_once(self, *, limit: int = 20) -> dict[str, int]:
        try:
            reconciled = await self._reconcile_dispatched(limit=limit)
            expired = await self._expire_stale_leases(limit=limit)
            entities = await asyncio.to_thread(
                lambda: list(self.commands.query_entities("status eq 'QUEUED'"))[:limit]
            )
            summary = {
                "claimed": 0,
                "succeeded": reconciled["succeeded"],
                "dispatched": 0,
                "reconciled": reconciled["reconciled"],
                "running": reconciled["running"],
                "expired": expired,
                "failed": reconciled["failed"] + expired,
                "awaiting_operator": 0,
            }
            for entity in entities:
                if not await asyncio.to_thread(self._claim, entity):
                    continue
                summary["claimed"] += 1
                try:
                    command = self._command(entity)
                    result = await self._handle(command)
                    final_status = result.pop("command_status", "SUCCEEDED")
                    await asyncio.to_thread(
                        self._finish,
                        entity,
                        status=final_status,
                        result=result,
                    )
                    if final_status == "AWAITING_MCP_OPERATOR":
                        summary["awaiting_operator"] += 1
                    elif final_status == "DISPATCHED":
                        summary["dispatched"] += 1
                    else:
                        summary["succeeded"] += 1
                except Exception as exc:
                    await asyncio.to_thread(
                        self._finish,
                        entity,
                        status="FAILED",
                        result={"error_type": type(exc).__name__},
                    )
                    summary["failed"] += 1
            return summary
        finally:
            await self.dispatcher.close()
            await asyncio.to_thread(self.credential.close)
