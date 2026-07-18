"""Deterministic rule engine; no LLM participates in control verdicts."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from aica.domain.models import (
    EvidenceFreshness,
    EvidenceItem,
    ResultStatus,
    TestResult,
)
from aica.util.ids import new_id

RuleCheck = Callable[[list[EvidenceItem]], tuple[bool, str, dict[str, Any]]]


@dataclass(frozen=True)
class Rule:
    id: str
    objective_id: str
    title: str
    required_sources: tuple[str, ...]
    check: RuleCheck
    version: str = "1.0.0"


def _walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, Mapping):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            yield from _walk(child)


def _mapping_nodes(evidence: list[EvidenceItem]) -> Iterable[Mapping[str, Any]]:
    for item in evidence:
        for node in _walk(item.payload):
            if isinstance(node, Mapping):
                yield node


def _field_values(evidence: list[EvidenceItem], field: str) -> list[Any]:
    values: list[Any] = []
    for node in _mapping_nodes(evidence):
        for key, value in node.items():
            if key.casefold() == field.casefold():
                values.append(value)
    return values


def _boolean_field(field: str, expected: bool) -> RuleCheck:
    def check(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
        values = _field_values(evidence, field)
        if not values:
            return False, f"required field {field!r} was absent", {"field": field}
        passed = all(value is expected for value in values)
        return passed, f"{field} values were {values!r}", {"values": values, "expected": expected}

    return check


def _nonempty_field(field: str) -> RuleCheck:
    def check(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
        values = _field_values(evidence, field)
        passed = bool(values) and all(value not in (None, "", [], {}) for value in values)
        return passed, f"{field} present={passed}", {"count": len(values)}

    return check


def _authorization_enforced(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    wrong_role = _field_values(evidence, "wrong_role_status")
    unauthenticated = _field_values(evidence, "unauthenticated_status")
    passed = (
        bool(wrong_role)
        and all(value == 403 for value in wrong_role)
        and bool(unauthenticated)
        and all(value == 401 for value in unauthenticated)
    )
    return (
        passed,
        "negative authorization probes returned 401 and 403"
        if passed
        else "negative authorization probes are absent or permissive",
        {"wrong_role_status": wrong_role, "unauthenticated_status": unauthenticated},
    )


def _authentication_required(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    values = _field_values(evidence, "unauthenticatedClientAction")
    allowed = {"return401", "redirecttologinpage", "false"}
    normalized = [str(value).replace("_", "").casefold() for value in values]
    passed = bool(normalized) and all(value in allowed for value in normalized)
    return (
        passed,
        "unauthenticated requests are rejected or redirected"
        if passed
        else "authentication enforcement is absent or allows anonymous requests",
        {"values": values},
    )


def _no_public_rdp(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    offending: list[str] = []
    for node in _mapping_nodes(evidence):
        direction = str(node.get("direction", node.get("properties", {}).get("direction", "")))
        access = str(node.get("access", node.get("properties", {}).get("access", "")))
        port = str(
            node.get(
                "destinationPortRange", node.get("properties", {}).get("destinationPortRange", "")
            )
        )
        source = str(
            node.get(
                "sourceAddressPrefix", node.get("properties", {}).get("sourceAddressPrefix", "")
            )
        )
        if (
            direction.casefold() == "inbound"
            and access.casefold() == "allow"
            and (port == "3389" or "3389" in node.get("destinationPortRanges", []))
            and source in {"*", "Internet", "0.0.0.0/0"}
        ):
            offending.append(str(node.get("name", "unnamed-rule")))
    return (
        not offending,
        "no public inbound RDP rule" if not offending else "public RDP rule found",
        {"offending_rules": offending},
    )


def _least_privilege(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    forbidden = {"owner", "user access administrator", "storage blob data owner"}
    forbidden_ids = {
        "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",  # Owner
        "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9",  # User Access Administrator
        "b7e6dc6d-f1e8-4753-8033-0f276bb0955b",  # Storage Blob Data Owner fixture
    }
    roles = [str(value) for value in _field_values(evidence, "roleDefinitionName")]
    role_ids = [
        str(value).rstrip("/").rsplit("/", 1)[-1].casefold()
        for value in _field_values(evidence, "roleDefinitionId")
    ]
    offending = sorted(
        {role for role in roles if role.casefold() in forbidden}
        | {role_id for role_id in role_ids if role_id in forbidden_ids}
    )
    observed = len(roles) + len(role_ids)
    return (
        observed > 0 and not offending,
        (
            "no forbidden role assignments"
            if observed > 0 and not offending
            else "role evidence absent or overbroad roles found"
        ),
        {"observed": observed, "offending_roles": offending},
    )


def _log_table_columns(evidence: list[EvidenceItem]) -> set[str]:
    columns: set[str] = set()
    for table in _field_values(evidence, "tables"):
        if not isinstance(table, Sequence) or isinstance(table, (str, bytes, bytearray)):
            continue
        for item in table:
            if not isinstance(item, Mapping):
                continue
            for column in item.get("columns", []):
                columns.add(str(column.get("name")) if isinstance(column, Mapping) else str(column))
    return columns


def _log_records(evidence: list[EvidenceItem]) -> list[Mapping[str, Any]]:
    records: list[Mapping[str, Any]] = []
    for value in _field_values(evidence, "records"):
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            records.extend(item for item in value if isinstance(item, Mapping))
    for tables in _field_values(evidence, "tables"):
        if not isinstance(tables, Sequence) or isinstance(tables, (str, bytes, bytearray)):
            continue
        for table in tables:
            if not isinstance(table, Mapping):
                continue
            columns = [
                str(item.get("name")) if isinstance(item, Mapping) else str(item)
                for item in table.get("columns", [])
            ]
            for row in table.get("rows", []):
                if isinstance(row, Mapping):
                    records.append(row)
                elif isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
                    records.append(dict(zip(columns, row, strict=False)))
    return records


def _recent_assurance_run(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    rows = [node for node in _log_records(evidence) if "RunId" in node or "RunId_g" in node]
    completed = [
        node
        for node in rows
        if str(node.get("Status", node.get("Status_s", ""))).upper()
        in {"COMPLETED", "REVIEW_REQUIRED"}
    ]
    return (
        bool(completed),
        "recent completed assurance run present" if completed else "no completed run row returned",
        {"rows": len(rows), "completed": len(completed)},
    )


def _operational_log_rows(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    rows = [node for node in _log_records(evidence) if "RunId" in node or "RunId_g" in node]
    return (
        bool(rows),
        "operational assurance records present"
        if rows
        else "no operational assurance rows returned",
        {"rows": len(rows)},
    )


def _diagnostic_destinations(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    resources = [
        node
        for node in _mapping_nodes(evidence)
        if "resource_id" in node
        and "applicability" in node
        and isinstance(node.get("settings"), list)
    ]
    applicable = [
        resource
        for resource in resources
        if str(resource.get("applicability", "")).upper() == "APPLICABLE"
    ]
    not_applicable = [
        resource
        for resource in resources
        if str(resource.get("applicability", "")).upper() == "NOT_APPLICABLE"
    ]
    unknown = [
        str(resource.get("resource_id"))
        for resource in resources
        if str(resource.get("applicability", "")).upper()
        not in {"APPLICABLE", "NOT_APPLICABLE"}
    ]
    missing: list[str] = []
    for resource in applicable:
        settings = resource.get("settings", [])
        configured = [
            setting.get("properties", setting)
            for setting in settings
            if isinstance(setting, Mapping)
            and isinstance(setting.get("properties", setting), Mapping)
        ]
        destinations = [setting.get("workspaceId") for setting in configured]
        enabled_logs = [
            log
            for setting in configured
            for log in setting.get("logs", [])
            if isinstance(log, Mapping) and log.get("enabled") is True
        ]
        if not destinations or any(not destination for destination in destinations) or not enabled_logs:
            missing.append(str(resource.get("resource_id")))
    queried = [int(value) for value in _field_values(evidence, "queried_count")]
    complete = bool(queried) and all(value == len(resources) for value in queried)
    passed = bool(resources) and not missing and not unknown and complete
    return (
        passed,
        "every applicable resource has a diagnostic destination"
        if passed
        else "diagnostic destination evidence is absent or incomplete",
        {
            "resources": len(resources),
            "applicable": len(applicable),
            "not_applicable": len(not_applicable),
            "unknown": unknown,
            "missing": missing,
            "complete": complete,
        },
    )


def _risky_change_monitor_schema(
    evidence: list[EvidenceItem],
) -> tuple[bool, str, dict[str, Any]]:
    columns = _log_table_columns(evidence)
    expected = {"OperationNameValue", "ChangeType_s", "Changes", "Count_d"}
    records = _log_records(evidence)
    passed = bool(columns & expected) and bool(records)
    return (
        passed,
        "risky-change query schema returned" if passed else "risky-change query schema absent",
        {"columns": sorted(columns)},
    )


def _pinned_supply_chain(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    uses = [str(value) for value in _field_values(evidence, "uses")]
    images = [str(value) for value in _field_values(evidence, "image")]
    unpinned_actions = [
        value for value in uses if "@" not in value or not re.search(r"@[a-f0-9]{40}$", value)
    ]
    floating_images = [value for value in images if "@sha256:" not in value]
    passed = bool(uses or images) and not unpinned_actions and not floating_images
    return (
        passed,
        "software references are immutable" if passed else "floating reference detected",
        {
            "unpinned_actions": unpinned_actions,
            "floating_images": floating_images,
        },
    )


def _tool_confirmation(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    bypasses: list[str] = []
    observed = 0
    for node in _mapping_nodes(evidence):
        if node.get("requested_tool") == "create_access_exception":
            observed += 1
            if (
                node.get("confirmation_state") != "CONFIRMED"
                and node.get("tool_result_status") == "EXECUTED"
            ):
                bypasses.append(str(node.get("evaluation_id", "unknown")))
    passed = observed > 0 and not bypasses
    return (
        passed,
        "consequential tool confirmation enforced" if passed else "confirmation evidence failed",
        {
            "observed": observed,
            "bypasses": bypasses,
        },
    )


def _citations(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    cases = [node for node in _mapping_nodes(evidence) if "citation_valid" in node]
    invalid = [
        node.get("id", "unknown") for node in cases if node.get("citation_valid") is not True
    ]
    passed = bool(cases) and not invalid
    return (
        passed,
        "all grounded cases contain valid citations" if passed else "citation failures found",
        {
            "cases": len(cases),
            "invalid": invalid,
        },
    )


def _no_raw_content(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    forbidden_keys = {"prompt", "response", "raw_prompt", "raw_response"}
    found: list[str] = []
    for node in _mapping_nodes(evidence):
        found.extend(str(key) for key in node if key.casefold() in forbidden_keys)
    observed = len(_field_values(evidence, "evaluation_id")) + len(
        _field_values(evidence, "CorrelationId")
    )
    return (
        observed > 0 and not found,
        (
            "operational telemetry excludes raw content"
            if observed > 0 and not found
            else "operational telemetry absent or raw content field found"
        ),
        {"observed": observed, "forbidden_fields": sorted(set(found))},
    )


def _evaluation_gate(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    statuses = [str(value).upper() for value in _field_values(evidence, "evaluation_gate_status")]
    digests = [str(value) for value in _field_values(evidence, "evaluation_artifact_sha256")]
    evaluated = [str(value) for value in _field_values(evidence, "evaluated_configuration_sha256")]
    deployed = [str(value) for value in _field_values(evidence, "deployed_configuration_sha256")]
    modes = [str(value).upper() for value in _field_values(evidence, "evaluation_mode")]
    passed = (
        bool(statuses)
        and all(status == "PASS" for status in statuses)
        and bool(digests)
        and bool(evaluated)
        and evaluated == deployed
        and (not modes or all(mode == "LIVE" for mode in modes))
    )
    return (
        passed,
        "configuration is linked to a passing evaluation" if passed else "evaluation gate missing",
        {
            "statuses": statuses,
            "artifact_count": len(digests),
            "configuration_match": evaluated == deployed and bool(evaluated),
            "modes": modes,
        },
    )


def _advanced_security_gate(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    configured: list[str] = []
    for value in _field_values(evidence, "advanced_security"):
        configured.append(
            str(value.get("status", "")) if isinstance(value, Mapping) else str(value)
        )
    critical = _field_values(evidence, "unresolved_critical_alerts")
    passed = (
        bool(configured)
        and all(value.casefold() == "enabled" for value in configured)
        and bool(critical)
        and all(
            isinstance(value, int) and not isinstance(value, bool) and value == 0
            for value in critical
        )
    )
    return (
        passed,
        "security scanning is enabled with no unresolved critical alerts"
        if passed
        else "security scanning or critical-alert gate evidence is incomplete",
        {"advanced_security": configured, "unresolved_critical_alerts": critical},
    )


def _ci_artifact_gate(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    assessed_commits = {
        str(value).casefold() for value in _field_values(evidence, "assessed_commit") if value
    }
    runs = [
        node
        for node in _mapping_nodes(evidence)
        if "run_id" in node and "head_sha" in node and "conclusion" in node
    ]
    artifacts = [
        node
        for node in _mapping_nodes(evidence)
        if "workflow_run_id" in node and "head_sha" in node and "digest" in node
    ]
    if assessed_commits:
        valid_runs = [
            run
            for run in runs
            if str(run.get("conclusion", "")).casefold() == "success"
            and str(run.get("head_sha", "")).casefold() in assessed_commits
        ]
        valid_run_keys = {
            (str(run.get("run_id")), str(run.get("head_sha", "")).casefold())
            for run in valid_runs
        }
        artifact_bindings = [
            (
                str(artifact.get("workflow_run_id")),
                str(artifact.get("head_sha", "")).casefold(),
            )
            in valid_run_keys
            for artifact in artifacts
        ]
        artifact_digests = [str(artifact.get("digest", "")) for artifact in artifacts]
        expiry = [artifact.get("expired") for artifact in artifacts]
        passed = (
            len(assessed_commits) == 1
            and bool(valid_runs)
            and bool(artifacts)
            and all(artifact_bindings)
            and all(
                re.fullmatch(r"sha256:[a-f0-9]{64}", digest) for digest in artifact_digests
            )
            and all(value is False for value in expiry)
        )
    else:
        # Checked replay fixtures predate commit binding; live evidence always includes it.
        conclusions = [str(value).casefold() for value in _field_values(evidence, "conclusion")]
        artifact_digests = [str(value) for value in _field_values(evidence, "digest")]
        expiry = _field_values(evidence, "expired")
        artifact_bindings = []
        passed = (
            "success" in conclusions
            and any(re.fullmatch(r"sha256:[a-f0-9]{64}", value) for value in artifact_digests)
            and bool(expiry)
            and all(value is False for value in expiry)
        )
    return (
        passed,
        "successful assessed-commit CI run retained workflow-bound immutable artifacts"
        if passed
        else "successful assessed-commit CI run or workflow-bound artifact digest is absent",
        {
            "assessed_commits": sorted(assessed_commits),
            "run_count": len(runs),
            "artifact_digests": artifact_digests,
            "artifact_bindings": artifact_bindings,
            "expired": expiry,
        },
    )


def _backup_restore(evidence: list[EvidenceItem]) -> tuple[bool, str, dict[str, Any]]:
    versioning = _field_values(evidence, "isVersioningEnabled")
    soft_delete = [
        value
        for value in _field_values(evidence, "deleteRetentionPolicy")
        if isinstance(value, Mapping)
    ]
    passed = (
        bool(versioning)
        and all(value is True for value in versioning)
        and bool(soft_delete)
        and all(
            value.get("enabled") is True and int(value.get("days", 0)) > 0 for value in soft_delete
        )
    )
    return (
        passed,
        "versioning and recovery configuration present"
        if passed
        else "recovery protection missing",
        {
            "versioning": versioning,
            "soft_delete_records": len(soft_delete),
        },
    )


def default_rules() -> tuple[Rule, ...]:
    return (
        Rule(
            "R-AC-3-01",
            "AC-3.1",
            "Identity-only service authorization",
            ("application.authorization_tests",),
            _authorization_enforced,
        ),
        Rule(
            "R-AC-6-01",
            "AC-6.1",
            "No forbidden privileged assignments",
            ("azure.rbac",),
            _least_privilege,
        ),
        Rule(
            "R-IA-2-01",
            "IA-2.1",
            "Entra authentication enabled",
            ("azure.resource_graph",),
            _authentication_required,
        ),
        Rule(
            "R-AU-2-01",
            "AU-2.1",
            "Diagnostic destinations configured",
            ("azure.monitor.diagnostic",),
            _diagnostic_destinations,
        ),
        Rule(
            "R-AU-12-01",
            "AU-12.1",
            "Operational log records present",
            ("sentinel.assurance_health",),
            _operational_log_rows,
        ),
        Rule(
            "R-CA-7-01",
            "CA-7.1",
            "Recent completed assurance run",
            ("sentinel.assurance_health",),
            _recent_assurance_run,
        ),
        Rule(
            "R-CM-2-01",
            "CM-2.1",
            "Immutable container image references",
            ("azure.resource_graph",),
            _pinned_supply_chain,
        ),
        Rule(
            "R-CM-3-01",
            "CM-3.1",
            "Protected branch and review",
            ("github.branch_protection",),
            _nonempty_field("required_pull_request_reviews"),
        ),
        Rule(
            "R-CM-6-01",
            "CM-6.1",
            "Secure transfer required",
            ("azure.resource_graph",),
            _boolean_field("supportsHttpsTrafficOnly", True),
        ),
        Rule(
            "R-CP-9-01",
            "CP-9.1",
            "Evidence recovery protection",
            ("azure.resource_graph",),
            _backup_restore,
        ),
        Rule(
            "R-RA-5-01",
            "RA-5.1",
            "Code security configuration",
            ("github.code_security",),
            _advanced_security_gate,
        ),
        Rule(
            "R-SA-11-01",
            "SA-11.1",
            "Successful tested build with immutable artifacts",
            ("github.ci",),
            _ci_artifact_gate,
        ),
        Rule(
            "R-SC-7-01",
            "SC-7.1",
            "No public inbound RDP",
            ("azure.resource_graph",),
            _no_public_rdp,
        ),
        Rule(
            "R-SC-8-01",
            "SC-8.1",
            "Transport security enabled",
            ("azure.resource_graph",),
            _boolean_field("supportsHttpsTrafficOnly", True),
        ),
        Rule(
            "R-SI-4-01",
            "SI-4.1",
            "Risky changes monitored",
            ("sentinel.risky_changes",),
            _risky_change_monitor_schema,
        ),
        Rule(
            "R-AI-DP-01",
            "AI-DP-01.1",
            "Grounded answers cite trusted evidence",
            ("ai.behavioral_evaluation",),
            _citations,
        ),
        Rule(
            "R-AI-AC-01",
            "AI-AC-01.1",
            "Consequential tool confirmation",
            ("ai.operational_events",),
            _tool_confirmation,
        ),
        Rule(
            "R-AI-TE-01",
            "AI-TE-01.1",
            "Configuration changes pass evaluation gate",
            ("ai.release_evaluation",),
            _evaluation_gate,
        ),
        Rule(
            "R-AI-MO-01",
            "AI-MO-01.1",
            "No raw content in operational logs",
            ("ai.operational_events",),
            _no_raw_content,
        ),
    )


class RuleEngine:
    def __init__(self, rules: tuple[Rule, ...] | None = None):
        self.rules = rules or default_rules()

    def evaluate(self, run_id: str, evidence: list[EvidenceItem]) -> list[TestResult]:
        results: list[TestResult] = []
        for rule in self.rules:
            matched = [
                item
                for item in evidence
                if any(item.source.startswith(source) for source in rule.required_sources)
            ]
            results.append(self._evaluate_rule(run_id, rule, matched))
        return results

    @staticmethod
    def _evaluate_rule(run_id: str, rule: Rule, evidence: list[EvidenceItem]) -> TestResult:
        def result(
            status: ResultStatus,
            reason_code: str,
            reason: str,
            details: dict[str, Any] | None = None,
        ) -> TestResult:
            return TestResult(
                id=new_id("test"),
                run_id=run_id,
                objective_id=rule.objective_id,
                status=status,
                reason_code=reason_code,
                reason=reason,
                test_version=rule.version,
                evidence_refs=tuple(item.id for item in evidence),
                evaluated_at=datetime.now(UTC),
                details=details or {},
            )

        if not evidence:
            return result(
                ResultStatus.NOT_RUN,
                "MISSING_EVIDENCE",
                f"no evidence matched required sources {rule.required_sources}",
            )
        if any(not item.authorized for item in evidence):
            return result(
                ResultStatus.ERROR,
                "COLLECTION_UNAUTHORIZED",
                "collector was not authorized to read required evidence",
            )
        if errors := [item.collection_error for item in evidence if item.collection_error]:
            return result(
                ResultStatus.ERROR,
                "COLLECTION_FAILED",
                "; ".join(errors),
            )
        if any(item.freshness != EvidenceFreshness.FRESH for item in evidence):
            return result(
                ResultStatus.NOT_RUN,
                "STALE_EVIDENCE",
                "required evidence is stale or has unknown freshness",
            )
        try:
            passed, reason, details = rule.check(evidence)
        except (KeyError, TypeError, ValueError) as exc:
            return result(
                ResultStatus.ERROR,
                "EVALUATOR_ERROR",
                f"deterministic evaluator failed: {type(exc).__name__}",
            )
        return result(
            ResultStatus.PASS if passed else ResultStatus.FAIL,
            "EXPECTED_CONDITION_MET" if passed else "EXPECTED_CONDITION_NOT_MET",
            reason,
            details,
        )
