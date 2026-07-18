#!/usr/bin/env python3
"""Execute and compare the controlled lifecycle proof for all safe scenarios."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from aica.scenarios import ScenarioCampaignArtifact, build_scenario_campaign_artifact

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data/scenario-campaigns/controlled-execution.json"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _conftest_path(value: str | None) -> Path:
    selected = value or shutil.which("conftest")
    if selected is None:
        raise SystemExit("Conftest is required; pass --conftest or install the pinned CI version")
    path = Path(selected)
    if not path.is_file():
        raise SystemExit(f"Conftest executable does not exist: {path}")
    return path


def validate_specs() -> None:
    schema = _read(ROOT / "schemas/scenario.schema.json")
    validator = Draft202012Validator(schema)
    errors: list[str] = []
    for path in sorted((ROOT / "data/scenarios").glob("SCN-*.json")):
        for error in validator.iter_errors(_read(path)):
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            errors.append(f"{path.name}:{location}: {error.message}")
    if errors:
        raise SystemExit("scenario specification validation failed:\n- " + "\n- ".join(errors))


def _serialized(artifact: ScenarioCampaignArtifact) -> str:
    return json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--conftest", help="Path to the pinned Conftest executable")
    parser.add_argument("--write", action="store_true", help="Regenerate the checked-in proof")
    args = parser.parse_args()

    validate_specs()
    artifact = build_scenario_campaign_artifact(ROOT, _conftest_path(args.conftest))
    generated = _serialized(artifact)
    if args.write:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(generated, encoding="utf-8")
    elif not OUTPUT.is_file():
        raise SystemExit(f"checked-in scenario proof is missing: {OUTPUT.relative_to(ROOT)}")
    elif OUTPUT.read_text(encoding="utf-8") != generated:
        raise SystemExit(
            "checked-in scenario proof is stale; rerun validate_scenarios.py --write "
            "with the pinned Conftest executable"
        )
    print(
        "validated 8 controlled scenario lifecycles: clean PASS, injected FAIL, exact evidence, "
        "finding/risk/remediation, fresh PASS retest, closure semantics, and cleanup proof; "
        "no checked-in Azure-live claim"
    )


if __name__ == "__main__":
    main()
