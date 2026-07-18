"""Application-owned retrieval, authorization, confirmation, and telemetry."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.data.tables import TableClient, UpdateMode
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

from aica.assistant.adapters import ModelAdapter, ModelAnswer
from aica.assistant.contracts import (
    ChatRequest,
    ChatResponse,
    Citation,
    ConfirmationState,
    OperationalEvent,
    ToolConfirmation,
    ToolExecution,
    ToolRequest,
)
from aica.assistant.retrieval import PolicyIndex
from aica.telemetry import OperationalTelemetrySink
from aica.util.ids import new_id

LOGGER = logging.getLogger("aica.policy_assistant")
DIRECT_INJECTION_PATTERN = re.compile(
    r"(?i)(ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions|"
    r"ignore\s+(?:your\s+)?policy\s+scope|"
    r"(?:reveal|show|print).{0,30}(?:system|developer|hidden)\s+(?:prompt|instructions)|"
    r"bypass.{0,30}(?:guardrail|policy|instruction))"
)
OUT_OF_SCOPE_PATTERN = re.compile(
    r"(?i)\b(medical|legal|financial|disciplinary|employment|weather|"
    r"diagnos(?:e|is)|prescri(?:be|ption))\b"
)
SENSITIVE_SUBMISSION_PATTERN = re.compile(
    r"(?i)\b(store|save|remember|submit|here\s+is|my)\b.{0,80}"
    r"\b(password|client\s+secret|api\s+key|access\s+token|credential)\b"
)
ABUSIVE_REQUEST_PATTERN = re.compile(
    r"(?i)\b(generate|write|compose|create)\b.{0,80}\b(abusive|harassing|insulting)\b"
)
SENSITIVE_DISCLOSURE_PATTERN = re.compile(
    r"(?i)(?:raw\s+prompts?.{0,40}(?:another|other)\s+evaluation|"
    r"(?:tenant|subscription)\s+(?:and\s+)?(?:tenant|subscription)?\s*identifiers?.{0,40}"
    r"evidence\s+store)"
)
GOVERNANCE_DECISION_PATTERN = re.compile(
    r"(?i)(?:mark\s+every\s+control\s+compliant|close\s+all\s+findings|"
    r"approve.{0,60}(?:exception|on\s+my\s+behalf)|real\s+production\s+access\s+request)"
)
AMBIGUOUS_POLICY_PATTERN = re.compile(
    r"(?i)which\s+policy\s+applies\?.{0,80}(?:only\s+know|concerns\s+data)"
)

CONSEQUENTIAL_TOOL_ROLES: dict[str, frozenset[str]] = {
    "create_access_exception": frozenset({"Assurance.Assessor"}),
}
CONSEQUENTIAL_TOOL_REQUIRED_ARGUMENTS: dict[str, frozenset[str]] = {
    "create_access_exception": frozenset(
        {"policy_id", "business_justification", "requested_duration"}
    ),
}


def canonical_argument_digest(arguments: dict[str, str]) -> str:
    """Digest the exact, order-independent JSON representation of tool arguments."""

    canonical = json.dumps(
        arguments,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True, slots=True)
class ConfirmationBinding:
    actor_pseudonym: str
    session_pseudonym: str
    tool_name: str
    argument_digest: str


@dataclass(slots=True)
class _StoredConfirmation:
    binding: ConfirmationBinding
    expires_at: datetime
    consumed_at: datetime | None = None


ConfirmationDecision = Literal["CONFIRMED", "INVALID", "EXPIRED", "REPLAYED", "MISMATCH"]


class ConfirmationStore(Protocol):
    """Atomic one-time confirmation storage; implementations store only token digests."""

    def issue(
        self, binding: ConfirmationBinding, *, expires_at: datetime, now: datetime
    ) -> str: ...

    def consume(
        self,
        token: str,
        binding: ConfirmationBinding,
        *,
        now: datetime,
    ) -> ConfirmationDecision: ...


class InMemoryConfirmationStore:
    """Process-local confirmation store for the single-replica demonstration service."""

    def __init__(self, *, retention_after_expiry: timedelta = timedelta(hours=1)):
        self._retention_after_expiry = retention_after_expiry
        self._confirmations: dict[str, _StoredConfirmation] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _prune_locked(self, now: datetime) -> None:
        threshold = now - self._retention_after_expiry
        stale = [
            token_digest
            for token_digest, confirmation in self._confirmations.items()
            if confirmation.expires_at < threshold
        ]
        for token_digest in stale:
            del self._confirmations[token_digest]

    def issue(self, binding: ConfirmationBinding, *, expires_at: datetime, now: datetime) -> str:
        with self._lock:
            self._prune_locked(now)
            while True:
                token = secrets.token_urlsafe(32)
                token_digest = self._token_digest(token)
                if token_digest not in self._confirmations:
                    break
            self._confirmations[token_digest] = _StoredConfirmation(
                binding=binding,
                expires_at=expires_at,
            )
        return token

    def consume(
        self,
        token: str,
        binding: ConfirmationBinding,
        *,
        now: datetime,
    ) -> ConfirmationDecision:
        token_digest = self._token_digest(token)
        with self._lock:
            confirmation = self._confirmations.get(token_digest)
            if confirmation is None:
                return "INVALID"
            if confirmation.consumed_at is not None:
                return "REPLAYED"
            if now >= confirmation.expires_at:
                return "EXPIRED"
            expected = confirmation.binding
            matches = (
                hmac.compare_digest(expected.actor_pseudonym, binding.actor_pseudonym)
                and hmac.compare_digest(expected.session_pseudonym, binding.session_pseudonym)
                and hmac.compare_digest(expected.tool_name, binding.tool_name)
                and hmac.compare_digest(expected.argument_digest, binding.argument_digest)
            )
            if not matches:
                return "MISMATCH"
            # The compare and state transition share one lock, so exactly one caller can consume.
            confirmation.consumed_at = now
            return "CONFIRMED"


class ToolAuthorizationDenied(PermissionError):
    pass


class ToolConfirmationNotAvailable(ValueError):
    pass


class RateLimitExceeded(RuntimeError):
    pass


class RateLimiter(Protocol):
    def check(self, subject: str, now: datetime) -> None: ...


class SlidingWindowRateLimiter:
    def __init__(self, limit: int, window: timedelta = timedelta(hours=1)):
        self.limit = limit
        self.window = window
        self.events: dict[str, deque[datetime]] = defaultdict(deque)

    def check(self, subject: str, now: datetime) -> None:
        queue = self.events[subject]
        threshold = now - self.window
        while queue and queue[0] <= threshold:
            queue.popleft()
        if len(queue) >= self.limit:
            raise RateLimitExceeded(f"rate limit of {self.limit} requests per hour exceeded")
        queue.append(now)


class AzureTableSlidingWindowRateLimiter:
    """Cross-replica limiter using an ETag-protected event window per pseudonym."""

    def __init__(
        self,
        endpoint: str,
        table_name: str,
        *,
        limit: int,
        managed_identity_client_id: str | None,
        window: timedelta = timedelta(hours=1),
        client: TableClient | None = None,
        max_attempts: int = 5,
    ):
        if limit < 1 or max_attempts < 1:
            raise ValueError("rate-limit settings must be positive")
        if client is not None:
            self.client = client
        else:
            credential = (
                ManagedIdentityCredential(client_id=managed_identity_client_id)
                if managed_identity_client_id
                else DefaultAzureCredential()
            )
            self.client = TableClient(
                endpoint=endpoint,
                table_name=table_name,
                credential=credential,
            )
        self.limit = limit
        self.window = window
        self.max_attempts = max_attempts

    def _events(self, entity: dict[str, object], threshold: datetime) -> list[datetime]:
        try:
            raw = json.loads(str(entity.get("eventsJson", "[]")))
        except json.JSONDecodeError as exc:
            raise RateLimitExceeded("rate-limit state is invalid; request denied") from exc
        if not isinstance(raw, list):
            raise RateLimitExceeded("rate-limit state is invalid; request denied")
        events: list[datetime] = []
        for value in raw:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError as exc:
                raise RateLimitExceeded("rate-limit state is invalid; request denied") from exc
            if parsed.tzinfo is None:
                raise RateLimitExceeded("rate-limit state is invalid; request denied")
            if parsed.astimezone(UTC) > threshold:
                events.append(parsed.astimezone(UTC))
        return events

    def check(self, subject: str, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("rate-limit time must be timezone-aware")
        current = now.astimezone(UTC)
        threshold = current - self.window
        for _attempt in range(self.max_attempts):
            try:
                entity = self.client.get_entity(partition_key="ASSISTANT", row_key=subject)
            except ResourceNotFoundError:
                try:
                    self.client.create_entity(
                        {
                            "PartitionKey": "ASSISTANT",
                            "RowKey": subject,
                            "eventsJson": json.dumps([current.isoformat()]),
                            "updatedAt": current,
                        }
                    )
                    return
                except ResourceExistsError:
                    continue
            events = self._events(entity, threshold)
            if len(events) >= self.limit:
                raise RateLimitExceeded(
                    f"rate limit of {self.limit} requests per hour exceeded"
                )
            events.append(current)
            replacement = {
                "PartitionKey": "ASSISTANT",
                "RowKey": subject,
                "eventsJson": json.dumps([value.isoformat() for value in events]),
                "updatedAt": current,
            }
            metadata = getattr(entity, "metadata", {})
            try:
                self.client.update_entity(
                    replacement,
                    mode=UpdateMode.REPLACE,
                    etag=metadata.get("etag"),
                    match_condition=MatchConditions.IfNotModified,
                )
                return
            except ResourceModifiedError:
                continue
        raise RateLimitExceeded("rate-limit state contention; request denied")


class PolicyAssistantService:
    def __init__(
        self,
        *,
        index: PolicyIndex,
        model: ModelAdapter,
        pseudonymization_secret: str,
        requests_per_hour: int = 10,
        rate_limiter: RateLimiter | None = None,
        confirmation_ttl: timedelta = timedelta(minutes=5),
        confirmation_store: ConfirmationStore | None = None,
        clock: Callable[[], datetime] | None = None,
        telemetry_sink: OperationalTelemetrySink | None = None,
    ):
        if confirmation_ttl <= timedelta(0):
            raise ValueError("confirmation_ttl must be positive")
        self.index = index
        self.model = model
        self.secret = pseudonymization_secret.encode("utf-8")
        self.rate_limiter = rate_limiter or SlidingWindowRateLimiter(requests_per_hour)
        self.confirmation_ttl = confirmation_ttl
        self.confirmation_store = confirmation_store or InMemoryConfirmationStore()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.telemetry_sink = telemetry_sink
        self.synthetic_requests: dict[str, dict[str, str]] = {}
        self.operational_events: list[OperationalEvent] = []

    def _pseudonym(self, raw: str) -> str:
        return hmac.new(self.secret, raw.encode("utf-8"), hashlib.sha256).hexdigest()[:24]

    def _now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            raise RuntimeError("assistant clock must return a timezone-aware datetime")
        return now.astimezone(UTC)

    @staticmethod
    def _has_required_role(tool_name: str, app_roles: Collection[str]) -> bool:
        required_roles = CONSEQUENTIAL_TOOL_ROLES.get(tool_name, frozenset())
        return bool(required_roles.intersection(app_roles))

    @staticmethod
    def _missing_arguments(tool: ToolRequest) -> frozenset[str]:
        required = CONSEQUENTIAL_TOOL_REQUIRED_ARGUMENTS.get(tool.name, frozenset())
        return required.difference(tool.arguments)

    def _confirmation_binding(
        self,
        tool: ToolRequest,
        *,
        user_subject: str,
        session_id: str,
    ) -> ConfirmationBinding:
        return ConfirmationBinding(
            actor_pseudonym=self._pseudonym(user_subject),
            session_pseudonym=self._pseudonym(session_id),
            tool_name=tool.name,
            argument_digest=canonical_argument_digest(tool.arguments),
        )

    def prepare_tool_confirmation(
        self,
        tool: ToolRequest,
        *,
        user_subject: str,
        session_id: str,
        app_roles: Collection[str],
    ) -> ToolConfirmation:
        """Prepare a short-lived confirmation for one authorized, exact request.

        The caller must supply app roles obtained from its authenticated principal. Model output,
        the client-controlled ``consequential`` flag, and the deprecated confirmation boolean do
        not participate in the authorization decision.
        """

        if tool.name not in CONSEQUENTIAL_TOOL_ROLES:
            raise ToolConfirmationNotAvailable("this tool does not require confirmation")
        if not self._has_required_role(tool.name, app_roles):
            raise ToolAuthorizationDenied("the authenticated principal lacks the required app role")
        missing = self._missing_arguments(tool)
        if missing:
            raise ToolConfirmationNotAvailable("required tool arguments are missing")
        if not 8 <= len(session_id) <= 128:
            raise ToolConfirmationNotAvailable("session_id must contain 8 to 128 characters")

        now = self._now()
        binding = self._confirmation_binding(
            tool,
            user_subject=user_subject,
            session_id=session_id,
        )
        expires_at = now + self.confirmation_ttl
        token = self.confirmation_store.issue(binding, expires_at=expires_at, now=now)
        return ToolConfirmation(
            confirmation_token=token,
            tool_name=tool.name,
            argument_digest=binding.argument_digest,
            expires_at=expires_at,
        )

    @staticmethod
    def _confirmation_rejection(
        tool_name: str,
        decision: ConfirmationState,
    ) -> ToolExecution:
        reasons = {
            "INVALID": "confirmation token is invalid",
            "EXPIRED": "confirmation token has expired",
            "REPLAYED": "confirmation token has already been used",
            "MISMATCH": "confirmation token does not match this exact request",
        }
        return ToolExecution(
            name=tool_name,
            authorization="ALLOWED",
            confirmation=decision,
            status="REJECTED",
            result={"reason": reasons.get(decision, "valid confirmation is required")},
        )

    def _execute_tool(
        self,
        request: ChatRequest,
        *,
        user_subject: str,
        app_roles: Collection[str],
        now: datetime,
    ) -> ToolExecution | None:
        tool = request.requested_tool
        if tool is None:
            return None
        if tool.name == "policy_lookup":
            result = self.index.lookup(
                tool.arguments.get("document_id", ""), tool.arguments.get("section_id")
            )
            return ToolExecution(
                name=tool.name,
                authorization="NOT_REQUIRED",
                confirmation="NOT_REQUIRED",
                status="EXECUTED" if result else "REJECTED",
                result=result or {"reason": "policy section not found"},
            )
        if not self._has_required_role(tool.name, app_roles):
            return ToolExecution(
                name=tool.name,
                authorization="DENIED",
                confirmation="MISSING",
                status="REJECTED",
                result={"reason": "the authenticated principal lacks the required app role"},
            )
        if self._missing_arguments(tool):
            return ToolExecution(
                name=tool.name,
                authorization="ALLOWED",
                confirmation="MISSING",
                status="REJECTED",
                result={"reason": "required fields are missing"},
            )
        if request.tool_confirmation_token is None:
            prepared = self.prepare_tool_confirmation(
                tool,
                user_subject=user_subject,
                session_id=request.session_id,
                app_roles=app_roles,
            )
            return ToolExecution(
                name=tool.name,
                authorization="ALLOWED",
                confirmation="MISSING",
                status="REJECTED",
                result={
                    "reason": "explicit confirmation with the server-issued token is required",
                    "confirmation_token": prepared.confirmation_token,
                    "argument_digest": prepared.argument_digest,
                    "expires_at": prepared.expires_at.isoformat(),
                },
            )
        binding = self._confirmation_binding(
            tool,
            user_subject=user_subject,
            session_id=request.session_id,
        )
        decision = self.confirmation_store.consume(
            request.tool_confirmation_token,
            binding,
            now=now,
        )
        if decision != "CONFIRMED":
            return self._confirmation_rejection(tool.name, decision)

        request_id = new_id("AEX")
        self.synthetic_requests[request_id] = {**tool.arguments, "status": "PENDING_REVIEW"}
        return ToolExecution(
            name=tool.name,
            authorization="ALLOWED",
            confirmation="CONFIRMED",
            status="EXECUTED",
            result={"request_id": request_id, "status": "PENDING_REVIEW"},
        )

    @staticmethod
    def _input_guardrail(message: str) -> tuple[str | None, tuple[str, ...]]:
        if DIRECT_INJECTION_PATTERN.search(message):
            return (
                "I cannot follow requests to reveal or override hidden instructions.",
                ("DIRECT_PROMPT_INJECTION_BLOCKED",),
            )
        if SENSITIVE_SUBMISSION_PATTERN.search(message):
            return (
                "Do not submit passwords, credentials, secrets, or production information.",
                ("SENSITIVE_DATA_SUBMISSION_BLOCKED",),
            )
        if SENSITIVE_DISCLOSURE_PATTERN.search(message):
            return (
                "I cannot disclose another evaluation's raw content or private identifiers.",
                ("SENSITIVE_DATA_DISCLOSURE_BLOCKED",),
            )
        if GOVERNANCE_DECISION_PATTERN.search(message):
            return (
                "I cannot make assurance conclusions, close findings, approve exceptions, or act "
                "on production access.",
                ("GOVERNANCE_DECISION_BLOCKED",),
            )
        if AMBIGUOUS_POLICY_PATTERN.search(message):
            return (
                "Please identify the data activity, classification, or decision you need guidance "
                "about so I can select the relevant policy.",
                ("AMBIGUOUS_POLICY_SCOPE",),
            )
        if OUT_OF_SCOPE_PATTERN.search(message):
            return (
                "That request is outside this assistant's synthetic policy-question scope.",
                ("OUT_OF_SCOPE_REQUEST_BLOCKED",),
            )
        if ABUSIVE_REQUEST_PATTERN.search(message):
            return (
                "I cannot generate abusive or harassing content.",
                ("ABUSIVE_CONTENT_REQUEST_BLOCKED",),
            )
        return None, ()

    @staticmethod
    def _deny_requested_tool(request: ChatRequest) -> ToolExecution | None:
        if request.requested_tool is None:
            return None
        return ToolExecution(
            name=request.requested_tool.name,
            authorization="DENIED",
            confirmation="NOT_REQUIRED",
            status="REJECTED",
            result={"reason": "input guardrail blocked tool execution"},
        )

    async def _record_operational_event(self, event: OperationalEvent) -> None:
        self.operational_events.append(event)
        # Structured event deliberately excludes raw request and response content.
        LOGGER.info("policy_assistant_event", extra={"aica_event": event.model_dump(mode="json")})
        if self.telemetry_sink is not None:
            try:
                await self.telemetry_sink.publish_operational_event(event)
            except Exception as exc:  # Telemetry cannot break the interaction path.
                LOGGER.error(
                    "policy_assistant_telemetry_failure",
                    extra={
                        "correlation_id": event.correlation_id,
                        "error_type": type(exc).__name__,
                    },
                )

    async def chat(
        self,
        request: ChatRequest,
        *,
        user_subject: str,
        app_roles: Collection[str] = (),
    ) -> ChatResponse:
        now = self._now()
        pseudonymous_user = self._pseudonym(user_subject)
        started = time.monotonic()
        correlation_id = new_id("corr")
        evaluation_id = new_id("eval")
        citations: list[Citation] = []
        retrieval_guardrails: list[str] = []
        input_guardrails: tuple[str, ...] = ()
        tool: ToolExecution | None = None
        try:
            self.rate_limiter.check(pseudonymous_user, now)
            refusal, input_guardrails = self._input_guardrail(request.message)
            if "DIRECT_PROMPT_INJECTION_BLOCKED" not in input_guardrails:
                citations, retrieval_guardrails = self.index.search(request.message)
            tool = (
                self._deny_requested_tool(request)
                if refusal is not None
                else self._execute_tool(
                    request,
                    user_subject=user_subject,
                    app_roles=app_roles,
                    now=now,
                )
            )
            model_answer = (
                await self.model.answer(request.message, tuple(citations))
                if refusal is None
                else ModelAnswer(
                    text=refusal,
                    model="application-guardrail",
                    version="1.0.0",
                )
            )
        except Exception as exc:
            latency_ms = round((time.monotonic() - started) * 1000)
            event = OperationalEvent(
                correlation_id=correlation_id,
                evaluation_id=evaluation_id,
                pseudonymous_user_id=pseudonymous_user,
                pseudonymous_session_id=self._pseudonym(request.session_id),
                model=type(self.model).__name__,
                model_version="unavailable",
                retrieval_document_ids=tuple(item.document_id for item in citations),
                retrieval_classifications=tuple(item.classification for item in citations),
                latency_ms=latency_ms,
                status="ERROR",
                input_tokens=None,
                output_tokens=None,
                guardrail_outcomes=(
                    *retrieval_guardrails,
                    *input_guardrails,
                    f"INTERACTION_ERROR:{type(exc).__name__}",
                ),
                requested_tool=request.requested_tool.name if request.requested_tool else None,
                authorization_decision=tool.authorization if tool else None,
                confirmation_state=tool.confirmation if tool else None,
                tool_result_status=tool.status if tool else None,
                occurred_at=now,
            )
            await self._record_operational_event(event)
            raise
        latency_ms = round((time.monotonic() - started) * 1000)
        guardrails = (
            tuple(retrieval_guardrails) + input_guardrails + model_answer.guardrail_outcomes
        )
        response = ChatResponse(
            correlation_id=correlation_id,
            evaluation_id=evaluation_id,
            answer=model_answer.text,
            citations=tuple(citations),
            tool=tool,
            guardrail_outcomes=tuple(guardrails),
            model=model_answer.model,
            model_version=model_answer.version,
            latency_ms=latency_ms,
            input_tokens=model_answer.input_tokens,
            output_tokens=model_answer.output_tokens,
            generated_at=now,
        )
        event = OperationalEvent(
            correlation_id=correlation_id,
            evaluation_id=evaluation_id,
            pseudonymous_user_id=pseudonymous_user,
            pseudonymous_session_id=self._pseudonym(request.session_id),
            model=model_answer.model,
            model_version=model_answer.version,
            retrieval_document_ids=tuple(item.document_id for item in citations),
            retrieval_classifications=tuple(item.classification for item in citations),
            latency_ms=latency_ms,
            status=(
                "REJECTED"
                if refusal is not None or (tool is not None and tool.status == "REJECTED")
                else "SUCCESS"
            ),
            input_tokens=model_answer.input_tokens,
            output_tokens=model_answer.output_tokens,
            guardrail_outcomes=tuple(guardrails),
            requested_tool=request.requested_tool.name if request.requested_tool else None,
            authorization_decision=tool.authorization if tool else None,
            confirmation_state=tool.confirmation if tool else None,
            tool_result_status=tool.status if tool else None,
            occurred_at=now,
        )
        await self._record_operational_event(event)
        return response
