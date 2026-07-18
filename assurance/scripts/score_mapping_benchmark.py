#!/usr/bin/env python3
"""Recompute the public mapping benchmark metrics and reject checked-in drift."""

from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "data" / "mapping-benchmark" / "human-labeled-examples.json"
LABELS = ("SUPPORTS", "CONTRADICTS", "INSUFFICIENT", "ABSTAIN")


def divide(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def f1(precision: float, recall: float) -> float:
    return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


def calculate(document: dict) -> dict:
    examples = document["examples"]
    matrix = {actual: {predicted: 0 for predicted in LABELS} for actual in LABELS}
    accepted_citations = 0
    checked_citations = 0
    rejections = 0
    for item in examples:
        actual = item["label"]
        predicted = item["suggested_label"]
        matrix[actual][predicted] += 1
        if predicted == "SUPPORTS":
            checked_citations += 1
            suggested = set(item["suggested_citations"])
            if suggested and suggested <= set(item["required_citations"]):
                accepted_citations += 1
        if item["reviewer_decision"] != "ACCEPT":
            rejections += 1

    per_label = {}
    for label in LABELS:
        true_positive = matrix[label][label]
        predicted_total = sum(matrix[actual][label] for actual in LABELS)
        actual_total = sum(matrix[label].values())
        precision = divide(true_positive, predicted_total)
        recall = divide(true_positive, actual_total)
        per_label[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1(precision, recall),
        }

    supports = per_label["SUPPORTS"]
    abstention = per_label["ABSTAIN"]
    correct = sum(matrix[label][label] for label in LABELS)
    return {
        "examples": len(examples),
        "confusion_matrix": {
            "labels": list(LABELS),
            "rows": {actual: [matrix[actual][predicted] for predicted in LABELS] for actual in LABELS},
        },
        "precision": supports["precision"],
        "recall": supports["recall"],
        "f1": supports["f1"],
        "accuracy": divide(correct, len(examples)),
        "macro_precision": sum(value["precision"] for value in per_label.values()) / len(LABELS),
        "macro_recall": sum(value["recall"] for value in per_label.values()) / len(LABELS),
        "macro_f1": sum(value["f1"] for value in per_label.values()) / len(LABELS),
        "abstention_precision": abstention["precision"],
        "abstention_recall": abstention["recall"],
        "abstention_f1": abstention["f1"],
        "citation_validity": divide(accepted_citations, checked_citations),
        "reviewer_rejection_rate": divide(rejections, len(examples)),
    }


def main() -> None:
    document = json.loads(PATH.read_text(encoding="utf-8"))
    actual = calculate(document)
    stored = document["measured_results"]
    errors: list[str] = []
    for key, value in actual.items():
        if key == "confusion_matrix":
            if value != stored[key]:
                errors.append(f"{key}: stored value differs from recomputed value")
        elif isinstance(value, float):
            if not math.isclose(round(value, 4), stored[key], abs_tol=0.0001):
                errors.append(f"{key}: stored={stored[key]} computed={value:.4f}")
        elif value != stored[key]:
            errors.append(f"{key}: stored={stored[key]} computed={value}")
    if errors:
        raise SystemExit("benchmark metric drift:\n- " + "\n- ".join(errors))
    print(json.dumps(actual, indent=2))


if __name__ == "__main__":
    main()
