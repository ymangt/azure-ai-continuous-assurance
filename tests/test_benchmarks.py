from pathlib import Path

from aica.evaluation.benchmarks import score_behavioral, score_mapping_benchmark


def test_checked_in_behavioral_gate_recomputes() -> None:
    result = score_behavioral(
        Path("data/ai-evaluations/behavioral-cases.json"),
        Path("data/ai-evaluations/replay-results.json"),
    )
    assert result["cases"] >= 40
    assert result["failed"] == 0
    assert result["citation_validity"] == 1.0


def test_checked_in_mapping_metrics_and_targets_recompute() -> None:
    result = score_mapping_benchmark(Path("data/mapping-benchmark/human-labeled-examples.json"))
    assert result["examples"] >= 60
    assert result["precision"] >= 0.9
    assert result["citation_validity"] == 1.0
