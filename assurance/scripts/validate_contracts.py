#!/usr/bin/env python3
"""Prove the committed assessment-package JSON Schema matches Pydantic exactly."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from aica.domain.models import AssessmentPackage, SystemRecord

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "assessment-package.schema.json"
SYSTEM_SCHEMA_PATH = ROOT / "schemas" / "system-record.schema.json"
SYSTEM_RECORD_PATH = ROOT / "config" / "system-record.json"
SAMPLE_ROOT = ROOT / "data" / "sample-runs"


def generated_schema() -> dict[str, Any]:
    schema = AssessmentPackage.model_json_schema(mode="validation")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.invalid/aica/schemas/assessment-package.schema.json",
        **schema,
    }


def serialized_schema() -> str:
    return json.dumps(generated_schema(), indent=2, sort_keys=True) + "\n"


def serialized_system_schema() -> str:
    schema = SystemRecord.model_json_schema(mode="validation")
    generated = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://example.invalid/aica/schemas/system-record.schema.json",
        **schema,
    }
    return json.dumps(generated, indent=2, sort_keys=True) + "\n"


def validate_committed_contract() -> list[str]:
    errors: list[str] = []
    expected = serialized_schema()
    if not SCHEMA_PATH.is_file():
        return [f"missing generated Pydantic contract: {SCHEMA_PATH.relative_to(ROOT)}"]
    actual = SCHEMA_PATH.read_text(encoding="utf-8")
    if actual != expected:
        errors.append(
            "assessment-package.schema.json drifted from AssessmentPackage; "
            "run validate_contracts.py --write"
        )
    schema = json.loads(actual)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    for name in ("baseline", "remediated"):
        package_path = SAMPLE_ROOT / name / "package.json"
        raw = json.loads(package_path.read_text(encoding="utf-8"))
        for error in sorted(validator.iter_errors(raw), key=lambda item: list(item.path)):
            location = ".".join(str(part) for part in error.absolute_path) or "$"
            errors.append(f"{name} package JSON Schema error at {location}: {error.message}")
        try:
            AssessmentPackage.model_validate(raw)
        except ValueError as exc:
            errors.append(f"{name} package Pydantic error: {exc}")

    expected_system = serialized_system_schema()
    if not SYSTEM_SCHEMA_PATH.is_file():
        errors.append(
            f"missing generated Pydantic contract: {SYSTEM_SCHEMA_PATH.relative_to(ROOT)}"
        )
        return errors
    actual_system = SYSTEM_SCHEMA_PATH.read_text(encoding="utf-8")
    if actual_system != expected_system:
        errors.append(
            "system-record.schema.json drifted from SystemRecord; run validate_contracts.py --write"
        )
    system_schema = json.loads(actual_system)
    Draft202012Validator.check_schema(system_schema)
    system_raw = json.loads(SYSTEM_RECORD_PATH.read_text(encoding="utf-8"))
    for error in Draft202012Validator(
        system_schema,
        format_checker=FormatChecker(),
    ).iter_errors(system_raw):
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        errors.append(f"system record JSON Schema error at {location}: {error.message}")
    try:
        SystemRecord.model_validate(system_raw)
    except ValueError as exc:
        errors.append(f"system record Pydantic error: {exc}")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Regenerate the committed schema.")
    args = parser.parse_args()
    if args.write:
        SCHEMA_PATH.write_text(serialized_schema(), encoding="utf-8")
        print(f"wrote {SCHEMA_PATH.relative_to(ROOT)}")
        SYSTEM_SCHEMA_PATH.write_text(serialized_system_schema(), encoding="utf-8")
        print(f"wrote {SYSTEM_SCHEMA_PATH.relative_to(ROOT)}")
        return
    errors = validate_committed_contract()
    if errors:
        raise SystemExit("contract validation failed:\n- " + "\n- ".join(errors))
    print("contract validation passed: Pydantic schema parity + system record + 2 sample packages")


if __name__ == "__main__":
    main()
