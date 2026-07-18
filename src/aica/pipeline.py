"""Headless scope → collect → normalize → evaluate → assess → publish pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

from azure.core.exceptions import ResourceNotFoundError

from aica.collectors.ai import AiEvaluationCollector
from aica.collectors.azure import AzureEvidenceCollector, AzureRestClient
from aica.collectors.base import CollectedEvidence, CollectionRequest, Collector, write_collected
from aica.collectors.github import GitHubAppCredentials, GitHubCollector
from aica.collectors.replay import ReplayCollector
from aica.config import Settings
from aica.domain.models import (
    AssessmentMethod,
    AssessmentPackage,
    AssessmentRun,
    ControlObjective,
    ResultStatus,
    RunStatus,
    SystemRecord,
    TestResult,
)
from aica.evaluation.assessment import build_assessments
from aica.evaluation.diff import (
    AssessmentDiff,
    build_retests,
    diff_packages,
    link_findings_to_objectives,
)
from aica.evaluation.engine import RuleEngine
from aica.evidence.manifest import (
    CadCostBreakdown,
    Es256Signer,
    KeyVaultEs256Signer,
    LocalEs256Signer,
    SignedManifest,
    build_manifest,
    load_signed_manifest,
    sign_manifest,
    verify_manifest,
    verify_manifest_signature,
)
from aica.evidence.redaction import assert_public_safe, sanitize
from aica.evidence.store import AzureBlobArtifactStore
from aica.profiles import AssessmentProfile
from aica.reporting.reports import (
    executive_summary,
    oscal_assessment_results,
    render_html,
    risk_register_csv,
)
from aica.review_store import AzureTableReviewEventStore, overlay_review_events
from aica.telemetry import LogsIngestionPublisher
from aica.util.canonical import canonical_json_bytes, sha256_bytes, sha256_file
from aica.util.ids import new_id


def _git_commit() -> str:
    override = os.environ.get("AICA_ASSESSED_GIT_COMMIT") or os.environ.get("GITHUB_SHA")
    if override:
        return override
    try:
        git = shutil.which("git")
        if not git:
            return "0000000"
        result = subprocess.run(  # noqa: S603 - executable resolved with shutil.which
            [git, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "0000000"


def load_objectives(path: Path) -> tuple[ControlObjective, ...]:
    raw: Any = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        controls = {
            str(item["id"]): str(item.get("title", item["id"])) for item in raw.get("controls", [])
        }
        raw = raw.get("objectives", raw.get("control_objectives", []))
        if raw and "source_control" not in raw[0]:
            method_map = {
                "AUTOMATED": (AssessmentMethod.TEST,),
                "HYBRID": (AssessmentMethod.HYBRID,),
                "MANUAL": (AssessmentMethod.EXAMINE, AssessmentMethod.INTERVIEW),
            }
            raw = [
                {
                    "id": item["id"],
                    "source_control": item["control_id"],
                    "title": f"{controls.get(str(item['control_id']), item['control_id'])} — {item['id']}",
                    "objective": item["objective"],
                    "methods": method_map[str(item["method"])],
                    "subject_selector": item["subject_selector"],
                    "cadence": item["cadence"],
                    "evidence_requirements": item["evidence_requirements"],
                    "owner": item["owner"],
                    "automated": item["method"] == "AUTOMATED",
                    "limitations": (item["limitations"],) if item.get("limitations") else (),
                    "crosswalk": {},
                }
                for item in raw
            ]
    return tuple(ControlObjective.model_validate(item) for item in raw)


def load_system_record(path: Path) -> SystemRecord:
    """Load the version-controlled system boundary through the strict runtime contract."""

    return SystemRecord.model_validate_json(path.read_text(encoding="utf-8"))


def terminal_run_status(results: list[TestResult]) -> RunStatus:
    """Derive an honest terminal state without discarding a signed failure package."""

    if any(result.status == ResultStatus.ERROR for result in results):
        return RunStatus.FAILED
    if any(
        result.status == ResultStatus.NOT_RUN and result.reason_code != "MANUAL_REVIEW_REQUIRED"
        for result in results
    ):
        return RunStatus.FAILED
    if any(result.status in {ResultStatus.FAIL, ResultStatus.NOT_RUN} for result in results):
        return RunStatus.REVIEW_REQUIRED
    return RunStatus.COMPLETED


def release_gate_failed(results: list[TestResult]) -> bool:
    """Block test failures without treating pending human review as a test failure."""

    return any(
        result.status in {ResultStatus.FAIL, ResultStatus.ERROR}
        or (
            result.status == ResultStatus.NOT_RUN
            and result.reason_code != "MANUAL_REVIEW_REQUIRED"
        )
        for result in results
    )


class PriorRunIntegrityError(RuntimeError):
    """The requested prior run exists but its signed artifact chain is invalid."""


class AssessmentPipeline:
    def __init__(self, settings: Settings, *, engine: RuleEngine | None = None):
        self.settings = settings
        self.engine = engine or RuleEngine()

    def _collectors(self, profile: AssessmentProfile) -> list[Collector]:
        collectors: list[Collector] = []
        if "replay" in profile.collectors:
            if not profile.fixture_dir:
                raise ValueError("replay profile requires fixture_dir")
            collectors.append(ReplayCollector(profile.fixture_dir))
        if "azure" in profile.collectors:
            if not self.settings.azure_subscription_id:
                raise ValueError("AZURE_SUBSCRIPTION_ID is required for the Azure collector")
            if profile.name == "azure-dev" and self.settings.env == "production" and not (
                self.settings.authorization_probe_endpoint
                and self.settings.authorization_probe_scope
            ):
                raise ValueError(
                    "azure-dev production collection requires AUTHORIZATION_PROBE_ENDPOINT "
                    "and AUTHORIZATION_PROBE_SCOPE"
                )
            azure_client = AzureRestClient(
                managed_identity_client_id=self.settings.azure_client_id
                if self.settings.env == "production"
                else None
            )
            collectors.append(
                AzureEvidenceCollector(
                    azure_client,
                    subscription_id=self.settings.azure_subscription_id,
                    log_analytics_workspace_id=self.settings.azure_log_analytics_workspace_id,
                    authorization_probe_endpoint=self.settings.authorization_probe_endpoint,
                    authorization_probe_scope=self.settings.authorization_probe_scope,
                )
            )
        if "github" in profile.collectors:
            if not self.settings.github_repository:
                raise ValueError("GITHUB_REPOSITORY is required for the GitHub collector")
            installation_token = (
                self.settings.github_installation_token.get_secret_value()
                if self.settings.github_installation_token
                else None
            )
            app_configuration = (
                self.settings.github_app_id,
                self.settings.github_app_installation_id,
                self.settings.github_app_private_key,
            )
            if installation_token and any(value is not None for value in app_configuration):
                raise ValueError(
                    "configure either GITHUB_INSTALLATION_TOKEN or GitHub App credentials, not both"
                )
            app_credentials = None
            if not installation_token:
                app_id = self.settings.github_app_id
                installation_id = self.settings.github_app_installation_id
                private_key = self.settings.github_app_private_key
                if app_id is None or installation_id is None or private_key is None:
                    raise ValueError(
                        "GitHub collection requires GITHUB_INSTALLATION_TOKEN or the complete "
                        "GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, and GITHUB_APP_PRIVATE_KEY set"
                    )
                app_credentials = GitHubAppCredentials(
                    app_id=app_id,
                    installation_id=installation_id,
                    private_key_pem=private_key.get_secret_value(),
                )
            collectors.append(
                GitHubCollector(
                    self.settings.github_repository,
                    app_credentials=app_credentials,
                    installation_token=installation_token,
                )
            )
        if "ai" in profile.collectors:
            collectors.append(
                AiEvaluationCollector(
                    self.settings.ai_evaluation_dir,
                    settings=self.settings,
                )
            )
        unknown = set(profile.collectors) - {"replay", "azure", "github", "ai"}
        if unknown:
            raise ValueError(f"unknown collectors: {', '.join(sorted(unknown))}")
        return collectors

    def _artifact_store(self, container: str) -> AzureBlobArtifactStore | None:
        if not self.settings.azure_blob_endpoint:
            return None
        return AzureBlobArtifactStore(
            self.settings.azure_blob_endpoint,
            container,
            managed_identity_client_id=self.settings.azure_client_id,
        )

    def _default_signer(self) -> Es256Signer:
        if self.settings.env == "production":
            if not self.settings.azure_key_vault_url:
                raise RuntimeError("AICA_AZURE_KEY_VAULT_URL is required in production")
            return KeyVaultEs256Signer(
                self.settings.azure_key_vault_url,
                self.settings.azure_key_name,
                managed_identity_client_id=self.settings.azure_client_id,
            )
        return LocalEs256Signer(self.settings.signing_key_path)

    def _manifest_trust_errors(self, signed: SignedManifest) -> list[str]:
        trusted = {
            value.strip()
            for value in self.settings.trusted_signing_key_fingerprints.split(",")
            if value.strip()
        }
        errors: list[str] = []
        if trusted and signed.key_fingerprint not in trusted:
            errors.append("manifest signer is not in the trusted fingerprint allowlist")
        if self.settings.env == "production" and not trusted:
            errors.append("production prior-run verification has no trusted signer allowlist")
        prefix = self.settings.trusted_signing_key_id_prefix
        if prefix and not signed.key_id.startswith(prefix):
            errors.append("manifest key ID is outside the trusted Key Vault prefix")
        return errors

    def _prior_review_events(self) -> list[dict[str, Any]]:
        if not self.settings.azure_table_endpoint:
            return []
        return AzureTableReviewEventStore(
            self.settings.azure_table_endpoint,
            self.settings.azure_review_table,
            managed_identity_client_id=self.settings.azure_client_id,
        ).list_events()

    def _project_verified_prior_events(
        self,
        package: AssessmentPackage,
        manifest_digest: str,
    ) -> AssessmentPackage:
        events = self._prior_review_events()
        if not events:
            return package
        signed_remediation_ids = {item.id for item in package.remediations}
        raw = package.model_dump(mode="json")
        raw["run"]["manifest_digest"] = manifest_digest
        projected = overlay_review_events(raw, events)
        for assessment in projected.get("assessments", []):
            for projection_field in (
                "review_version",
                "reviewer_conclusion",
                "reviewer_rationale",
                "review_decision_id",
            ):
                assessment.pop(projection_field, None)
        for finding in projected.get("findings", []):
            finding.pop("review_version", None)
        try:
            validated = AssessmentPackage.model_validate(projected)
        except ValueError as exc:
            raise PriorRunIntegrityError(
                f"prior run {package.run.id!r} has invalid bound review events"
            ) from exc
        for remediation in validated.remediations:
            if remediation.id in signed_remediation_ids:
                continue
            if (
                remediation.artifact_hash != manifest_digest
                or remediation.artifact_run_id != package.run.id
            ):
                raise PriorRunIntegrityError(
                    f"remediation {remediation.id!r} is not bound to the verified prior run"
                )
        return validated

    def _local_prior_package_path(self, run_id: str) -> Path | None:
        roots = (
            self.settings.artifact_dir / "private",
            self.settings.artifact_dir / "public",
            self.settings.data_dir,
        )
        for root in roots:
            direct = root / run_id / "package.json"
            if direct.is_file():
                return direct
            if not root.is_dir():
                continue
            for candidate in sorted(root.glob("*/package.json")):
                try:
                    raw = json.loads(candidate.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                candidate_run = raw.get("run", raw.get("assessment_run", raw))
                if isinstance(candidate_run, dict) and candidate_run.get("id") == run_id:
                    return candidate
        return None

    def _load_verified_local_prior(self, run_id: str, package_path: Path) -> AssessmentPackage:
        manifest_path = package_path.parent / "run-manifest.json"
        if not manifest_path.is_file():
            raise PriorRunIntegrityError(f"prior run {run_id!r} has no signed manifest")
        try:
            signed = load_signed_manifest(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise PriorRunIntegrityError(f"prior run {run_id!r} manifest cannot be parsed") from exc
        errors = verify_manifest(signed, package_path.parent)
        errors.extend(self._manifest_trust_errors(signed))
        relative_package = package_path.relative_to(package_path.parent).as_posix()
        package_artifact = next(
            (
                artifact
                for artifact in signed.manifest.artifacts
                if artifact.path == relative_package
            ),
            None,
        )
        if package_artifact is None:
            errors.append(f"manifest does not cover {relative_package}")
        if signed.manifest.run_id != run_id:
            errors.append("manifest run ID does not match requested prior run")
        try:
            package_content = package_path.read_bytes()
        except OSError as exc:
            raise PriorRunIntegrityError(f"prior run {run_id!r} package cannot be read") from exc
        if (
            package_artifact is not None
            and sha256_bytes(package_content) != package_artifact.sha256
        ):
            errors.append(f"artifact digest mismatch: {relative_package}")
        if errors:
            raise PriorRunIntegrityError(
                f"prior run {run_id!r} failed integrity verification: {'; '.join(errors)}"
            )
        try:
            package = AssessmentPackage.model_validate_json(package_content)
        except ValueError as exc:
            raise PriorRunIntegrityError(f"prior run {run_id!r} package cannot be parsed") from exc
        if package.run.id != run_id:
            raise PriorRunIntegrityError("prior package run ID does not match requested prior run")
        return self._project_verified_prior_events(package, signed.manifest_sha256)

    def _load_verified_azure_prior_from_container(
        self,
        run_id: str,
        container: str,
    ) -> AssessmentPackage | None:
        store = self._artifact_store(container)
        if store is None:
            return None
        prefix = f"runs/{run_id}"
        try:
            package_content = bytes(store.client.download_blob(f"{prefix}/package.json").readall())
        except ResourceNotFoundError:
            return None
        try:
            manifest_content = bytes(
                store.client.download_blob(f"{prefix}/run-manifest.json").readall()
            )
            signed = SignedManifest.model_validate_json(manifest_content)
        except (ResourceNotFoundError, ValueError, json.JSONDecodeError) as exc:
            raise PriorRunIntegrityError(
                f"Azure prior run {run_id!r} has no valid signed manifest"
            ) from exc

        errors = verify_manifest_signature(signed)
        errors.extend(self._manifest_trust_errors(signed))
        if signed.manifest.run_id != run_id:
            errors.append("manifest run ID does not match requested prior run")
        for artifact in signed.manifest.artifacts:
            relative = PurePosixPath(artifact.path)
            if relative.is_absolute() or ".." in relative.parts:
                errors.append(f"artifact escapes package root: {artifact.path}")
                continue
            try:
                content = (
                    package_content
                    if artifact.path == "package.json"
                    else bytes(store.client.download_blob(f"{prefix}/{artifact.path}").readall())
                )
            except ResourceNotFoundError:
                errors.append(f"artifact missing: {artifact.path}")
                continue
            if sha256_bytes(content) != artifact.sha256:
                errors.append(f"artifact digest mismatch: {artifact.path}")
        if "package.json" not in {artifact.path for artifact in signed.manifest.artifacts}:
            errors.append("manifest does not cover package.json")
        if errors:
            raise PriorRunIntegrityError(
                f"Azure prior run {run_id!r} failed integrity verification: {'; '.join(errors)}"
            )
        try:
            package = AssessmentPackage.model_validate_json(package_content)
        except ValueError as exc:
            raise PriorRunIntegrityError(
                f"Azure prior run {run_id!r} package cannot be parsed"
            ) from exc
        if package.run.id != run_id:
            raise PriorRunIntegrityError("prior package run ID does not match requested prior run")
        return self._project_verified_prior_events(package, signed.manifest_sha256)

    async def _load_verified_prior(self, run_id: str) -> AssessmentPackage:
        if not run_id or "/" in run_id or "\\" in run_id or run_id in {".", ".."}:
            raise ValueError("prior_run_id must be a single run identifier")
        local = self._local_prior_package_path(run_id)
        if local is not None:
            return await asyncio.to_thread(self._load_verified_local_prior, run_id, local)
        if self.settings.azure_blob_endpoint:
            for container in (
                self.settings.azure_private_evidence_container,
                self.settings.azure_public_evidence_container,
            ):
                package = await asyncio.to_thread(
                    self._load_verified_azure_prior_from_container,
                    run_id,
                    container,
                )
                if package is not None:
                    return package
        raise FileNotFoundError(f"prior assessment run {run_id!r} was not found")

    async def _publish_evidence_artifacts(
        self,
        evidence: CollectedEvidence,
        run_root: Path,
        store: AzureBlobArtifactStore,
    ) -> CollectedEvidence:
        normalized_path = run_root / "evidence" / evidence.item.id / "normalized.json"
        blob_name = f"runs/{run_root.name}/evidence/{evidence.item.id}/normalized.json"
        url, version_id = await asyncio.to_thread(
            store.upload_file,
            normalized_path,
            blob_name,
            run_id=run_root.name,
            classification=evidence.item.classification.value,
        )
        updated = evidence.model_copy(
            update={
                "item": evidence.item.model_copy(
                    update={"private_artifact_uri": url, "blob_version": version_id}
                )
            }
        )
        write_collected(updated, run_root)
        return updated

    async def execute(
        self,
        profile: AssessmentProfile,
        *,
        signer: Es256Signer | None = None,
        prior_run_id: str | None = None,
        finding_ids: tuple[str, ...] | None = None,
    ) -> tuple[AssessmentPackage, Path]:
        if finding_ids and not prior_run_id:
            raise ValueError("finding_ids require prior_run_id")
        if self.settings.env == "production":
            if not self.settings.trusted_signing_key_fingerprints.strip():
                raise RuntimeError(
                    "AICA_TRUSTED_SIGNING_KEY_FINGERPRINTS is required in production"
                )
            if not (
                self.settings.sentinel_dcr_endpoint and self.settings.sentinel_dcr_immutable_id
            ):
                raise RuntimeError(
                    "AICA_SENTINEL_DCR_ENDPOINT and AICA_SENTINEL_DCR_IMMUTABLE_ID are required"
                )
        system = load_system_record(profile.system_record_path)
        prior_package = (
            await self._load_verified_prior(prior_run_id) if prior_run_id is not None else None
        )
        started = datetime.now(UTC)
        run_id = new_id()
        run_root = self.settings.artifact_dir / "private" / run_id
        run_root.mkdir(parents=True, exist_ok=False)
        run = AssessmentRun(
            id=run_id,
            trigger="retest" if prior_run_id else profile.trigger,
            scope=profile.scope,
            observation_window_start=started - timedelta(hours=profile.observation_window_hours),
            observation_window_end=started,
            git_commit=_git_commit(),
            collector_version="1.0.0",
            evaluator_version="1.0.0",
            started_at=started,
            status=RunStatus.COLLECTING,
            estimated_cost_cad=profile.estimated_cost_cad,
            prior_run_id=prior_run_id,
        )
        request = CollectionRequest(
            run_id=run_id,
            observation_window_start=run.observation_window_start,
            observation_window_end=run.observation_window_end,
            scope=profile.scope,
            output_dir=run_root,
            assessed_git_commit=run.git_commit,
            max_age=timedelta(hours=self.settings.evidence_max_age_hours),
        )
        collectors = self._collectors(profile)
        batches = await asyncio.gather(*(collector.collect(request) for collector in collectors))
        collected: list[CollectedEvidence] = [item for batch in batches for item in batch]
        for evidence in collected:
            write_collected(evidence, run_root)

        private_store = self._artifact_store(self.settings.azure_private_evidence_container)
        if private_store:
            collected = list(
                await asyncio.gather(
                    *(
                        self._publish_evidence_artifacts(evidence, run_root, private_store)
                        for evidence in collected
                    )
                )
            )

        objectives = load_objectives(profile.objective_path)
        evidence_items = [item.item for item in collected]
        results = self.engine.evaluate(run_id, evidence_items)
        assessments, observations, findings, risks = build_assessments(run_id, objectives, results)
        linked_findings = link_findings_to_objectives(findings, objectives, results)
        ended = datetime.now(UTC)
        run = run.model_copy(update={"ended_at": ended, "status": terminal_run_status(results)})
        current_package = AssessmentPackage(
            run=run,
            system=system,
            objectives=objectives,
            evidence=tuple(evidence_items),
            test_results=tuple(results),
            assessments=tuple(assessments),
            observations=tuple(observations),
            findings=linked_findings,
            risks=tuple(risks),
        )
        comparison: AssessmentDiff | None = None
        if prior_package is not None:
            new_retests = build_retests(
                prior_package,
                current_package,
                finding_ids=finding_ids,
                tested_at=ended,
            )
            package = AssessmentPackage.model_validate(
                {
                    **current_package.model_dump(mode="python"),
                    "findings": (*prior_package.findings, *current_package.findings),
                    "risks": (*prior_package.risks, *current_package.risks),
                    "exceptions": prior_package.exceptions,
                    "remediations": prior_package.remediations,
                    "retests": (*prior_package.retests, *new_retests),
                    "decisions": prior_package.decisions,
                }
            )
            comparison = diff_packages(prior_package, package)
        else:
            package = current_package
        self._write_private_reports(package, run_root, comparison)
        signer = signer or self._default_signer()
        private_manifest = self._write_signed_manifest(
            package,
            run_root,
            signer,
            cost_breakdown=profile.cost_breakdown,
            public=False,
        )
        trust_errors = self._manifest_trust_errors(private_manifest)
        if trust_errors:
            raise RuntimeError("new assessment signer is untrusted: " + "; ".join(trust_errors))
        public_root = self._write_public_package(
            package,
            signer,
            profile.cost_breakdown,
            comparison,
        )
        if private_store:
            await asyncio.to_thread(
                private_store.upload_tree,
                run_root,
                prefix=f"runs/{run_id}",
                run_id=run_id,
                classification="INTERNAL",
            )
        public_store = self._artifact_store(self.settings.azure_public_evidence_container)
        if public_store:
            await asyncio.to_thread(
                public_store.upload_tree,
                public_root,
                prefix=f"runs/{run_id}",
                run_id=run_id,
                classification="PUBLIC",
            )
        if self.settings.sentinel_dcr_endpoint and self.settings.sentinel_dcr_immutable_id:
            telemetry = LogsIngestionPublisher(
                self.settings.sentinel_dcr_endpoint,
                self.settings.sentinel_dcr_immutable_id,
                managed_identity_client_id=self.settings.azure_client_id,
            )
            try:
                await telemetry.publish_assurance_run(package.run)
            finally:
                await telemetry.close()
        return package, run_root

    @staticmethod
    def _write_private_reports(
        package: AssessmentPackage,
        run_root: Path,
        comparison: AssessmentDiff | None = None,
    ) -> None:
        outputs: dict[str, bytes] = {
            "package.json": canonical_json_bytes(package),
            "executive-summary.json": canonical_json_bytes(executive_summary(package)),
            "assessment-results.json": canonical_json_bytes(oscal_assessment_results(package)),
            "assessment-report.html": sanitize(render_html(package)).encode("utf-8"),
            "risk-register.csv": risk_register_csv(package).encode("utf-8"),
        }
        if comparison is not None:
            outputs["assessment-diff.json"] = canonical_json_bytes(comparison)
        for name, content in outputs.items():
            (run_root / name).write_bytes(content)

    @staticmethod
    def _write_signed_manifest(
        package: AssessmentPackage,
        run_root: Path,
        signer: Es256Signer,
        *,
        cost_breakdown: CadCostBreakdown,
        public: bool,
    ) -> SignedManifest:
        paths = [
            path
            for path in run_root.rglob("*")
            if path.is_file() and path.name not in {"run-manifest.json"}
        ]
        unsigned = build_manifest(
            run_id=package.run.id,
            root=run_root,
            paths=paths,
            git_commit=package.run.git_commit,
            collector_version=package.run.collector_version,
            evaluator_version=package.run.evaluator_version,
            cost_estimate_cad=package.run.estimated_cost_cad,
            cost_breakdown=cost_breakdown,
            public=public,
        )
        signed = sign_manifest(unsigned, signer)
        (run_root / "run-manifest.json").write_bytes(canonical_json_bytes(signed))
        return signed

    def _write_public_package(
        self,
        package: AssessmentPackage,
        signer: Es256Signer,
        cost_breakdown: CadCostBreakdown,
        comparison: AssessmentDiff | None = None,
    ) -> Path:
        public_root = self.settings.artifact_dir / "public" / package.run.id
        public_root.mkdir(parents=True, exist_ok=False)
        raw_package = package.model_dump(mode="json")
        public_package = sanitize(raw_package)
        for evidence in public_package.get("evidence", []):
            evidence["private_artifact_uri"] = "private://withheld"
            evidence.pop("blob_version", None)
        outputs = {
            "package.json": canonical_json_bytes(public_package),
            "executive-summary.json": canonical_json_bytes(sanitize(executive_summary(package))),
            "assessment-results.json": canonical_json_bytes(
                sanitize(oscal_assessment_results(package))
            ),
            "assessment-report.html": str(sanitize(render_html(package))).encode("utf-8"),
            "risk-register.csv": risk_register_csv(package).encode("utf-8"),
        }
        if comparison is not None:
            outputs["assessment-diff.json"] = canonical_json_bytes(
                sanitize(comparison.model_dump(mode="json"))
            )
        for name, content in outputs.items():
            text = content.decode("utf-8")
            assert_public_safe(text)
            (public_root / name).write_bytes(content)
        self._write_signed_manifest(
            package,
            public_root,
            signer,
            cost_breakdown=cost_breakdown,
            public=True,
        )
        return public_root


def mutate_check(path: Path) -> bool:
    """Small helper for demos: returns whether a file's digest changes after one-byte mutation."""

    before = sha256_file(path)
    content = path.read_bytes()
    if not content:
        return False
    changed = bytes([content[0] ^ 1]) + content[1:]
    return before != hashlib.sha256(changed).hexdigest()
