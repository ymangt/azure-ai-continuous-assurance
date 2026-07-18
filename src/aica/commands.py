"""Append-only command queues for local and Azure-hosted execution."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from azure.data.tables import TableClient
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from pydantic import BaseModel, ConfigDict

from aica.util.canonical import canonical_json_bytes, sha256_value
from aica.util.ids import new_id


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    type: str
    subject: str
    payload: dict[str, Any]
    expected_version: int | None
    status: str = "QUEUED"
    created_at: datetime
    payload_sha256: str


class CommandQueue(Protocol):
    def enqueue(
        self,
        command_type: str,
        subject: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
    ) -> Command: ...


def build_command(
    command_type: str,
    subject: str,
    payload: dict[str, Any],
    expected_version: int | None,
) -> Command:
    return Command(
        id=new_id("cmd"),
        type=command_type,
        subject=subject,
        payload=payload,
        expected_version=expected_version,
        created_at=datetime.now(UTC),
        payload_sha256=sha256_value(payload),
    )


class LocalCommandQueue:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def enqueue(
        self,
        command_type: str,
        subject: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
    ) -> Command:
        command = build_command(command_type, subject, payload, expected_version)
        path = self.root / f"{command.created_at:%Y%m%dT%H%M%S}-{command.id}.json"
        fd, temporary = tempfile.mkstemp(prefix=".command-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(canonical_json_bytes(command))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return command


class AzureTableCommandQueue:
    """Queue backed by Table Storage and authenticated without account keys."""

    def __init__(
        self,
        endpoint: str,
        table_name: str,
        *,
        managed_identity_client_id: str | None,
    ):
        credential = (
            ManagedIdentityCredential(client_id=managed_identity_client_id)
            if managed_identity_client_id
            else DefaultAzureCredential()
        )
        self.client = TableClient(endpoint=endpoint, table_name=table_name, credential=credential)

    def enqueue(
        self,
        command_type: str,
        subject: str,
        payload: dict[str, Any],
        expected_version: int | None = None,
    ) -> Command:
        command = build_command(command_type, subject, payload, expected_version)
        self.client.create_entity(
            {
                "PartitionKey": command_type,
                "RowKey": command.id,
                "subject": subject,
                "payload": json.dumps(payload, separators=(",", ":"), sort_keys=True),
                "expectedVersion": expected_version,
                "status": command.status,
                "createdAt": command.created_at.isoformat(),
                "payloadSha256": command.payload_sha256,
            }
        )
        return command
