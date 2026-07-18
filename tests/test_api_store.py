from pathlib import Path

import pytest

from aica.api_store import CompositeRunStore, PackageIntegrityError
from aica.evidence.manifest import CadCostBreakdown, LocalEs256Signer, build_manifest, sign_manifest
from aica.util.canonical import canonical_json_bytes

ZERO_COST = CadCostBreakdown(
    model_estimate_cad=0,
    compute_estimate_cad=0,
    storage_estimate_cad=0,
    telemetry_estimate_cad=0,
    total_estimate_cad=0,
)


def _signed_run(root: Path, key: Path) -> str:
    run = root / "run-1"
    run.mkdir(parents=True)
    package = {"run": {"id": "run-1", "started_at": "2026-07-16T12:00:00Z"}}
    package_path = run / "package.json"
    package_path.write_bytes(canonical_json_bytes(package))
    unsigned = build_manifest(
        run_id="run-1",
        root=run,
        paths=[package_path],
        git_commit="abcdef0",
        collector_version="1.0.0",
        evaluator_version="1.0.0",
        cost_estimate_cad=0,
        cost_breakdown=ZERO_COST,
        public=True,
    )
    signed = sign_manifest(unsigned, LocalEs256Signer(key))
    (run / "run-manifest.json").write_bytes(canonical_json_bytes(signed))
    return signed.key_fingerprint


def test_composite_store_fails_closed_for_missing_or_mutated_manifest(tmp_path) -> None:
    missing_root = tmp_path / "missing"
    missing_run = missing_root / "run-1"
    missing_run.mkdir(parents=True)
    (missing_run / "package.json").write_text('{"run":{"id":"run-1"}}', encoding="utf-8")
    with pytest.raises(PackageIntegrityError, match="manifest missing"):
        CompositeRunStore([missing_root]).list_runs_raw()

    signed_root = tmp_path / "signed"
    _signed_run(signed_root, tmp_path / "key.pem")
    (signed_root / "run-1" / "package.json").write_text(
        '{"run":{"id":"run-1","tampered":true}}', encoding="utf-8"
    )
    with pytest.raises(PackageIntegrityError, match="digest mismatch"):
        CompositeRunStore([signed_root]).get_raw("run-1")


def test_composite_store_enforces_configured_signer_trust(tmp_path) -> None:
    root = tmp_path / "runs"
    fingerprint = _signed_run(root, tmp_path / "key.pem")
    verified = CompositeRunStore([root], trusted_key_fingerprints=frozenset({fingerprint})).get_raw(
        "run-1"
    )
    assert len(verified["run"]["manifest_digest"]) == 64

    with pytest.raises(PackageIntegrityError, match="not trusted"):
        CompositeRunStore([root], trusted_key_fingerprints=frozenset({"0" * 64})).get_raw("run-1")
