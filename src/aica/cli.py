"""`assure` command-line interface for the headless assurance lifecycle."""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, cast

import typer

from aica.api_store import CompositeRunStore
from aica.assistant.adapters import (
    FoundryModelAdapter,
    PhiModelAdapter,
    ReplayModelAdapter,
)
from aica.command_worker import AzureCommandProcessor
from aica.commands import AzureTableCommandQueue, CommandQueue, LocalCommandQueue
from aica.config import get_settings
from aica.domain.models import RunStatus
from aica.evaluation.behavioral import (
    FOUNDRY_ADAPTER_VERSION,
    PHI_ADAPTER_VERSION,
    REPLAY_ADAPTER_VERSION,
    EvaluationAdapter,
    configured_adapter_provenance,
    configured_deployment_provenance,
    endpoint_fingerprint,
    local_corpus_provenance,
    run_behavioral_evaluation,
    runtime_evaluation_configuration,
    write_behavioral_result,
)
from aica.evaluation.benchmarks import score_behavioral, score_mapping_benchmark
from aica.evaluation.diff import diff_packages
from aica.evaluation.engine import RuleEngine
from aica.evidence.manifest import load_signed_manifest, verify_manifest
from aica.evidence.redaction import assert_public_safe
from aica.fixtures.cleanup import AzureFixtureJanitor, FixtureCleanupError
from aica.pipeline import AssessmentPipeline, release_gate_failed
from aica.profiles import load_profile
from aica.reporting.reports import (
    executive_summary,
    oscal_assessment_results,
    render_html,
    result_summary,
    risk_register_csv,
)
from aica.util.canonical import canonical_json_bytes

app = typer.Typer(
    name="assure",
    no_args_is_help=True,
    help="Collect evidence, evaluate controls, produce reports, and verify signed packages.",
)
fixture_app = typer.Typer(help="Queue guarded, synthetic failure scenarios.")
evaluation_app = typer.Typer(help="Run fixed AI assurance release gates.")
commands_app = typer.Typer(help="Process queued private-console commands.")
app.add_typer(fixture_app, name="fixture")
app.add_typer(evaluation_app, name="evaluation")
app.add_typer(commands_app, name="commands")


def _store() -> CompositeRunStore:
    settings = get_settings()
    return CompositeRunStore([settings.artifact_dir / "public", settings.data_dir])


def _command_queue() -> CommandQueue:
    settings = get_settings()
    if settings.azure_table_endpoint:
        return AzureTableCommandQueue(
            settings.azure_table_endpoint,
            settings.azure_command_table,
            managed_identity_client_id=settings.azure_client_id,
        )
    return LocalCommandQueue(settings.artifact_dir / "requests")


@app.command()
def collect(
    profile: Annotated[
        str, typer.Option("--profile", help="Profile name or JSON path.")
    ] = "azure-dev",
    prior_run: Annotated[
        str | None, typer.Option("--prior-run", help="Prior run ID when this is a retest.")
    ] = None,
    finding: Annotated[
        list[str] | None,
        typer.Option("--finding", help="Finding ID to retest; repeat to target several."),
    ] = None,
    release_gate: Annotated[
        bool,
        typer.Option(
            "--release-gate/--no-release-gate",
            help=(
                "Exit nonzero for failed/error automated tests; pending manual review alone "
                "does not block."
            ),
        ),
    ] = False,
) -> None:
    """Run scope, collection, evaluation, assessment, reporting, and signing."""

    settings = get_settings()
    selected = load_profile(profile)
    package, path = asyncio.run(
        AssessmentPipeline(settings).execute(
            selected,
            prior_run_id=prior_run,
            finding_ids=tuple(finding or ()) or None,
        )
    )
    typer.echo(f"run_id={package.run.id}")
    typer.echo(f"results={result_summary(package)}")
    typer.echo(f"package={path}")
    gate_failed = release_gate and release_gate_failed(list(package.test_results))
    if release_gate:
        typer.echo(f"release_gate={'BLOCKED' if gate_failed else 'PASSED'}")
    if package.run.status == RunStatus.FAILED or gate_failed:
        raise typer.Exit(code=1)


@app.command()
def evaluate(
    run: Annotated[str, typer.Option("--run", help="Existing run ID.")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Re-evaluate an existing package without changing its authoritative record."""

    package = _store().get(run)
    results = RuleEngine().evaluate(run, list(package.evidence))
    destination = output or Path("artifacts/work") / run / "evaluation-preview.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(
        canonical_json_bytes([item.model_dump(mode="json") for item in results])
    )
    typer.echo(f"preview={destination}")


@app.command()
def report(
    run: Annotated[str, typer.Option("--run", help="Existing run ID.")],
    formats: Annotated[
        str, typer.Option("--format", help="Comma-delimited: oscal,html,json,csv")
    ] = "oscal,html",
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("artifacts/work/reports"),
) -> None:
    """Regenerate derived reports from an immutable assessment package."""

    package = _store().get(run)
    destination = output_dir / run
    destination.mkdir(parents=True, exist_ok=True)
    requested = {item.strip().casefold() for item in formats.split(",")}
    if "oscal" in requested:
        (destination / "assessment-results.json").write_bytes(
            canonical_json_bytes(oscal_assessment_results(package))
        )
    if "html" in requested:
        (destination / "assessment-report.html").write_text(render_html(package), encoding="utf-8")
    if "json" in requested:
        (destination / "executive-summary.json").write_bytes(
            canonical_json_bytes(executive_summary(package))
        )
    if "csv" in requested:
        (destination / "risk-register.csv").write_text(risk_register_csv(package), encoding="utf-8")
    typer.echo(f"reports={destination}")


@app.command("diff")
def diff_command(
    from_run: Annotated[str, typer.Option("--from", help="Baseline run ID.")],
    to_run: Annotated[str, typer.Option("--to", help="Retest run ID.")],
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Compare two immutable assessment packages."""

    store = _store()
    result = diff_packages(store.get(from_run), store.get(to_run))
    content = canonical_json_bytes(result)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)
        typer.echo(f"diff={output}")
    else:
        typer.echo(content.decode("utf-8"))


@app.command()
def verify(
    manifest: Annotated[Path, typer.Option("--manifest", help="Signed run-manifest.json.")],
) -> None:
    """Offline-verify the manifest signature and every artifact digest."""

    signed = load_signed_manifest(manifest)
    errors = verify_manifest(signed, manifest.parent)
    if errors:
        for error in errors:
            typer.echo(f"ERROR: {error}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"verified run={signed.manifest.run_id} key_fingerprint={signed.key_fingerprint}")


@app.command()
def publish(
    run: Annotated[str, typer.Option("--run")],
    sanitized: Annotated[bool, typer.Option("--sanitized/--private")] = True,
    destination: Annotated[Path, typer.Option("--destination")] = Path("dist/public-assessments"),
) -> None:
    """Copy only a pre-sanitized, signed package to the publication directory."""

    if not sanitized:
        raise typer.BadParameter("private assessment packages cannot be published")
    settings = get_settings()
    source = settings.artifact_dir / "public" / run
    if not source.is_dir():
        raise typer.BadParameter(f"sanitized package does not exist: {source}")
    for path in source.rglob("*"):
        if path.is_file():
            assert_public_safe(path.read_text(encoding="utf-8"))
    target = destination / run
    if target.exists():
        raise typer.BadParameter(f"publication target already exists: {target}")
    shutil.copytree(source, target)
    typer.echo(f"published={target}")


@evaluation_app.command("behavioral")
def behavioral_evaluation(
    cases: Annotated[Path, typer.Option("--cases")] = Path(
        "data/ai-evaluations/behavioral-cases.json"
    ),
    results: Annotated[Path, typer.Option("--results")] = Path(
        "data/ai-evaluations/replay-results.json"
    ),
) -> None:
    """Recompute the fixed behavioral gate and reject stored-summary drift."""

    summary = score_behavioral(cases, results)
    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


async def _generate_behavioral_artifact(
    *,
    cases: Path,
    corpus: Path,
    fixtures: Path,
    configuration_path: Path | None,
    adapter_kind: str,
    deployed_configuration_sha256: str | None,
) -> dict[str, Any]:
    settings = get_settings()
    if adapter_kind == "replay":
        selected = EvaluationAdapter(
            model=ReplayModelAdapter(),
            kind="replay",
            name="ReplayModelAdapter",
            version=REPLAY_ADAPTER_VERSION,
            deployment="deterministic-replay",
        )
    elif adapter_kind == "foundry":
        if not settings.foundry_endpoint:
            raise typer.BadParameter("AICA_FOUNDRY_ENDPOINT is required for --adapter foundry")
        selected = EvaluationAdapter(
            model=FoundryModelAdapter(
                settings.foundry_endpoint,
                settings.model_deployment,
                max_output_tokens=settings.model_max_output_tokens,
                managed_identity_client_id=(
                    settings.azure_client_id if settings.env == "production" else None
                ),
            ),
            kind="foundry",
            name="FoundryModelAdapter",
            version=FOUNDRY_ADAPTER_VERSION,
            deployment=settings.model_deployment,
            endpoint_sha256=endpoint_fingerprint(settings.foundry_endpoint),
        )
    elif adapter_kind == "phi":
        if not settings.phi_endpoint:
            raise typer.BadParameter("AICA_PHI_ENDPOINT is required for --adapter phi")
        selected = EvaluationAdapter(
            model=PhiModelAdapter(
                settings.phi_endpoint,
                bearer_token=settings.phi_bearer_token,
                max_output_tokens=settings.model_max_output_tokens,
                managed_identity_client_id=(
                    settings.azure_client_id if settings.env == "production" else None
                ),
                token_scope=settings.phi_token_scope,
            ),
            kind="phi",
            name="PhiModelAdapter",
            version=PHI_ADAPTER_VERSION,
            deployment="Phi-4-mini-instruct",
            endpoint_sha256=endpoint_fingerprint(settings.phi_endpoint),
        )
    else:
        raise typer.BadParameter("--adapter must be replay, foundry, or phi")

    if configuration_path is not None:
        configuration = json.loads(configuration_path.read_text(encoding="utf-8"))
        if not isinstance(configuration, dict):
            raise typer.BadParameter("the evaluation configuration must be a JSON object")
        configuration_source = configuration_path.name
    else:
        configuration = runtime_evaluation_configuration(
            adapter=configured_adapter_provenance(
                kind=selected.kind,
                deployment=selected.deployment,
                endpoint=(
                    settings.foundry_endpoint
                    if selected.kind == "foundry"
                    else settings.phi_endpoint
                    if selected.kind == "phi"
                    else None
                ),
            ),
            max_output_tokens=settings.model_max_output_tokens,
            confirmation_ttl_seconds=settings.confirmation_ttl_seconds,
            requests_per_user_hour=settings.request_limit_per_user_per_hour,
            corpus=local_corpus_provenance(corpus),
            deployment=configured_deployment_provenance(
                source_commit=settings.deployed_source_commit,
                assurance_api_image_sha256=settings.assurance_api_image_sha256,
                assistant_ui_image_sha256=settings.assistant_ui_image_sha256,
                assurance_job_image_sha256=settings.assurance_job_image_sha256,
                required=selected.kind != "replay",
            ),
        )
        configuration_source = "generated-runtime-configuration"
    try:
        return await run_behavioral_evaluation(
            cases_path=cases,
            corpus_dir=corpus,
            controlled_fixtures_path=fixtures,
            configuration=cast(dict[str, Any], configuration),
            configuration_source=configuration_source,
            adapter=selected,
            deployed_configuration_sha256=deployed_configuration_sha256,
        )
    finally:
        if isinstance(selected.model, (FoundryModelAdapter, PhiModelAdapter)):
            await selected.model.close()


@evaluation_app.command("generate")
def generate_behavioral_evaluation(
    adapter: Annotated[str, typer.Option("--adapter", help="replay, foundry, or phi")] = "replay",
    cases: Annotated[Path, typer.Option("--cases")] = Path(
        "data/ai-evaluations/behavioral-cases.json"
    ),
    corpus: Annotated[Path, typer.Option("--corpus")] = Path("data/policy-corpus"),
    fixtures: Annotated[Path, typer.Option("--fixtures")] = Path(
        "data/ai-evaluations/controlled-fixtures.json"
    ),
    configuration: Annotated[Path | None, typer.Option("--configuration")] = None,
    output: Annotated[Path | None, typer.Option("--output")] = None,
    deployed_configuration_sha256: Annotated[
        str | None,
        typer.Option(
            "--deployed-configuration-sha256",
            help="Digest independently exported by the deployed workload configuration.",
        ),
    ] = None,
) -> None:
    """Execute fixed cases through the assistant and write controlled result evidence."""

    selected_adapter = adapter.casefold()
    if configuration is None and selected_adapter == "replay":
        configuration = cases.parent / "replay-configuration.json"
    destination = output or Path("artifacts/work/ai-evaluations") / (
        "live-results.json" if selected_adapter in {"foundry", "phi"} else "replay-results.json"
    )
    artifact = asyncio.run(
        _generate_behavioral_artifact(
            cases=cases,
            corpus=corpus,
            fixtures=fixtures,
            configuration_path=configuration,
            adapter_kind=selected_adapter,
            deployed_configuration_sha256=deployed_configuration_sha256,
        )
    )
    write_behavioral_result(destination, artifact)
    summary = cast(dict[str, Any], artifact["summary"])
    typer.echo(f"evaluation_id={artifact['evaluation_id']}")
    typer.echo(f"mode={artifact['execution_mode']}")
    typer.echo(f"results={destination}")
    typer.echo(canonical_json_bytes(summary).decode("utf-8"))
    if int(summary["failed"]) > 0:
        raise typer.Exit(code=1)


@evaluation_app.command("mapping")
def mapping_evaluation(
    benchmark: Annotated[Path, typer.Option("--benchmark")] = Path(
        "data/mapping-benchmark/human-labeled-examples.json"
    ),
) -> None:
    """Recompute mapping metrics, confusion matrix, citations, and release targets."""

    summary = score_mapping_benchmark(benchmark)
    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


@commands_app.command("process")
def process_commands(
    once: Annotated[bool, typer.Option("--once")] = True,
) -> None:
    """Claim and process one bounded batch from Azure Table Storage."""

    if not once:
        raise typer.BadParameter("only bounded --once processing is supported")
    settings = get_settings()
    if not settings.azure_table_endpoint or not settings.azure_assessment_job_resource_id:
        raise typer.BadParameter(
            "AICA_AZURE_TABLE_ENDPOINT and AICA_AZURE_ASSESSMENT_JOB_RESOURCE_ID are required"
        )
    processor = AzureCommandProcessor(
        settings.azure_table_endpoint,
        settings.azure_command_table,
        settings.azure_review_table,
        settings.azure_assessment_job_resource_id,
        managed_identity_client_id=settings.azure_client_id,
    )
    summary = asyncio.run(processor.process_once())
    typer.echo(canonical_json_bytes(summary).decode("utf-8"))


def _scenario_path(scenario_id: str, *, deployable_only: bool = False) -> Path:
    normalized = scenario_id.casefold()
    for candidate in sorted(Path("data/scenarios").glob("*.json")):
        raw = json.loads(candidate.read_text(encoding="utf-8"))
        declared = str(raw.get("scenario_id", "")).casefold()
        if normalized in {
            declared,
            candidate.stem.casefold(),
        } or candidate.stem.casefold().startswith(f"{normalized}-"):
            safety = raw.get("safety", {})
            if str(safety.get("data_classification", "")).casefold() != "synthetic":
                raise typer.BadParameter("scenario is not restricted to synthetic data")
            if (
                deployable_only
                and raw.get("execution", {}).get("mode") != "CONTROLLED_ARM_TRANSCRIPT"
            ):
                raise typer.BadParameter(
                    "this scenario is not an Azure fixture handoff; run the controlled "
                    "scenario validator for offline, replay, and signed-sample campaigns"
                )
            return candidate
    raise typer.BadParameter(f"unknown safe scenario: {scenario_id}")


def _validated_expiry(path: Path, expires_on: str) -> str:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        expiry = datetime.fromisoformat(expires_on.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter("--expires-on must be an RFC3339 date/time") from exc
    if expiry.tzinfo is None:
        raise typer.BadParameter("--expires-on must include a timezone")
    now = datetime.now(UTC)
    maximum = now + timedelta(minutes=int(raw["safety"]["expires_after_minutes"]))
    if expiry <= now or expiry > maximum:
        raise typer.BadParameter(
            f"--expires-on must be in the future and no later than {maximum.isoformat()}"
        )
    return expiry.astimezone(UTC).isoformat()


@fixture_app.command("run")
def fixture_run(
    scenario_id: Annotated[str, typer.Argument(help="Version-controlled safe scenario ID.")],
    expires_on: Annotated[str, typer.Option("--expires-on", help="ISO-8601 expiry date/time.")],
    owner: Annotated[str, typer.Option("--owner")],
) -> None:
    """Queue one allowlisted fixture; the protected Azure job performs injection and cleanup."""

    path = _scenario_path(scenario_id, deployable_only=True)
    expiry = _validated_expiry(path, expires_on)
    queue = _command_queue()
    command = queue.enqueue(
        "RUN_FIXTURE",
        owner,
        {
            "scenario_id": scenario_id,
            "scenario_path": path.as_posix(),
            "resource_group": "rg-aica-fixture-eus2",
            "expires_on": expiry,
            "owner": owner,
            "data_classification": "synthetic",
        },
    )
    typer.echo(f"queued={command.id} operator=Azure-MCP")


@fixture_app.command("cleanup")
def fixture_cleanup(
    scenario_id: Annotated[str, typer.Argument(help="Version-controlled safe scenario ID.")],
    owner: Annotated[str, typer.Option("--owner")],
) -> None:
    """Queue unconditional fixture cleanup and empty-group verification."""

    _scenario_path(scenario_id, deployable_only=True)
    queue = _command_queue()
    command = queue.enqueue(
        "CLEANUP_FIXTURE",
        owner,
        {
            "scenario_id": scenario_id,
            "resource_group": "rg-aica-fixture-eus2",
            "verify_empty": True,
        },
    )
    typer.echo(f"queued={command.id} operator=Azure-MCP")


@fixture_app.command("cleanup-expired")
def fixture_cleanup_expired(
    resource_group: Annotated[str, typer.Option("--resource-group")],
    require_tag: Annotated[list[str], typer.Option("--require-tag")],
) -> None:
    """Delete only expired, doubly tagged synthetic resources; never delete the group."""

    settings = get_settings()
    if resource_group != settings.fixture_group:
        raise typer.BadParameter(
            f"resource group must exactly match configured fixture group {settings.fixture_group}"
        )
    if settings.delete_resource_group:
        raise typer.BadParameter("resource-group deletion is prohibited by this command")
    if not settings.azure_subscription_id:
        raise typer.BadParameter("AICA_AZURE_SUBSCRIPTION_ID is required")
    try:
        result = asyncio.run(
            AzureFixtureJanitor(
                settings.azure_subscription_id,
                resource_group,
                managed_identity_client_id=settings.azure_client_id,
                required_tags=require_tag,
            ).cleanup()
        )
    except FixtureCleanupError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"deleted_count={result['deleted_count']}")
    typer.echo(f"resource_types={','.join(result['resource_types'])}")
    typer.echo("resource_group_deleted=false")


if __name__ == "__main__":
    app()
