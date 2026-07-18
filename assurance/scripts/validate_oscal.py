#!/usr/bin/env python3
"""Validate every repository OSCAL document against NIST OSCAL v1.2.2."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OSCAL = ROOT / "assurance" / "oscal"
BUNDLED_SCHEMA = OSCAL / "schema" / "v1.2.2" / "oscal_complete_schema.json"
BUNDLED_SCHEMA_SHA256 = "484d09fb794155d25c3d017a461a47a8f07d8a4cc53e7bce2f5b3c025820a945"
MODELS = {
    "aica-ai-catalog.json": ("catalog", "oscal_catalog_schema.json"),
    "aica-profile.json": ("profile", "oscal_profile_schema.json"),
    "assistant-component-definition.json": ("component-definition", "oscal_component_schema.json"),
    "assurance-component-definition.json": ("component-definition", "oscal_component_schema.json"),
    "system-security-plan.json": ("system-security-plan", "oscal_ssp_schema.json"),
    "assessment-plan.json": ("assessment-plan", "oscal_assessment-plan_schema.json"),
    "assessment-results-baseline.json": (
        "assessment-results",
        "oscal_assessment-results_schema.json",
    ),
    "assessment-results-retest.json": (
        "assessment-results",
        "oscal_assessment-results_schema.json",
    ),
    "plan-of-action-and-milestones.json": (
        "plan-of-action-and-milestones",
        "oscal_poam_schema.json",
    ),
}
RUNTIME_PACKAGES = {
    "runtime-assessment-results-baseline.json": ROOT
    / "data"
    / "sample-runs"
    / "baseline"
    / "package.json",
    "runtime-assessment-results-remediated.json": ROOT
    / "data"
    / "sample-runs"
    / "remediated"
    / "package.json",
}
STATIC_RESULT_MANIFESTS = {
    "assessment-results-baseline.json": ROOT
    / "data"
    / "sample-runs"
    / "baseline"
    / "run-manifest.json",
    "assessment-results-retest.json": ROOT
    / "data"
    / "sample-runs"
    / "remediated"
    / "run-manifest.json",
}


def _local_rlink_hash_errors(filename: str, model: dict[str, Any]) -> list[str]:
    """Verify hashes for local files referenced from OSCAL back matter."""

    errors: list[str] = []
    resources = model.get("back-matter", {}).get("resources", [])
    for resource in resources:
        for link in resource.get("rlinks", []):
            href = str(link.get("href", ""))
            if not href or href.startswith("#") or "://" in href:
                continue
            target = (OSCAL / href).resolve()
            try:
                target.relative_to(ROOT)
            except ValueError:
                errors.append(f"{filename}: local rlink escapes the repository: {href}")
                continue
            if not target.is_file():
                errors.append(f"{filename}: local rlink is missing: {href}")
                continue
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            for declared in link.get("hashes", []):
                algorithm = str(declared.get("algorithm", "")).upper().replace("-", "")
                if algorithm == "SHA256" and str(declared.get("value", "")).lower() != actual:
                    errors.append(
                        f"{filename}: {href} SHA-256 mismatch: expected {actual}, "
                        f"got {declared.get('value', '')}"
                    )
    return errors


def _assessment_manifest_errors(filename: str, model: dict[str, Any]) -> list[str]:
    manifest_path = STATIC_RESULT_MANIFESTS.get(filename)
    if manifest_path is None:
        return []
    if not manifest_path.is_file():
        return [f"{filename}: linked signed manifest is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = model.get("results", [])
    if not results:
        return [f"{filename}: assessment result is missing"]
    props = {str(item.get("name")): str(item.get("value")) for item in results[0].get("props", [])}
    errors: list[str] = []
    expected_digest = f"sha256:{manifest.get('manifest_sha256', '')}"
    if props.get("manifest-digest") != expected_digest:
        errors.append(
            f"{filename}: manifest-digest does not match {manifest_path.relative_to(ROOT)}"
        )
    expected_run_id = str(manifest.get("manifest", {}).get("run_id", ""))
    if props.get("run-id") != expected_run_id:
        errors.append(f"{filename}: run-id does not match its signed manifest")
    return errors


def _runtime_assessment_result_documents() -> dict[str, dict[str, Any]]:
    """Build runtime OSCAL from checked-in packages and include checked-in public runs."""

    from aica.domain.models import AssessmentPackage
    from aica.reporting.reports import oscal_assessment_results

    documents: dict[str, dict[str, Any]] = {}
    for filename, package_path in RUNTIME_PACKAGES.items():
        package = AssessmentPackage.model_validate_json(package_path.read_text(encoding="utf-8"))
        documents[filename] = oscal_assessment_results(package)
    for path in sorted((ROOT / "artifacts" / "public").glob("*/assessment-results.json")):
        documents[path.relative_to(ROOT).as_posix()] = json.loads(path.read_text(encoding="utf-8"))
    return documents


def _validate_runtime_assessment_results(validator: Any) -> list[str]:
    errors: list[str] = []
    try:
        documents = _runtime_assessment_result_documents()
    except Exception as error:
        return [f"runtime assessment-results generation failed: {error}"]
    for filename, instance in documents.items():
        validation_errors = sorted(
            validator.iter_errors(instance),
            key=lambda item: [str(part) for part in item.absolute_path],
        )
        errors.extend(_format_error(filename, error) for error in validation_errors)
    return errors


def structural_check() -> list[str]:
    """Return clear repository-level errors before running the official schema."""
    errors: list[str] = []
    for filename, (root_key, _) in MODELS.items():
        path = OSCAL / filename
        if not path.exists():
            errors.append(f"missing {path.relative_to(ROOT)}")
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        if set(document) != {root_key}:
            errors.append(f"{filename}: expected sole root key {root_key}")
            continue
        model = document[root_key]
        errors.extend(_local_rlink_hash_errors(filename, model))
        errors.extend(_assessment_manifest_errors(filename, model))
        metadata = model.get("metadata", {})
        if metadata.get("oscal-version") != "1.2.2":
            errors.append(f"{filename}: oscal-version is not 1.2.2")
        for required in ("uuid", "metadata"):
            if required not in model:
                errors.append(f"{filename}: missing {required}")
        for required in ("title", "last-modified", "version", "oscal-version"):
            if required not in metadata:
                errors.append(f"{filename}: metadata missing {required}")
    return errors


def _load_dependencies() -> tuple[Any, Any, Any]:
    try:
        import jsonschema
        import regex
        from jsonschema import exceptions, validators
    except ImportError as error:
        raise SystemExit(
            "strict OSCAL validation requires the development dependencies; "
            "install the project with `pip install -e '.[dev]'`"
        ) from error
    return jsonschema, regex, (exceptions, validators)


def _validator(schema: dict[str, Any]) -> Any:
    """Create a Draft 7 validator with ECMA-262 Unicode pattern support.

    NIST's generated schemas use ``\\p{...}`` Unicode properties. Python's
    standard ``re`` engine does not implement them, while the ``regex`` package
    does. Only the Draft 7 ``pattern`` keyword is replaced; all other schema
    behavior remains jsonschema's standard implementation.
    """
    jsonschema, regex, modules = _load_dependencies()
    exceptions, validators = modules

    def validate_pattern(
        validator: Any,
        pattern: str,
        instance: object,
        subschema: dict[str, Any],
    ) -> Iterator[Any]:
        del validator, subschema
        if isinstance(instance, str) and regex.search(pattern, instance) is None:
            yield exceptions.ValidationError(f"{instance!r} does not match {pattern!r}")

    validator_class = validators.extend(
        jsonschema.Draft7Validator,
        validators={"pattern": validate_pattern},
    )
    return validator_class(schema)


def _format_error(filename: str, error: Any) -> str:
    location = "/".join(str(part) for part in error.absolute_path)
    return f"{filename}:{location}: {error.message}"


def _check_schema_version(schema: dict[str, Any], schema_path: Path) -> list[str]:
    schema_id = schema.get("$id", "")
    if "1.2.2" not in schema_id:
        return [f"{schema_path}: schema $id is not OSCAL v1.2.2: {schema_id!r}"]
    return []


def _validate_with_complete_schema(schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = _check_schema_version(schema, schema_path)
    base_schema = {key: value for key, value in schema.items() if key != "oneOf"}
    branches = {
        branch["required"][0]: branch
        for branch in schema.get("oneOf", [])
        if len(branch.get("required", [])) == 1
    }
    root_validators: dict[str, Any] = {}
    for filename, (root_key, _) in MODELS.items():
        if root_key not in branches:
            errors.append(f"{schema_path}: complete schema missing root model {root_key}")
            continue
        # Selecting the matching official root branch gives precise nested
        # errors instead of one opaque top-level `oneOf` failure.
        validator = _validator({**base_schema, **branches[root_key]})
        root_validators[root_key] = validator
        instance = json.loads((OSCAL / filename).read_text(encoding="utf-8"))
        validation_errors = sorted(
            validator.iter_errors(instance),
            key=lambda item: [str(part) for part in item.absolute_path],
        )
        errors.extend(_format_error(filename, error) for error in validation_errors)
    assessment_validator = root_validators.get("assessment-results")
    if assessment_validator is not None:
        errors.extend(_validate_runtime_assessment_results(assessment_validator))
    return errors


def _validate_with_model_schemas(schema_dir: Path) -> list[str]:
    errors: list[str] = []
    validators: dict[str, Any] = {}
    for filename, (_, schema_name) in MODELS.items():
        schema_path = schema_dir / schema_name
        if not schema_path.exists():
            errors.append(f"official schema missing {schema_name}")
            continue
        validator = validators.get(schema_name)
        if validator is None:
            schema = json.loads(schema_path.read_text(encoding="utf-8"))
            errors.extend(_check_schema_version(schema, schema_path))
            validator = _validator(schema)
            validators[schema_name] = validator
        instance = json.loads((OSCAL / filename).read_text(encoding="utf-8"))
        validation_errors = sorted(
            validator.iter_errors(instance),
            key=lambda item: [str(part) for part in item.absolute_path],
        )
        errors.extend(_format_error(filename, error) for error in validation_errors)
    assessment_validator = validators.get("oscal_assessment-results_schema.json")
    if assessment_validator is not None:
        errors.extend(_validate_runtime_assessment_results(assessment_validator))
    return errors


def official_check(schema_dir: Path | None = None) -> list[str]:
    """Validate using the bundled complete schema or an official schema directory."""
    if schema_dir is not None:
        complete_schema = schema_dir / "oscal_complete_schema.json"
        if complete_schema.exists():
            return _validate_with_complete_schema(complete_schema)
        return _validate_with_model_schemas(schema_dir)

    actual_digest = hashlib.sha256(BUNDLED_SCHEMA.read_bytes()).hexdigest()
    if actual_digest != BUNDLED_SCHEMA_SHA256:
        return [
            "bundled OSCAL schema checksum mismatch: "
            f"expected {BUNDLED_SCHEMA_SHA256}, got {actual_digest}"
        ]
    return _validate_with_complete_schema(BUNDLED_SCHEMA)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=Path(os.environ["OSCAL_SCHEMA_DIR"]) if "OSCAL_SCHEMA_DIR" in os.environ else None,
        help="Optional directory containing the official OSCAL v1.2.2 JSON schema bundle.",
    )
    args = parser.parse_args()
    errors = structural_check()
    errors.extend(official_check(args.schema_dir.resolve() if args.schema_dir else None))
    if errors:
        raise SystemExit("OSCAL validation failed:\n- " + "\n- ".join(errors))
    checked_public_runs = len(
        list((ROOT / "artifacts" / "public").glob("*/assessment-results.json"))
    )
    print(
        f"validated {len(MODELS)} static OSCAL documents, {len(RUNTIME_PACKAGES)} generated "
        f"runtime samples, and {checked_public_runs} checked-in public runtime results against "
        "official OSCAL v1.2.2 JSON schema"
    )


if __name__ == "__main__":
    main()
