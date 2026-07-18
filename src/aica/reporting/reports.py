"""Deterministic reports derived from the authoritative assessment package."""

from __future__ import annotations

import csv
import html
import io
from collections import Counter
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from aica.domain.models import AssessmentPackage, ResultStatus


def _oscal_uuid(run_id: str, record_type: str, record_id: str) -> str:
    """Return a stable OSCAL-compatible UUID for a runtime assessment record."""

    return str(uuid5(NAMESPACE_URL, f"aica:{run_id}:{record_type}:{record_id}"))


def executive_summary(package: AssessmentPackage) -> dict[str, Any]:
    statuses = Counter(result.status.value for result in package.test_results)
    ratings = Counter(risk.residual_rating.value for risk in package.risks)
    stale = sum(1 for item in package.evidence if item.freshness.value != "FRESH")
    return {
        "title": "Azure AI Continuous Assurance — Executive Readout",
        "disclaimer": "Internal readiness assessment—not certification or independent audit.",
        "run_id": package.run.id,
        "status": package.run.status.value,
        "scope": list(package.run.scope),
        "test_distribution": dict(sorted(statuses.items())),
        "evidence_items": len(package.evidence),
        "stale_or_unknown_evidence": stale,
        "open_findings": sum(1 for item in package.findings if item.status != "CLOSED"),
        "residual_risk_distribution": dict(sorted(ratings.items())),
        "estimated_cost_cad": package.run.estimated_cost_cad,
        "limitations": [
            "All business data, policies, users, and attacks are synthetic.",
            "A passed automated check supports an objective; it does not alone prove a control effective.",
            "Assessor, owner, and approver roles are simulated by one practitioner.",
        ],
    }


def render_html(package: AssessmentPackage) -> str:
    summary = executive_summary(package)
    rows = []
    by_objective = {item.id: item for item in package.objectives}
    for result in package.test_results:
        objective = by_objective.get(result.objective_id)
        rows.append(
            "<tr>"
            f"<td>{html.escape(result.objective_id)}</td>"
            f"<td>{html.escape(objective.title if objective else result.objective_id)}</td>"
            f"<td><span class='status {result.status.value.lower()}'>{result.status.value}</span></td>"
            f"<td>{html.escape(result.reason)}</td>"
            f"<td>{len(result.evidence_refs)}</td>"
            "</tr>"
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{html.escape(summary["title"])}</title>
<style>
body{{font:15px/1.5 system-ui,sans-serif;color:#172033;margin:0;background:#f5f7fa}}
main{{max-width:1180px;margin:auto;padding:40px}} h1{{font-size:30px;margin-bottom:8px}}
.notice{{border-left:4px solid #8661c5;background:#fff;padding:12px 16px;margin:18px 0 28px}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:24px 0}}
.metric{{background:#fff;border:1px solid #d9e0ea;padding:18px}} .metric strong{{font-size:28px;display:block}}
table{{width:100%;border-collapse:collapse;background:#fff}} th,td{{text-align:left;padding:12px;border-bottom:1px solid #e5e9ef}}
th{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#526079}}
.status{{font-weight:700}} .pass{{color:#107c10}} .fail,.error{{color:#c50f1f}} .not_run{{color:#8a6500}}
@media(max-width:800px){{main{{padding:20px}}.metrics{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main>
<p>ASSURANCE WORKPAPER / {html.escape(package.run.id)}</p><h1>{html.escape(summary["title"])}</h1>
<div class="notice"><strong>{html.escape(summary["disclaimer"])}</strong><br>Evidence-backed snapshot for the declared observation window.</div>
<div class="metrics"><div class="metric"><strong>{len(package.test_results)}</strong>tests</div>
<div class="metric"><strong>{summary["test_distribution"].get("FAIL", 0)}</strong>failed</div>
<div class="metric"><strong>{summary["open_findings"]}</strong>open findings</div>
<div class="metric"><strong>{summary["stale_or_unknown_evidence"]}</strong>stale evidence</div></div>
<h2>Control objectives</h2><table><thead><tr><th>ID</th><th>Objective</th><th>Result</th><th>Reason</th><th>Evidence</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>
<h2>Limitations</h2><ul>{"".join(f"<li>{html.escape(item)}</li>" for item in summary["limitations"])}</ul>
</main></body></html>"""


def risk_register_csv(package: AssessmentPackage) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "risk_id",
            "finding_id",
            "statement",
            "inherent_score",
            "inherent_rating",
            "residual_score",
            "residual_rating",
            "treatment",
            "owner",
        ]
    )
    for risk in package.risks:
        writer.writerow(
            [
                risk.id,
                risk.finding_id,
                risk.statement,
                risk.inherent_score,
                risk.inherent_rating.value,
                risk.residual_score,
                risk.residual_rating.value,
                risk.treatment.value,
                risk.owner,
            ]
        )
    return buffer.getvalue()


def oscal_assessment_results(package: AssessmentPackage) -> dict[str, Any]:
    """Create a compact OSCAL 1.2.2 assessment-results document."""

    observations: list[dict[str, Any]] = []
    observation_by_objective: dict[str, list[str]] = {}
    objective_control = {item.id: item.source_control for item in package.objectives}
    for item in package.observations:
        observation_id = _oscal_uuid(package.run.id, "observation", item.id)
        observation_by_objective.setdefault(item.objective_id, []).append(observation_id)
        observations.append(
            {
                "uuid": observation_id,
                "title": f"Observation for {item.objective_id}",
                "description": item.condition,
                "methods": ["TEST"],
                "collected": item.observed_at.isoformat(),
                "relevant-evidence": [
                    {"href": f"#evidence-{reference}", "description": "Hashed evidence item"}
                    for reference in item.evidence_refs
                ],
            }
        )
    findings: list[dict[str, Any]] = []
    for finding in package.findings:
        objective_id = finding.objective_id
        if objective_id is None or objective_id not in objective_control:
            raise ValueError(
                f"finding {finding.id} must reference a known objective before OSCAL export"
            )
        findings.append(
            {
                "uuid": _oscal_uuid(package.run.id, "finding", finding.id),
                "title": finding.title,
                "description": finding.condition,
                "target": {
                    "type": "objective-id",
                    "target-id": objective_id,
                    "status": {"state": "not-satisfied"},
                },
                "related-observations": [
                    {"observation-uuid": observation_id}
                    for observation_id in observation_by_objective.get(objective_id, [])
                ],
            }
        )
    selected_controls = sorted({objective.source_control for objective in package.objectives})
    return {
        "assessment-results": {
            "uuid": _oscal_uuid(package.run.id, "assessment-results", package.run.id),
            "metadata": {
                "title": "Azure AI Continuous Assurance Assessment Results",
                "last-modified": (package.run.ended_at or package.run.started_at).isoformat(),
                "version": "1.0.0",
                "oscal-version": "1.2.2",
                "remarks": "Continuous internal-assurance simulation; not certification.",
            },
            "import-ap": {"href": "../assessment-plan.json"},
            "results": [
                {
                    "uuid": _oscal_uuid(package.run.id, "result", package.run.id),
                    "title": f"Assessment run {package.run.id}",
                    "description": "Deterministic evidence evaluation plus reviewable conclusions.",
                    "start": package.run.started_at.isoformat(),
                    "end": (package.run.ended_at or package.run.started_at).isoformat(),
                    "reviewed-controls": {
                        "control-selections": [
                            {
                                "include-controls": [
                                    {"control-id": control_id} for control_id in selected_controls
                                ]
                            }
                        ]
                    },
                    "observations": observations,
                    "findings": findings,
                }
            ],
        }
    }


def result_summary(package: AssessmentPackage) -> str:
    counts = Counter(item.status for item in package.test_results)
    return ", ".join(
        f"{status.value}={counts.get(status, 0)}"
        for status in (
            ResultStatus.PASS,
            ResultStatus.FAIL,
            ResultStatus.ERROR,
            ResultStatus.NOT_RUN,
            ResultStatus.NOT_APPLICABLE,
        )
    )
