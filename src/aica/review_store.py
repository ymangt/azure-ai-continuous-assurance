"""Append-only review-event read model and package overlay."""

from __future__ import annotations

import json
from typing import Any, Protocol, cast

from azure.data.tables import TableClient
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

EFFECTIVENESS_DECISIONS = {
    "EFFECTIVE",
    "PARTIALLY_EFFECTIVE",
    "INEFFECTIVE",
    "NOT_CONCLUDED",
}


class ReviewEventStore(Protocol):
    def list_events(self) -> list[dict[str, Any]]: ...


class EmptyReviewEventStore:
    def list_events(self) -> list[dict[str, Any]]:
        return []


class AzureTableReviewEventStore:
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

    def list_events(self) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for row in self.client.query_entities("RowKey ne 'STATE'"):
            try:
                event = json.loads(str(row["eventJson"]))
            except (KeyError, TypeError, json.JSONDecodeError):
                continue
            if isinstance(event, dict):
                event["_event_type"] = str(row.get("eventType", ""))
                event["_event_version"] = int(row.get("version", 1))
                events.append(event)
        return events


def overlay_review_events(package: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    """Project append-only decisions, exceptions, and remediations without mutation."""

    enriched = cast(dict[str, Any], json.loads(json.dumps(package)))
    run = enriched.get("run", enriched.get("assessment_run", {}))
    package_digest = str(run.get("manifest_digest", ""))
    all_decisions = [event for event in events if event.get("_event_type") == "REVIEW_DECISION"]
    current_versions: dict[str, int] = {}
    for event in events:
        subject_id = str(event.get("subject_id", event.get("finding_id", "")))
        if subject_id:
            current_versions[subject_id] = max(
                current_versions.get(subject_id, 1),
                int(event.get("version", event.get("_event_version", 1))),
            )
    decisions = [
        {key: value for key, value in event.items() if key not in {"_event_type", "_event_version"}}
        for event in all_decisions
        if event.get("artifact_hash") == package_digest
    ]
    exceptions = [
        {key: value for key, value in event.items() if key not in {"_event_type", "_event_version"}}
        for event in events
        if event.get("_event_type") == "EXCEPTION" and event.get("artifact_hash") == package_digest
    ]
    lifecycle_run_ids = {str(run.get("prior_run_id", ""))}
    lifecycle_run_ids.update(str(item.get("run_id", "")) for item in enriched.get("findings", []))
    for retest in enriched.get("retests", []):
        lifecycle_run_ids.update(
            {
                str(retest.get("before_run_id", "")),
                str(retest.get("after_run_id", "")),
            }
        )
    lifecycle_run_ids.discard("")
    remediations = [
        {key: value for key, value in event.items() if key not in {"_event_type", "_event_version"}}
        for event in events
        if event.get("_event_type") == "REMEDIATION"
        and (
            event.get("artifact_hash") == package_digest
            or str(event.get("artifact_run_id", "")) in lifecycle_run_ids
        )
    ]

    existing_decisions = list(enriched.get("decisions", []))
    existing_exceptions = list(enriched.get("exceptions", []))
    existing_remediations = list(enriched.get("remediations", []))
    known_decisions = {str(item.get("id")) for item in existing_decisions}
    known_exceptions = {str(item.get("id")) for item in existing_exceptions}
    known_remediations = {str(item.get("id")) for item in existing_remediations}
    existing_decisions.extend(
        item for item in decisions if str(item.get("id")) not in known_decisions
    )
    existing_exceptions.extend(
        item for item in exceptions if str(item.get("id")) not in known_exceptions
    )
    existing_remediations.extend(
        item for item in remediations if str(item.get("id")) not in known_remediations
    )
    enriched["decisions"] = existing_decisions
    enriched["exceptions"] = existing_exceptions
    enriched["remediations"] = existing_remediations

    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for decision in existing_decisions:
        key = (str(decision.get("subject_type")), str(decision.get("subject_id")))
        if int(decision.get("version", 0)) >= int(latest.get(key, {}).get("version", -1)):
            latest[key] = decision

    for assessment in enriched.get("assessments", []):
        assessment["review_version"] = current_versions.get(str(assessment.get("objective_id")), 1)
        decision = latest.get(("CONTROL", str(assessment.get("objective_id"))))
        if decision:
            conclusion = str(decision.get("decision", "")).upper()
            if conclusion in {"ACCEPTED", "REJECTED"}:
                assessment["review_state"] = conclusion
            elif conclusion in EFFECTIVENESS_DECISIONS:
                assessment["review_state"] = "ACCEPTED"
                assessment["reviewer_conclusion"] = conclusion
            assessment["reviewer"] = decision.get("reviewer")
            assessment["reviewer_rationale"] = decision.get("rationale")
            assessment["review_decision_id"] = decision.get("id")

    for finding in enriched.get("findings", []):
        finding["review_version"] = current_versions.get(str(finding.get("id")), 1)
        decision = latest.get(("FINDING", str(finding.get("id"))))
        if decision:
            disposition = str(decision.get("decision", "")).upper()
            if disposition in {"CLOSE", "CLOSED"}:
                finding["status"] = "CLOSED"
            elif disposition in {"REOPEN", "REOPENED"}:
                finding["status"] = "REOPENED"
            elif disposition == "READY_FOR_RETEST":
                finding["status"] = "READY_FOR_RETEST"
            if disposition in {"CLOSE", "CLOSED", "REOPEN", "REOPENED"}:
                recommendation = "CLOSE" if disposition in {"CLOSE", "CLOSED"} else "REOPEN"
                for retest in reversed(enriched.get("retests", [])):
                    retest_finding = str(retest.get("finding_id", retest.get("finding_ref", "")))
                    if (
                        retest_finding == str(finding.get("id"))
                        and str(retest.get("decision", "")).upper() == recommendation
                    ):
                        retest["review_state"] = "ACCEPTED"
                        retest["review_decision_id"] = decision.get("id")
                        break
        finding_id = str(finding.get("id"))
        latest_remediation = max(
            (
                remediation
                for remediation in existing_remediations
                if str(remediation.get("finding_id")) == finding_id
                and (
                    remediation.get("artifact_hash") == package_digest
                    or str(remediation.get("artifact_run_id", "")) in lifecycle_run_ids
                )
            ),
            key=lambda item: int(item.get("version", 0)),
            default=None,
        )
        decision_version = int(decision.get("version", 0)) if decision else 0
        has_accepted_disposition = any(
            str(retest.get("finding_id", retest.get("finding_ref", ""))) == finding_id
            and str(retest.get("review_state", "")).upper() == "ACCEPTED"
            and str(retest.get("decision", "")).upper() in {"CLOSE", "REOPEN"}
            for retest in enriched.get("retests", [])
        )
        if (
            latest_remediation
            and str(latest_remediation.get("status")) == "READY_FOR_RETEST"
            and int(latest_remediation.get("version", 0)) > decision_version
            and not has_accepted_disposition
        ):
            finding["status"] = "READY_FOR_RETEST"
    return enriched
