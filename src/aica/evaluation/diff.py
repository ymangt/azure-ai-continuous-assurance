"""Immutable baseline-to-retest comparison and retest record creation."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from aica.domain.models import (
    AssessmentPackage,
    ControlObjective,
    EvidenceFreshness,
    Finding,
    ResultStatus,
    Retest,
    ReviewState,
    StrictRecord,
    TestResult,
)
from aica.util.ids import new_id


class ResultChange(StrictRecord):
    objective_id: str
    category: str
    from_status: ResultStatus | None
    to_status: ResultStatus | None


class AssessmentDiff(StrictRecord):
    from_run_id: str
    to_run_id: str
    changes: tuple[ResultChange, ...]
    counts: dict[str, int] = Field(default_factory=dict)


def _objective_for_finding(
    finding: Finding,
    objectives: Sequence[ControlObjective],
    results: Sequence[TestResult],
) -> str | None:
    """Resolve a finding to one objective without guessing through a tie."""
    objective_by_id = {objective.id: objective for objective in objectives}
    if finding.objective_id in objective_by_id:
        return finding.objective_id

    results_by_objective = {result.objective_id: result for result in results}
    scored: list[tuple[int, str]] = []
    searchable = f"{finding.title}\n{finding.criteria}".casefold()
    for objective in objectives:
        if objective.source_control not in finding.affected_controls:
            continue
        score = 1  # control-level match
        if finding.criteria.strip().casefold() == objective.objective.strip().casefold():
            score += 16
        if objective.id.casefold() in searchable:
            score += 8
        result = results_by_objective.get(objective.id)
        if result is not None:
            if result.status == ResultStatus.FAIL:
                score += 4
            if set(result.evidence_refs) & set(finding.evidence_refs):
                score += 2
        scored.append((score, objective.id))

    if not scored:
        return None
    scored.sort(reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def link_findings_to_objectives(
    findings: Sequence[Finding],
    objectives: Sequence[ControlObjective],
    results: Sequence[TestResult],
) -> tuple[Finding, ...]:
    """Add explicit objective links to newly generated findings."""
    linked: list[Finding] = []
    for finding in findings:
        objective_id = _objective_for_finding(finding, objectives, results)
        linked.append(
            finding
            if objective_id is None or finding.objective_id == objective_id
            else finding.model_copy(update={"objective_id": objective_id})
        )
    return tuple(linked)


def _result_freshness(after: AssessmentPackage, result: TestResult) -> EvidenceFreshness:
    assessment = next(
        (item for item in after.assessments if item.objective_id == result.objective_id),
        None,
    )
    if assessment is None:
        return EvidenceFreshness.UNKNOWN
    if assessment.evidence_freshness != EvidenceFreshness.FRESH:
        return assessment.evidence_freshness
    if not result.evidence_refs:
        return EvidenceFreshness.UNKNOWN

    evidence_by_id = {item.id: item for item in after.evidence}
    referenced = [evidence_by_id.get(reference) for reference in result.evidence_refs]
    if any(item is None for item in referenced):
        return EvidenceFreshness.UNKNOWN
    if any(item is not None and item.freshness == EvidenceFreshness.STALE for item in referenced):
        return EvidenceFreshness.STALE
    if any(
        item is not None
        and (
            item.freshness != EvidenceFreshness.FRESH
            or not item.authorized
            or item.collection_error is not None
        )
        for item in referenced
    ):
        return EvidenceFreshness.UNKNOWN
    return EvidenceFreshness.FRESH


def build_retests(
    before: AssessmentPackage,
    after: AssessmentPackage,
    *,
    finding_ids: Sequence[str] | None = None,
    tested_at: datetime | None = None,
) -> tuple[Retest, ...]:
    """Create suggested retest outcomes without mutating earlier findings.

    A closure suggestion is emitted only when the matching current objective is
    an evidence-backed PASS and every linked evidence item is fresh, authorized,
    and free from collection errors. All ambiguous, missing, stale, errored, or
    unavailable cases fail closed to a REOPEN suggestion.
    """
    if after.run.prior_run_id != before.run.id:
        raise ValueError("retest package does not reference the supplied prior run")

    findings_by_id = {finding.id: finding for finding in before.findings}
    if finding_ids is None:
        selected = tuple(
            finding
            for finding in before.findings
            if finding.status in {"OPEN", "READY_FOR_RETEST", "REOPENED"}
        )
    else:
        requested = tuple(dict.fromkeys(finding_ids))
        unknown = sorted(set(requested) - set(findings_by_id))
        if unknown:
            raise ValueError(f"unknown prior finding IDs: {', '.join(unknown)}")
        selected = tuple(findings_by_id[finding_id] for finding_id in requested)

    current_results = {result.objective_id: result for result in after.test_results}
    timestamp = tested_at or after.run.ended_at or datetime.now(UTC)
    retests: list[Retest] = []
    for finding in selected:
        objective_id = _objective_for_finding(
            finding,
            before.objectives,
            before.test_results,
        )
        if objective_id not in current_results:
            objective_id = _objective_for_finding(
                finding,
                after.objectives,
                after.test_results,
            )
        current = current_results.get(objective_id) if objective_id else None
        if current is None:
            rationale = (
                "No unambiguous matching objective and current result were available; "
                "the retest is NOT_RUN and the finding must remain open pending reviewer action."
            )
            retests.append(
                Retest(
                    id=new_id("retest"),
                    finding_id=finding.id,
                    before_run_id=before.run.id,
                    after_run_id=after.run.id,
                    objective_id=objective_id,
                    evidence_refs=(),
                    result=ResultStatus.NOT_RUN,
                    decision="REOPEN",
                    evidence_freshness=EvidenceFreshness.UNKNOWN,
                    review_state=ReviewState.SUGGESTED,
                    rationale=rationale,
                    tested_at=timestamp,
                )
            )
            continue

        freshness = _result_freshness(after, current)
        is_closable = current.status == ResultStatus.PASS and freshness == EvidenceFreshness.FRESH
        decision: Literal["CLOSE", "REOPEN"]
        if is_closable:
            result_status = ResultStatus.PASS
            decision = "CLOSE"
            rationale = (
                f"Suggested closure pending reviewer: objective {current.objective_id} passed "
                f"with fresh, authorized evidence. {current.reason}"
            )
        else:
            # A nominal PASS is deliberately downgraded when its evidence chain
            # is not fresh and complete; missing/stale evidence never becomes a
            # PASS merely because an upstream result claimed one.
            result_status = (
                ResultStatus.NOT_RUN if current.status == ResultStatus.PASS else current.status
            )
            decision = "REOPEN"
            rationale = (
                f"Suggested reopening or continued-open status pending reviewer: objective "
                f"{current.objective_id} is {result_status.value} with {freshness.value} evidence. "
                f"{current.reason}"
            )
        retests.append(
            Retest(
                id=new_id("retest"),
                finding_id=finding.id,
                before_run_id=before.run.id,
                after_run_id=after.run.id,
                objective_id=current.objective_id,
                test_result_id=current.id,
                evidence_refs=current.evidence_refs,
                result=result_status,
                decision=decision,
                evidence_freshness=freshness,
                review_state=ReviewState.SUGGESTED,
                rationale=rationale,
                tested_at=timestamp,
            )
        )
    return tuple(retests)


def diff_packages(before: AssessmentPackage, after: AssessmentPackage) -> AssessmentDiff:
    old = {item.objective_id: item.status for item in before.test_results}
    new = {item.objective_id: item.status for item in after.test_results}
    changes: list[ResultChange] = []
    for objective_id in sorted(set(old) | set(new)):
        previous = old.get(objective_id)
        current = new.get(objective_id)
        if previous is None:
            category = "new"
        elif current is None:
            category = "removed"
        elif previous == ResultStatus.FAIL and current == ResultStatus.PASS:
            category = "resolved"
        elif previous == ResultStatus.PASS and current == ResultStatus.FAIL:
            category = "regressed"
        elif current == ResultStatus.ERROR:
            category = "errored"
        elif current == ResultStatus.NOT_RUN:
            category = "stale_or_not_run"
        else:
            category = "unchanged"
        changes.append(
            ResultChange(
                objective_id=objective_id,
                category=category,
                from_status=previous,
                to_status=current,
            )
        )
    counts: dict[str, int] = {}
    for change in changes:
        counts[change.category] = counts.get(change.category, 0) + 1
    return AssessmentDiff(
        from_run_id=before.run.id,
        to_run_id=after.run.id,
        changes=tuple(changes),
        counts=counts,
    )
