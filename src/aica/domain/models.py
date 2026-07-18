"""Canonical, immutable records for the assurance lifecycle.

The models intentionally reject extra fields and enforce the audit invariants at
the boundary.  Persistence adapters may change, but these semantics may not.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

Sha256 = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
NonEmpty = Annotated[str, Field(min_length=1)]


class StrictRecord(BaseModel):
    """Base for append-only records serialized into evidence packages."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class ResultStatus(StrEnum):
    PASS = "PASS"  # noqa: S105 - assurance verdict, not a credential
    FAIL = "FAIL"
    ERROR = "ERROR"
    NOT_RUN = "NOT_RUN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Effectiveness(StrEnum):
    EFFECTIVE = "EFFECTIVE"
    PARTIALLY_EFFECTIVE = "PARTIALLY_EFFECTIVE"
    INEFFECTIVE = "INEFFECTIVE"
    NOT_CONCLUDED = "NOT_CONCLUDED"


class EvidenceFreshness(StrEnum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class RunStatus(StrEnum):
    QUEUED = "QUEUED"
    COLLECTING = "COLLECTING"
    EVALUATING = "EVALUATING"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AssessmentMethod(StrEnum):
    EXAMINE = "EXAMINE"
    INTERVIEW = "INTERVIEW"
    TEST = "TEST"
    HYBRID = "HYBRID"


class Classification(StrEnum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED_TEST_EVIDENCE = "RESTRICTED_TEST_EVIDENCE"


class SystemDataFlow(StrictRecord):
    id: NonEmpty
    source: NonEmpty
    destination: NonEmpty
    data: NonEmpty
    classification: Classification
    protection: NonEmpty
    retention: NonEmpty


class SystemInventoryItem(StrictRecord):
    name: NonEmpty
    type: NonEmpty
    plane: NonEmpty
    region: NonEmpty
    lifecycle: NonEmpty


class SystemIdentity(StrictRecord):
    name: NonEmpty
    purpose: NonEmpty
    privilege: NonEmpty
    authentication: NonEmpty
    assigned_scope: NonEmpty


class SystemClassification(StrictRecord):
    classification: Classification
    description: NonEmpty
    handling: NonEmpty


class SystemRecord(StrictRecord):
    """Versioned, runtime system-boundary record included in every package."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    system_id: NonEmpty
    name: NonEmpty
    boundary: NonEmpty
    data_classification: NonEmpty
    data_flows: tuple[SystemDataFlow, ...] = Field(min_length=1)
    trust_boundaries: tuple[NonEmpty, ...] = Field(min_length=1)
    inventory: tuple[SystemInventoryItem, ...] = Field(min_length=1)
    identities: tuple[SystemIdentity, ...] = Field(min_length=1)
    classifications: tuple[SystemClassification, ...] = Field(min_length=1)
    shared_responsibility: NonEmpty
    exclusions: tuple[NonEmpty, ...] = Field(min_length=1)


class ReviewState(StrEnum):
    SUGGESTED = "SUGGESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class Severity(StrEnum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskTreatment(StrEnum):
    MITIGATE = "MITIGATE"
    ACCEPT = "ACCEPT"
    TRANSFER = "TRANSFER"
    AVOID = "AVOID"


class AssessmentRun(StrictRecord):
    id: NonEmpty
    trigger: Literal["manual", "scheduled", "change", "retest", "fixture"]
    scope: tuple[str, ...]
    observation_window_start: datetime
    observation_window_end: datetime
    git_commit: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{7,40}$")]
    collector_version: NonEmpty
    evaluator_version: NonEmpty
    started_at: datetime
    ended_at: datetime | None = None
    status: RunStatus
    manifest_digest: Sha256 | None = None
    estimated_cost_cad: Annotated[float, Field(ge=0)] = 0
    prior_run_id: str | None = None

    @model_validator(mode="after")
    def validate_times(self) -> AssessmentRun:
        if self.observation_window_end < self.observation_window_start:
            raise ValueError("observation window end precedes its start")
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("run end precedes its start")
        if self.trigger == "retest" and not self.prior_run_id:
            raise ValueError("retest runs must reference the prior run")
        return self


class ControlObjective(StrictRecord):
    id: NonEmpty
    source_control: NonEmpty
    title: NonEmpty
    objective: NonEmpty
    methods: tuple[AssessmentMethod, ...]
    subject_selector: NonEmpty
    cadence: NonEmpty
    evidence_requirements: tuple[str, ...]
    owner: NonEmpty
    automated: bool
    limitations: tuple[str, ...] = ()
    crosswalk: dict[str, tuple[str, ...]] = Field(default_factory=dict)


class EvidenceItem(StrictRecord):
    id: NonEmpty
    source: NonEmpty
    scope: tuple[str, ...]
    captured_at: datetime
    observation_window_start: datetime
    observation_window_end: datetime
    query_digest: Sha256
    collector_version: NonEmpty
    private_artifact_uri: str | HttpUrl
    media_type: NonEmpty
    sha256: Sha256
    sanitized_sha256: Sha256 | None = None
    blob_version: str | None = None
    classification: Classification
    freshness: EvidenceFreshness
    redaction_profile: NonEmpty
    authorized: bool = True
    collection_error: str | None = None
    payload: dict[str, Any] | list[Any] | str | int | float | bool | None = None

    @model_validator(mode="after")
    def validate_collection_state(self) -> EvidenceItem:
        if not self.authorized and not self.collection_error:
            raise ValueError("unauthorized evidence must record the collection error")
        if self.observation_window_end < self.observation_window_start:
            raise ValueError("evidence observation window is reversed")
        return self


class TestResult(StrictRecord):
    id: NonEmpty
    run_id: NonEmpty
    objective_id: NonEmpty
    status: ResultStatus
    reason_code: NonEmpty
    reason: NonEmpty
    test_version: NonEmpty
    evidence_refs: tuple[str, ...] = ()
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def passes_require_evidence(self) -> TestResult:
        if self.status == ResultStatus.PASS and not self.evidence_refs:
            raise ValueError("PASS requires at least one evidence reference")
        if self.status in {ResultStatus.ERROR, ResultStatus.NOT_RUN} and self.reason_code == "OK":
            raise ValueError("unavailable tests require a non-OK reason")
        return self


class ControlAssessment(StrictRecord):
    id: NonEmpty
    run_id: NonEmpty
    objective_id: NonEmpty
    design_effectiveness: Effectiveness
    operating_effectiveness: Effectiveness
    coverage_percent: Annotated[float, Field(ge=0, le=100)]
    conclusion: Effectiveness
    reviewer: str | None = None
    rationale: NonEmpty
    evidence_freshness: EvidenceFreshness
    review_state: ReviewState = ReviewState.SUGGESTED

    @model_validator(mode="after")
    def stale_evidence_cannot_conclude(self) -> ControlAssessment:
        if (
            self.evidence_freshness != EvidenceFreshness.FRESH
            and self.conclusion != Effectiveness.NOT_CONCLUDED
        ):
            raise ValueError("stale or unknown evidence requires NOT_CONCLUDED")
        return self


class Observation(StrictRecord):
    id: NonEmpty
    run_id: NonEmpty
    objective_id: NonEmpty
    condition: NonEmpty
    evidence_refs: tuple[str, ...]
    observed_at: datetime


class Finding(StrictRecord):
    id: NonEmpty
    run_id: NonEmpty
    objective_id: str | None = None
    title: NonEmpty
    criteria: NonEmpty
    condition: NonEmpty
    cause: NonEmpty
    consequence: NonEmpty
    affected_controls: tuple[str, ...]
    affected_assets: tuple[str, ...]
    severity: Severity
    severity_rationale: NonEmpty
    evidence_refs: tuple[str, ...]
    status: Literal["OPEN", "READY_FOR_RETEST", "CLOSED", "REOPENED"] = "OPEN"


def risk_severity(score: int) -> Severity:
    if score <= 4:
        return Severity.LOW
    if score <= 9:
        return Severity.MODERATE
    if score <= 16:
        return Severity.HIGH
    return Severity.CRITICAL


class Risk(StrictRecord):
    id: NonEmpty
    finding_id: NonEmpty
    statement: NonEmpty
    likelihood: Annotated[int, Field(ge=1, le=5)]
    impact: Annotated[int, Field(ge=1, le=5)]
    inherent_score: Annotated[int, Field(ge=1, le=25)]
    inherent_rating: Severity
    residual_likelihood: Annotated[int, Field(ge=1, le=5)]
    residual_impact: Annotated[int, Field(ge=1, le=5)]
    residual_score: Annotated[int, Field(ge=1, le=25)]
    residual_rating: Severity
    confidence: Literal["LOW", "MODERATE", "HIGH"]
    treatment: RiskTreatment
    owner: NonEmpty
    rationale: NonEmpty

    @model_validator(mode="after")
    def validate_scores(self) -> Risk:
        if self.inherent_score != self.likelihood * self.impact:
            raise ValueError("inherent score must equal likelihood x impact")
        if self.residual_score != self.residual_likelihood * self.residual_impact:
            raise ValueError("residual score must equal likelihood x impact")
        if self.inherent_rating != risk_severity(self.inherent_score):
            raise ValueError("inherent rating does not match the 5x5 rubric")
        if self.residual_rating != risk_severity(self.residual_score):
            raise ValueError("residual rating does not match the 5x5 rubric")
        return self


class ExceptionRecord(StrictRecord):
    id: NonEmpty
    finding_id: NonEmpty
    approver: NonEmpty
    rationale: NonEmpty
    compensating_controls: tuple[str, ...]
    approved_at: datetime
    expires_at: datetime
    review_cadence: NonEmpty
    artifact_hash: Sha256 | None = None

    @model_validator(mode="after")
    def expiry_is_future(self) -> ExceptionRecord:
        if self.expires_at <= self.approved_at:
            raise ValueError("exception must expire after approval")
        return self


class Remediation(StrictRecord):
    id: NonEmpty
    finding_id: NonEmpty
    owner: NonEmpty
    action: NonEmpty
    target_date: datetime
    commit_or_pr: NonEmpty
    evidence_refs: tuple[str, ...] = ()
    status: Literal["PLANNED", "IN_PROGRESS", "READY_FOR_RETEST", "VERIFIED"]
    recorded_by: str | None = None
    recorded_at: datetime | None = None
    artifact_run_id: str | None = None
    artifact_hash: Sha256 | None = None
    expected_version: Annotated[int, Field(ge=0)] | None = None
    version: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def readiness_has_evidence_and_consistent_event_metadata(self) -> Remediation:
        if self.status == "READY_FOR_RETEST" and not self.evidence_refs:
            raise ValueError("a remediation ready for retest requires evidence")
        event_fields = (
            self.recorded_by,
            self.recorded_at,
            self.artifact_run_id,
            self.artifact_hash,
            self.expected_version,
            self.version,
        )
        if any(value is not None for value in event_fields):
            if any(value is None for value in event_fields):
                raise ValueError("append-only remediation event metadata must be complete")
            if self.expected_version is None or self.version is None:
                raise ValueError("append-only remediation event versions must be present")
            if self.version != self.expected_version + 1:
                raise ValueError("remediation version must increment expected_version exactly once")
        return self


class Retest(StrictRecord):
    id: NonEmpty
    finding_id: NonEmpty
    before_run_id: NonEmpty
    after_run_id: NonEmpty
    objective_id: str | None = None
    test_result_id: str | None = None
    evidence_refs: tuple[str, ...]
    result: ResultStatus
    decision: Literal["CLOSE", "REOPEN"]
    evidence_freshness: EvidenceFreshness | None = None
    review_state: ReviewState = ReviewState.SUGGESTED
    review_decision_id: str | None = None
    rationale: NonEmpty
    tested_at: datetime

    @model_validator(mode="after")
    def closure_requires_fresh_pass(self) -> Retest:
        if self.result == ResultStatus.PASS:
            if not self.evidence_refs:
                raise ValueError("a PASS retest requires evidence")
            if self.evidence_freshness not in {None, EvidenceFreshness.FRESH}:
                raise ValueError("a PASS retest requires fresh evidence")
        if self.decision == "CLOSE":
            if self.result != ResultStatus.PASS:
                raise ValueError("a CLOSE suggestion requires a PASS retest")
            # None remains valid for checked-in records authored before the
            # freshness field was introduced. New runtime retests always set it.
            if self.evidence_freshness not in {None, EvidenceFreshness.FRESH}:
                raise ValueError("a CLOSE suggestion requires fresh evidence")
        if self.review_state == ReviewState.ACCEPTED and not self.review_decision_id:
            raise ValueError("an accepted retest requires a reviewer decision reference")
        return self


class ReviewDecision(StrictRecord):
    id: NonEmpty
    reviewer: NonEmpty
    subject_type: Literal["RUN", "CONTROL", "FINDING", "RISK", "EXCEPTION", "AI_SUGGESTION"]
    subject_id: NonEmpty
    prior_state: NonEmpty
    decision: NonEmpty
    rationale: NonEmpty
    timestamp: datetime
    artifact_hash: Sha256
    expected_version: Annotated[int, Field(ge=0)]
    version: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_version(self) -> ReviewDecision:
        if self.version != self.expected_version + 1:
            raise ValueError("decision version must increment expected_version exactly once")
        return self


class AssessmentPackage(StrictRecord):
    run: AssessmentRun
    system: SystemRecord
    objectives: tuple[ControlObjective, ...]
    evidence: tuple[EvidenceItem, ...]
    test_results: tuple[TestResult, ...]
    assessments: tuple[ControlAssessment, ...]
    observations: tuple[Observation, ...] = ()
    findings: tuple[Finding, ...] = ()
    risks: tuple[Risk, ...] = ()
    exceptions: tuple[ExceptionRecord, ...] = ()
    remediations: tuple[Remediation, ...] = ()
    retests: tuple[Retest, ...] = ()
    decisions: tuple[ReviewDecision, ...] = ()

    @model_validator(mode="after")
    def references_are_traceable(self) -> AssessmentPackage:
        evidence_ids = {item.id for item in self.evidence}
        objective_ids = {objective.id for objective in self.objectives}
        objective_controls = {
            objective.id: objective.source_control for objective in self.objectives
        }
        test_ids = {result.id for result in self.test_results}
        finding_ids = {finding.id for finding in self.findings}
        risk_ids = {risk.id for risk in self.risks}
        exception_ids = {exception.id for exception in self.exceptions}
        for result in self.test_results:
            if result.run_id != self.run.id:
                raise ValueError(f"test {result.id} is not bound to package run {self.run.id}")
            if result.objective_id not in objective_ids:
                raise ValueError(f"test {result.id} references unknown objective")
            missing = set(result.evidence_refs) - evidence_ids
            if missing:
                raise ValueError(f"test {result.id} references unknown evidence: {sorted(missing)}")
        for assessment in self.assessments:
            if assessment.run_id != self.run.id:
                raise ValueError(
                    f"assessment {assessment.id} is not bound to package run {self.run.id}"
                )
            if assessment.objective_id not in objective_ids:
                raise ValueError(f"assessment {assessment.id} references unknown objective")
        for observation in self.observations:
            if observation.run_id != self.run.id:
                raise ValueError(
                    f"observation {observation.id} is not bound to package run {self.run.id}"
                )
            if observation.objective_id not in objective_ids:
                raise ValueError(f"observation {observation.id} references unknown objective")
            missing = set(observation.evidence_refs) - evidence_ids
            if missing:
                raise ValueError(
                    f"observation {observation.id} references unknown evidence: {sorted(missing)}"
                )
        for finding in self.findings:
            if finding.objective_id not in objective_ids:
                raise ValueError(f"finding {finding.id} references unknown objective")
            source_control = objective_controls[finding.objective_id]
            if source_control not in finding.affected_controls:
                raise ValueError(
                    f"finding {finding.id} does not include objective source control {source_control}"
                )
            if finding.run_id == self.run.id:
                missing = set(finding.evidence_refs) - evidence_ids
                if missing:
                    raise ValueError(
                        f"finding {finding.id} references unknown current-run evidence: "
                        f"{sorted(missing)}"
                    )
        for risk in self.risks:
            if risk.finding_id not in finding_ids:
                raise ValueError(f"risk {risk.id} references unknown finding")
        findings_with_risk = {risk.finding_id for risk in self.risks}
        missing_risks = finding_ids - findings_with_risk
        if missing_risks:
            raise ValueError(f"findings have no linked risk: {sorted(missing_risks)}")
        for exception in self.exceptions:
            if exception.finding_id not in finding_ids:
                raise ValueError(f"exception {exception.id} references unknown finding")
        for remediation in self.remediations:
            if remediation.finding_id not in finding_ids:
                raise ValueError(f"remediation {remediation.id} references unknown finding")
            if remediation.artifact_run_id in {None, self.run.id}:
                missing = set(remediation.evidence_refs) - evidence_ids
                if missing:
                    raise ValueError(
                        f"remediation {remediation.id} references unknown evidence: "
                        f"{sorted(missing)}"
                    )
        for retest in self.retests:
            if retest.finding_id not in finding_ids:
                raise ValueError(f"retest {retest.id} references unknown finding")
            if retest.objective_id not in objective_ids:
                raise ValueError(f"retest {retest.id} references unknown objective")
            if retest.after_run_id == self.run.id:
                if retest.test_result_id not in test_ids:
                    raise ValueError(f"retest {retest.id} references unknown current-run test")
                missing = set(retest.evidence_refs) - evidence_ids
                if missing:
                    raise ValueError(
                        f"retest {retest.id} references unknown current-run evidence: "
                        f"{sorted(missing)}"
                    )
        known_subjects = {
            "RUN": {self.run.id},
            "CONTROL": objective_ids | set(objective_controls.values()),
            "FINDING": finding_ids,
            "RISK": risk_ids,
            "EXCEPTION": exception_ids,
        }
        for decision in self.decisions:
            if decision.subject_type == "AI_SUGGESTION":
                continue
            if decision.subject_id not in known_subjects[decision.subject_type]:
                raise ValueError(
                    f"decision {decision.id} references unknown {decision.subject_type.lower()}"
                )
        return self
