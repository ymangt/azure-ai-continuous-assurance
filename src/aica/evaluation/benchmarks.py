"""Deterministic behavioral and evidence-mapping release gates."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, cast

from aica.evaluation.behavioral import BehavioralEvaluationError, load_behavioral_result

LABELS = ("SUPPORTS", "CONTRADICTS", "INSUFFICIENT", "ABSTAIN")
EVIDENCE_REFERENCE = re.compile(r"^(?:EVD|FIX|POL)-[A-Z0-9-]+$")


class BenchmarkGateError(RuntimeError):
    """Raised when a fixed release dataset is incomplete, inconsistent, or below target."""


def _load(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _rounded(value: float) -> float:
    return round(value, 4)


def _prf(true_positive: int, predicted_positive: int, actual_positive: int) -> tuple[float, ...]:
    precision = true_positive / predicted_positive if predicted_positive else 0.0
    recall = true_positive / actual_positive if actual_positive else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return _rounded(precision), _rounded(recall), _rounded(f1)


def score_behavioral(cases_path: Path, results_path: Path) -> dict[str, Any]:
    dataset = _load(cases_path)
    try:
        replay = load_behavioral_result(cases_path, results_path)
    except BehavioralEvaluationError as exc:
        raise BenchmarkGateError(str(exc)) from exc
    cases = dataset.get("cases", [])
    results = replay.get("results", {})
    if len(cases) < 40:
        raise BenchmarkGateError(f"behavioral dataset has {len(cases)} cases; at least 40 required")
    if replay.get("dataset_id") != dataset.get("dataset_id"):
        raise BenchmarkGateError("behavioral result dataset ID does not match the cases")
    if replay.get("dataset_version") != dataset.get("version"):
        raise BenchmarkGateError("behavioral result version does not match the cases")
    case_ids = [str(item["id"]) for item in cases]
    if len(case_ids) != len(set(case_ids)):
        raise BenchmarkGateError("behavioral case IDs are not unique")
    if set(results) != set(case_ids):
        missing = sorted(set(case_ids) - set(results))
        extra = sorted(set(results) - set(case_ids))
        raise BenchmarkGateError(
            f"behavioral result IDs differ: missing={missing!r}, extra={extra!r}"
        )

    failures: list[dict[str, Any]] = []
    citation_valid = 0
    tool_correct = 0
    categories: Counter[str] = Counter()
    category_passes: Counter[str] = Counter()
    for case in cases:
        case_id = str(case["id"])
        category = str(case["category"])
        expected = case["expected"]
        actual = results[case_id]
        disposition_ok = actual.get("disposition") == expected.get("disposition")
        citation_ok = bool(actual.get("citation_valid"))
        tool_ok = actual.get("tool_execution") == expected.get("tool_execution")
        scenario_ok = actual.get("scenario_valid") is True
        passed = disposition_ok and citation_ok and tool_ok and scenario_ok
        if bool(actual.get("passed")) != passed:
            raise BenchmarkGateError(f"stored pass flag is inconsistent for {case_id}")
        categories[category] += 1
        citation_valid += int(citation_ok)
        tool_correct += int(tool_ok)
        category_passes[category] += int(passed)
        if not passed:
            failures.append(
                {
                    "id": case_id,
                    "disposition_ok": disposition_ok,
                    "citation_valid": citation_ok,
                    "tool_outcome_ok": tool_ok,
                    "scenario_valid": scenario_ok,
                }
            )
    total = len(cases)
    summary = {
        "dataset_id": dataset["dataset_id"],
        "adapter": cast(dict[str, Any], replay.get("adapter", {})).get("name"),
        "configuration_sha256": replay.get("configuration_sha256"),
        "cases": total,
        "passed": total - len(failures),
        "failed": len(failures),
        "pass_rate": _rounded((total - len(failures)) / total),
        "citation_validity": _rounded(citation_valid / total),
        "tool_outcome_accuracy": _rounded(tool_correct / total),
        "category_results": {
            category: {"passed": category_passes[category], "cases": categories[category]}
            for category in sorted(categories)
        },
        "failures": failures,
    }
    stored = replay.get("summary", {})
    for key in ("cases", "passed", "failed", "citation_validity", "tool_outcome_accuracy"):
        if stored.get(key) != summary[key]:
            raise BenchmarkGateError(f"stored behavioral summary drifted for {key}")
    if failures or summary["citation_validity"] != 1.0:
        raise BenchmarkGateError(f"behavioral release gate failed: {summary}")
    return summary


def _macro_metrics(confusion: dict[str, dict[str, int]]) -> tuple[float, float, float]:
    precisions: list[float] = []
    recalls: list[float] = []
    f1_values: list[float] = []
    for label in LABELS:
        true_positive = confusion[label][label]
        predicted = sum(confusion[actual][label] for actual in LABELS)
        actual = sum(confusion[label].values())
        precision, recall, f1 = _prf(true_positive, predicted, actual)
        precisions.append(precision)
        recalls.append(recall)
        f1_values.append(f1)
    return (
        _rounded(sum(precisions) / len(precisions)),
        _rounded(sum(recalls) / len(recalls)),
        _rounded(sum(f1_values) / len(f1_values)),
    )


def score_mapping_benchmark(path: Path) -> dict[str, Any]:
    dataset = _load(path)
    examples = dataset.get("examples", [])
    if len(examples) < 60:
        raise BenchmarkGateError(f"mapping benchmark has {len(examples)} examples; 60 required")
    ids = [str(item["id"]) for item in examples]
    if len(ids) != len(set(ids)):
        raise BenchmarkGateError("mapping benchmark IDs are not unique")

    confusion = {actual: {predicted: 0 for predicted in LABELS} for actual in LABELS}
    mechanically_valid = 0
    reviewer_rejections = 0
    for example in examples:
        actual = str(example["label"])
        predicted = str(example["suggested_label"])
        if actual not in LABELS or predicted not in LABELS:
            raise BenchmarkGateError(f"unknown mapping label in {example['id']}")
        confusion[actual][predicted] += 1
        citations = example.get("suggested_citations", [])
        citations_valid = (
            isinstance(citations, list)
            and len(citations) == len(set(citations))
            and all(
                isinstance(item, str) and EVIDENCE_REFERENCE.fullmatch(item) for item in citations
            )
            and (
                (predicted == "ABSTAIN" and not citations) or (predicted != "ABSTAIN" and citations)
            )
        )
        mechanically_valid += int(bool(citations_valid))
        reviewer_rejections += int(example.get("reviewer_decision") != "ACCEPT")

    total = len(examples)
    supports_tp = confusion["SUPPORTS"]["SUPPORTS"]
    supports_predicted = sum(confusion[label]["SUPPORTS"] for label in LABELS)
    supports_actual = sum(confusion["SUPPORTS"].values())
    precision, recall, f1 = _prf(supports_tp, supports_predicted, supports_actual)
    correct = sum(confusion[label][label] for label in LABELS)
    macro_precision, macro_recall, macro_f1 = _macro_metrics(confusion)
    abstention_precision, abstention_recall, abstention_f1 = _prf(
        confusion["ABSTAIN"]["ABSTAIN"],
        sum(confusion[label]["ABSTAIN"] for label in LABELS),
        sum(confusion["ABSTAIN"].values()),
    )
    metrics: dict[str, Any] = {
        "examples": total,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "accuracy": _rounded(correct / total),
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "macro_f1": macro_f1,
        "abstention_precision": abstention_precision,
        "abstention_recall": abstention_recall,
        "abstention_f1": abstention_f1,
        "citation_validity": _rounded(mechanically_valid / total),
        "reviewer_rejection_rate": _rounded(reviewer_rejections / total),
        "confusion_matrix": {
            "labels": list(LABELS),
            "rows": {
                label: [confusion[label][predicted] for predicted in LABELS] for label in LABELS
            },
        },
    }
    stored = dataset.get("measured_results", {})
    for key, value in metrics.items():
        if key == "confusion_matrix":
            continue
        if stored.get(key) != value:
            raise BenchmarkGateError(
                f"stored mapping metric drifted for {key}: {stored.get(key)!r} != {value!r}"
            )
    if stored.get("confusion_matrix") != metrics["confusion_matrix"]:
        raise BenchmarkGateError("stored mapping confusion matrix drifted")
    targets = dataset.get("release_targets", {})
    if precision < float(targets.get("precision", 0.9)):
        raise BenchmarkGateError("mapping precision is below the release target")
    if metrics["citation_validity"] < float(
        targets.get("mechanically_valid_evidence_references", 1.0)
    ):
        raise BenchmarkGateError("mapping citation validity is below the release target")
    return metrics
