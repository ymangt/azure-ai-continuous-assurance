from __future__ import annotations

import pytest
from pydantic import ValidationError

from aica.evidence.manifest import (
    CadCostBreakdown,
    LocalEs256Signer,
    build_manifest,
    sign_manifest,
    verify_manifest,
)


def _cost(total: float = 0) -> CadCostBreakdown:
    return CadCostBreakdown(
        model_estimate_cad=total,
        compute_estimate_cad=0,
        storage_estimate_cad=0,
        telemetry_estimate_cad=0,
        total_estimate_cad=total,
    )


def test_manifest_verifies_and_detects_mutation(tmp_path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    artifact = run_root / "assessment.json"
    artifact.write_text('{"result":"PASS"}', encoding="utf-8")
    signer = LocalEs256Signer(tmp_path / "signing.pem")
    unsigned = build_manifest(
        run_id="run-1",
        root=run_root,
        paths=[artifact],
        git_commit="abcdef0",
        collector_version="1.0.0",
        evaluator_version="1.0.0",
        cost_estimate_cad=0,
        cost_breakdown=_cost(),
        public=True,
    )
    signed = sign_manifest(unsigned, signer)
    assert verify_manifest(signed, run_root) == []

    artifact.write_text('{"result":"FAIL"}', encoding="utf-8")
    errors = verify_manifest(signed, run_root)
    assert errors == ["artifact digest mismatch: assessment.json"]


def test_manifest_content_signature_detects_change(tmp_path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    signer = LocalEs256Signer(tmp_path / "signing.pem")
    signed = sign_manifest(
        build_manifest(
            run_id="run-1",
            root=tmp_path,
            paths=[artifact],
            git_commit="abcdef0",
            collector_version="1.0.0",
            evaluator_version="1.0.0",
            cost_estimate_cad=0,
            cost_breakdown=_cost(),
            public=False,
        ),
        signer,
    )
    tampered = signed.model_copy(
        update={"manifest": signed.manifest.model_copy(update={"run_id": "run-2"})}
    )
    errors = verify_manifest(tampered, tmp_path)
    assert "manifest digest mismatch" in errors
    assert any(error.startswith("manifest signature invalid") for error in errors)


def test_cost_breakdown_rejects_inconsistent_component_total() -> None:
    with pytest.raises(ValidationError, match="cost total must equal"):
        CadCostBreakdown(
            model_estimate_cad=0.03,
            compute_estimate_cad=0.02,
            storage_estimate_cad=0.01,
            telemetry_estimate_cad=0.01,
            total_estimate_cad=0.08,
        )


def test_manifest_rejects_total_that_differs_from_breakdown(tmp_path) -> None:
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    with pytest.raises(ValidationError, match="manifest cost estimate must equal"):
        build_manifest(
            run_id="run-1",
            root=tmp_path,
            paths=[artifact],
            git_commit="abcdef0",
            collector_version="1.0.0",
            evaluator_version="1.0.0",
            cost_estimate_cad=0.02,
            cost_breakdown=_cost(0.01),
            public=False,
        )
