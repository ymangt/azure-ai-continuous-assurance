#!/usr/bin/env python3
"""Validate checked-in assurance artifacts, counts, traceability, and signatures."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator
from score_mapping_benchmark import calculate

from aica.collectors.ai import (
    compose_behavioral_evidence_payload,
    load_mapping_metrics,
    load_mapping_suggestion,
)
from aica.domain.models import AssessmentPackage
from aica.evaluation.behavioral import BehavioralEvaluationError, validate_behavioral_result
from aica.evidence.manifest import SignedManifest, verify_manifest
from aica.evidence.redaction import public_boundary_violations
from aica.scenarios import ScenarioCampaignArtifact
from aica.util.canonical import sha256_value

ROOT = Path(__file__).resolve().parents[2]


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_run(name: str, errors: list[str]) -> AssessmentPackage:
    root = ROOT / "data" / "sample-runs" / name
    package = AssessmentPackage.model_validate_json((root / "package.json").read_text(encoding="utf-8"))
    signed = SignedManifest.model_validate_json((root / "run-manifest.json").read_text(encoding="utf-8"))
    manifest_errors = verify_manifest(signed, root)
    errors.extend(f"{name} manifest: {error}" for error in manifest_errors)
    if not signed.key_id.startswith("local://"):
        errors.append(f"{name}: checked-in sample must use a local:// CI-only key")
    if len(package.objectives) != 35 or len(package.test_results) != 35:
        errors.append(f"{name}: package must contain 35 objectives and 35 results")
    evidence_ids = {item.id for item in package.evidence}
    result_ids = {item.id for item in package.test_results}
    finding_ids = {item.id for item in package.findings}
    risk_ids = {item.id for item in package.risks}
    for evidence in package.evidence:
        if evidence.private_artifact_uri != "private://withheld":
            errors.append(f"{name}:{evidence.id} exposes a private artifact URI")
        if evidence.sanitized_sha256 == evidence.sha256:
            errors.append(f"{name}:{evidence.id} reuses its private hash as the sanitized hash")
        if evidence.blob_version is not None:
            errors.append(f"{name}:{evidence.id} exposes a private blob version")
    lifecycle = read(root / "lifecycle.json")
    for finding in lifecycle["findings"]:
        if set(finding["evidence_refs"]) - evidence_ids:
            errors.append(f"{name}:{finding['finding_id']} has unknown evidence")
        if set(finding["test_result_refs"]) - result_ids:
            errors.append(f"{name}:{finding['finding_id']} has unknown result")
        if set(finding["risk_refs"]) - risk_ids:
            errors.append(f"{name}:{finding['finding_id']} has unknown risk")
    for risk in package.risks:
        if risk.finding_id not in finding_ids:
            errors.append(f"{name}:{risk.id} has unknown finding {risk.finding_id}")
    return package


def validate_retest_chain(
    baseline: AssessmentPackage,
    remediated: AssessmentPackage,
    errors: list[str],
) -> None:
    baseline_findings = {item.id: item for item in baseline.findings}
    current_findings = {item.id: item for item in remediated.findings}
    current_results = {item.id: item for item in remediated.test_results}
    current_evidence = {item.id for item in remediated.evidence}
    current_decisions = {item.id: item for item in remediated.decisions}
    remediated_findings = {item.finding_id for item in remediated.remediations}
    for finding_id in baseline_findings:
        if finding_id not in current_findings:
            errors.append(f"retest package dropped historical finding {finding_id}")
    for retest in remediated.retests:
        if retest.before_run_id != baseline.run.id or retest.after_run_id != remediated.run.id:
            errors.append(f"{retest.id}: before/after run links do not match signed packages")
        prior_finding = baseline_findings.get(retest.finding_id)
        if prior_finding is None:
            errors.append(f"{retest.id}: finding is not present in the signed baseline")
            continue
        result = current_results.get(retest.test_result_id or "")
        if result is None:
            errors.append(f"{retest.id}: current result link is missing or unknown")
        elif result.objective_id != retest.objective_id:
            errors.append(f"{retest.id}: result and objective links disagree")
        if prior_finding.objective_id != retest.objective_id:
            errors.append(f"{retest.id}: finding and retest objective links disagree")
        if set(retest.evidence_refs) - current_evidence:
            errors.append(f"{retest.id}: retest evidence is absent from the after package")
        if retest.finding_id not in remediated_findings:
            errors.append(f"{retest.id}: no remediation links the finding to the retest")
        if retest.review_state.value == "ACCEPTED":
            decision = current_decisions.get(retest.review_decision_id or "")
            if decision is None:
                errors.append(f"{retest.id}: accepted retest has no review decision")
            elif (
                decision.subject_type != "FINDING"
                or decision.subject_id != retest.finding_id
                or decision.decision != retest.decision
            ):
                errors.append(f"{retest.id}: review decision does not bind the recommendation")
    for finding in remediated.findings:
        if finding.status == "CLOSED" and not any(
            retest.finding_id == finding.id
            and retest.decision == "CLOSE"
            and retest.result.value == "PASS"
            and retest.evidence_freshness is not None
            and retest.evidence_freshness.value == "FRESH"
            and retest.review_state.value == "ACCEPTED"
            for retest in remediated.retests
        ):
            errors.append(f"{finding.id}: closed finding lacks an accepted fresh PASS retest")


def validate_signed_evaluation_binding(
    package: AssessmentPackage,
    behavior: dict,
    replay: dict,
    errors: list[str],
) -> None:
    """Reject drift between evaluation sources and the manifest-covered public read model."""

    evidence = [item for item in package.evidence if item.source == "AI_BEHAVIORAL_EVALUATION"]
    if len(evidence) != 1:
        errors.append("remediated package must contain exactly one signed AI evaluation")
        return
    baseline = read(
        ROOT / "data" / "collector-fixtures" / "baseline" / "ai.behavioral_evaluation.json"
    )
    baseline_by_id = {
        str(item["id"]): item for item in baseline.get("payload", {}).get("nodes", [])
    }
    try:
        expected = compose_behavioral_evidence_payload(
            cases=behavior,
            results=replay,
            mapping_metrics=load_mapping_metrics(
                ROOT / "data" / "mapping-benchmark" / "human-labeled-examples.json"
            ),
            suggested_mapping=load_mapping_suggestion(
                ROOT / "data" / "ai-evaluations" / "mapping-suggestion.json",
                run_id=package.run.id,
                evaluation_id=str(replay["evaluation_id"]),
            ),
            baseline_by_id=baseline_by_id,
        )
    except (BehavioralEvaluationError, KeyError, TypeError) as exc:
        errors.append(f"signed AI evaluation source binding is invalid: {exc}")
        return

    actual = evidence[0].payload
    if actual != expected:
        errors.append(
            "signed AI evaluation payload drifted from the behavioral cases, replay results, "
            "mapping metrics, suggestion, or baseline comparison"
        )
    if evidence[0].sanitized_sha256 != sha256_value(actual):
        errors.append("signed AI evaluation sanitized digest does not bind its payload")


def main() -> None:
    errors: list[str] = []
    for top_level in ("assurance", "data", "docs", "schemas"):
        for path in (ROOT / top_level).glob("**/*.json"):
            try:
                read(path)
            except Exception as exc:
                errors.append(f"invalid JSON {path.relative_to(ROOT)}: {exc}")

    profile = read(ROOT / "assurance" / "controls" / "control-profile.json")
    controls = profile["controls"]
    objectives = profile["objectives"]
    methods = Counter(item["method"] for item in objectives)
    if len(controls) != 25 or len({item["id"] for item in controls}) != 25:
        errors.append("control profile must contain 25 unique controls")
    if len(objectives) != 35 or len({item["id"] for item in objectives}) != 35:
        errors.append("control profile must contain 35 unique objectives")
    if methods != Counter({"AUTOMATED": 19, "HYBRID": 8, "MANUAL": 8}):
        errors.append(f"objective method counts drifted: {dict(methods)}")

    behavior = read(ROOT / "data" / "ai-evaluations" / "behavioral-cases.json")
    replay = read(ROOT / "data" / "ai-evaluations" / "replay-results.json")
    try:
        validate_behavioral_result(behavior, replay)
    except BehavioralEvaluationError as exc:
        errors.append(f"behavioral result artifact: {exc}")
    cases = {item["id"]: item for item in behavior["cases"]}
    if len(cases) < 40 or set(cases) != set(replay["results"]):
        errors.append("behavioral cases and replay results must have the same >=40 case IDs")
    for case_id, case in cases.items():
        actual = replay["results"][case_id]
        expected = case["expected"]
        computed = (
            actual["disposition"] == expected["disposition"]
            and actual["tool_execution"] == expected["tool_execution"]
            and actual["citation_valid"]
            and actual["scenario_valid"]
        )
        if actual["passed"] != computed:
            errors.append(f"{case_id}: replay passed flag does not match expected outcomes")

    benchmark = read(ROOT / "data" / "mapping-benchmark" / "human-labeled-examples.json")
    metrics = calculate(benchmark)
    if len(benchmark["examples"]) < 60:
        errors.append("mapping benchmark contains fewer than 60 examples")
    if round(metrics["precision"], 4) < benchmark["release_targets"]["precision"]:
        errors.append("mapping precision is below release target")
    if round(metrics["citation_validity"], 4) != 1.0:
        errors.append("mapping evidence-reference validity must be 1.0")

    corpus = read(ROOT / "data" / "policy-corpus" / "manifest.json")
    if not 15 <= len(corpus["documents"]) <= 25:
        errors.append("policy corpus must contain 15-25 documents")
    for item in corpus["documents"]:
        if not (ROOT / "data" / "policy-corpus" / item["path"]).exists():
            errors.append(f"missing corpus document {item['path']}")

    scenarios = list((ROOT / "data" / "scenarios").glob("SCN-*.json"))
    if len(scenarios) != 8:
        errors.append(f"expected 8 scenario specifications, found {len(scenarios)}")
    scenario_schema = read(ROOT / "schemas" / "scenario.schema.json")
    scenario_validator = Draft202012Validator(scenario_schema)
    for path in scenarios:
        scenario = read(path)
        for error in scenario_validator.iter_errors(scenario):
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            errors.append(f"{path.name}:{location}: {error.message}")
        if scenario["safety"]["data_classification"] != "SYNTHETIC":
            errors.append(f"{path.name}: scenario is not synthetic-only")

    try:
        campaign_artifact = ScenarioCampaignArtifact.model_validate(
            read(ROOT / "data" / "scenario-campaigns" / "controlled-execution.json")
        )
    except Exception as exc:
        errors.append(f"controlled scenario campaign artifact: {exc}")
    else:
        if any(item.execution.azure_live_evidence_checked_in for item in campaign_artifact.campaigns):
            errors.append("controlled scenario artifact makes an unsupported Azure-live claim")

    packages = {name: validate_run(name, errors) for name in ("baseline", "remediated")}
    validate_retest_chain(packages["baseline"], packages["remediated"], errors)
    validate_signed_evaluation_binding(packages["remediated"], behavior, replay, errors)

    for path in (ROOT / "data" / "sample-runs").glob("**/*.json"):
        violations = public_boundary_violations(path.read_text(encoding="utf-8"))
        if violations:
            errors.append(
                f"public-boundary violation in {path.relative_to(ROOT)}: "
                + ", ".join(violations)
            )

    if errors:
        raise SystemExit("artifact validation failed:\n- " + "\n- ".join(errors))
    print(
        "validated 25 controls, 35 objectives (19 automated/8 hybrid/8 manual), "
        f"{len(cases)} behavioral cases, {len(benchmark['examples'])} mapping examples, "
        f"{len(corpus['documents'])} policy documents, 8 scenarios, 2 signed packages"
    )


if __name__ == "__main__":
    main()
