from datetime import UTC, datetime, timedelta

import pytest

from aica.command_worker import (
    AzureCommandProcessor,
    CommandProcessingError,
    OptimisticConcurrencyError,
    assessment_job_args,
    build_exception_event,
    build_remediation_event,
    build_review_event,
    processing_lease_is_stale,
)
from aica.commands import build_command


def test_review_event_increments_expected_version_once() -> None:
    command = build_command(
        "RECORD_REVIEW_DECISION",
        "reviewer-1",
        {
            "subject_type": "CONTROL",
            "subject_id": "AC-3.1",
            "prior_state": "SUGGESTED",
            "decision": "ACCEPTED",
            "rationale": "The linked evidence is current and sufficient.",
            "artifact_hash": "a" * 64,
        },
        1,
    )
    event = build_review_event(command, 1)
    assert event.version == 2
    assert event.expected_version == 1


def test_review_event_rejects_stale_expected_version() -> None:
    command = build_command(
        "RECORD_REVIEW_DECISION",
        "reviewer-1",
        {
            "subject_type": "CONTROL",
            "subject_id": "AC-3.1",
            "prior_state": "SUGGESTED",
            "decision": "ACCEPTED",
            "rationale": "The linked evidence is current and sufficient.",
            "artifact_hash": "a" * 64,
        },
        1,
    )
    with pytest.raises(OptimisticConcurrencyError):
        build_review_event(command, 2)


def test_exception_event_validates_expiry_and_version() -> None:
    command = build_command(
        "CREATE_EXCEPTION",
        "risk-approver-1",
        {
            "finding_id": "FND-001",
            "rationale": "Temporary acceptance while the safe fixture is removed.",
            "compensating_controls": ["Daily review"],
            "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "review_cadence": "daily",
        },
        1,
    )
    event, version = build_exception_event(command, 1)
    assert version == 2
    assert event.finding_id == "FND-001"


def test_remediation_event_is_append_only_and_version_bound() -> None:
    command = build_command(
        "MARK_REMEDIATION_READY",
        "reviewer-1",
        {
            "finding_id": "FND-001",
            "artifact_run_id": "run-signed",
            "owner": "Cloud Owner",
            "action": "Remove the broad ingress rule through reviewed infrastructure code.",
            "target_date": "2026-08-01T00:00:00Z",
            "commit_or_pr": "PR-101",
            "evidence_refs": ["EVD-001"],
            "artifact_hash": "a" * 64,
        },
        3,
    )

    event = build_remediation_event(command, 3)

    assert event.status == "READY_FOR_RETEST"
    assert event.recorded_by == "reviewer-1"
    assert event.artifact_run_id == "run-signed"
    assert event.artifact_hash == "a" * 64
    assert event.expected_version == 3
    assert event.version == 4
    with pytest.raises(OptimisticConcurrencyError):
        build_remediation_event(command, 4)


def test_retest_dispatch_preserves_each_targeted_finding() -> None:
    command = build_command(
        "RUN_RETEST",
        "assessor-1",
        {
            "profile": "azure-dev",
            "prior_run_id": "run-prior",
            "finding_ids": ["FND-001", "FND-003"],
        },
        None,
    )
    assert assessment_job_args(command) == [
        "collect",
        "--profile",
        "azure-dev",
        "--prior-run",
        "run-prior",
        "--finding",
        "FND-001",
        "--finding",
        "FND-003",
    ]


def test_processing_lease_expiry_is_fail_safe() -> None:
    now = datetime(2026, 7, 16, 12, tzinfo=UTC)
    assert processing_lease_is_stale(
        {"processingStartedAt": (now - timedelta(minutes=16)).isoformat()}, now=now
    )
    assert not processing_lease_is_stale(
        {"processingStartedAt": (now - timedelta(minutes=14)).isoformat()}, now=now
    )
    assert processing_lease_is_stale({"processingStartedAt": "malformed"}, now=now)


def test_worker_rejects_mutated_queued_payload() -> None:
    command = build_command(
        "RUN_ASSESSMENT",
        "assessor-1",
        {"profile": "azure-dev", "reason": "Run the scheduled assessment."},
        None,
    )
    entity = {
        "PartitionKey": command.type,
        "RowKey": command.id,
        "subject": command.subject,
        "payload": '{"profile":"tampered"}',
        "expectedVersion": None,
        "status": "PROCESSING",
        "createdAt": command.created_at,
        "payloadSha256": command.payload_sha256,
    }
    with pytest.raises(CommandProcessingError, match="payload digest mismatch"):
        AzureCommandProcessor._command(entity)
