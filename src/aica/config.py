"""Runtime settings with safe local defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AICA_", env_file=".env", extra="ignore", case_sensitive=False
    )

    env: Literal["development", "test", "production"] = "development"
    data_dir: Path = Path("data/sample-runs")
    artifact_dir: Path = Path("artifacts")
    public_mode: bool = True
    model_adapter: Literal["replay", "foundry", "phi"] = "replay"
    model_deployment: str = "gpt-4o-mini"
    model_max_output_tokens: int = Field(default=400, ge=1, le=400)
    foundry_endpoint: str | None = None
    phi_endpoint: str | None = None
    policy_corpus_dir: Path = Path("data/policy-corpus")
    corpus_blob_endpoint: str | None = None
    corpus_blob_prefix: str = ""
    assistant_enabled: bool = True
    assurance_enabled: bool = True
    ai_evaluation_dir: Path = Path("data/ai-evaluations")
    ai_evaluation_mode: Literal["auto", "replay", "live"] = "auto"
    deployed_configuration_url: str | None = None
    deployed_source_commit: str = ""
    assurance_api_image_sha256: str = ""
    assistant_ui_image_sha256: str = ""
    assurance_job_image_sha256: str = ""
    mapping_benchmark_path: Path = Path("data/mapping-benchmark/human-labeled-examples.json")
    mapping_suggestion_path: Path = Path("data/ai-evaluations/mapping-suggestion.json")
    evidence_max_age_hours: int = Field(default=26, ge=1)
    signing_key_path: Path = Path(".local/aica-es256.pem")
    pseudonymization_secret: str = "local-development-only-change-me"  # noqa: S105
    phi_bearer_token: str | None = None
    phi_token_scope: str | None = None
    confirmation_ttl_seconds: int = Field(default=300, ge=1, le=3_600)
    request_limit_per_user_per_hour: int = Field(default=10, ge=1, le=100)

    azure_client_id: str | None = None
    azure_subscription_id: str | None = None
    azure_tenant_id: str | None = None
    azure_key_vault_url: str | None = None
    azure_key_name: str = "aica-assessment-signing"
    azure_log_analytics_workspace_id: str | None = None
    authorization_probe_endpoint: str | None = None
    authorization_probe_scope: str | None = None
    sentinel_dcr_endpoint: str | None = None
    sentinel_dcr_immutable_id: str | None = None
    azure_table_endpoint: str | None = None
    azure_command_table: str = "commandrequests"
    azure_review_table: str = "reviewdecisions"
    azure_rate_limit_table: str = "assistantratelimits"
    azure_assessment_job_resource_id: str | None = None
    azure_blob_endpoint: str | None = None
    azure_private_evidence_container: str = "aica-evidence"
    azure_public_evidence_container: str = "aica-public"
    trusted_signing_key_fingerprints: str = ""
    trusted_signing_key_id_prefix: str | None = None
    fixture_group: str = "rg-aica-fixture-eus2"
    delete_resource_group: bool = False

    github_repository: str | None = None
    github_app_id: int | None = Field(default=None, gt=0)
    github_app_installation_id: int | None = Field(default=None, gt=0)
    github_app_private_key: SecretStr | None = None
    github_installation_token: SecretStr | None = None


def get_settings() -> Settings:
    """Return settings; kept as a function for dependency injection in tests."""

    return Settings()
