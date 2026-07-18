"""Policy Assistant request, response, retrieval, and telemetry contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from aica.domain.models import Classification, StrictRecord


class Citation(StrictRecord):
    document_id: str
    section_id: str
    title: str
    excerpt: str
    classification: Classification
    score: float


class ToolRequest(StrictRecord):
    name: Literal["policy_lookup", "create_access_exception"]
    arguments: dict[str, str]
    consequential: bool


type ConfirmationState = Literal[
    "CONFIRMED",
    "MISSING",
    "INVALID",
    "EXPIRED",
    "REPLAYED",
    "MISMATCH",
    "NOT_REQUIRED",
]


class ToolConfirmation(StrictRecord):
    """Opaque, short-lived proof that the server prepared one exact tool request."""

    confirmation_token: str
    tool_name: str
    argument_digest: str
    expires_at: datetime


class ToolExecution(StrictRecord):
    name: str
    authorization: Literal["ALLOWED", "DENIED", "NOT_REQUIRED"]
    confirmation: ConfirmationState
    status: Literal["EXECUTED", "REJECTED", "NOT_REQUESTED"]
    result: dict[str, str] | None = None


class ChatRequest(StrictRecord):
    message: str = Field(min_length=1, max_length=4_000)
    session_id: str = Field(min_length=8, max_length=128)
    tool_confirmation_token: str | None = Field(default=None, min_length=32, max_length=512)
    # Deprecated compatibility input. It is deliberately ignored for authorization and execution.
    confirm_tool_execution: bool = False
    evaluation_mode: bool = False
    requested_tool: ToolRequest | None = None


class ChatResponse(StrictRecord):
    correlation_id: str
    evaluation_id: str
    answer: str
    citations: tuple[Citation, ...]
    tool: ToolExecution | None
    guardrail_outcomes: tuple[str, ...]
    model: str
    model_version: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    generated_at: datetime


class OperationalEvent(StrictRecord):
    correlation_id: str
    evaluation_id: str
    pseudonymous_user_id: str
    pseudonymous_session_id: str
    model: str
    model_version: str
    retrieval_document_ids: tuple[str, ...]
    retrieval_classifications: tuple[Classification, ...]
    latency_ms: int
    status: Literal["SUCCESS", "REJECTED", "ERROR"]
    input_tokens: int | None
    output_tokens: int | None
    guardrail_outcomes: tuple[str, ...]
    requested_tool: str | None
    authorization_decision: str | None
    confirmation_state: str | None
    tool_result_status: str | None
    occurred_at: datetime
