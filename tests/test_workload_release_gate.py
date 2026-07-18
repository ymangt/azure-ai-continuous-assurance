from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_scheduled_assessment_job_enforces_release_gate() -> None:
    workload = (ROOT / "infra" / "modules" / "control-workloads.bicep").read_text(
        encoding="utf-8"
    )
    assessment_job = workload.split(
        "resource assessmentJob 'Microsoft.App/jobs@2025-01-01'", maxsplit=1
    )[1].split(
        "resource commandWorkerJob 'Microsoft.App/jobs@2025-01-01'", maxsplit=1
    )[0]

    assert "'collect'" in assessment_job
    assert "'--profile'" in assessment_job
    assert "'azure-dev'" in assessment_job
    assert "'--release-gate'" in assessment_job
