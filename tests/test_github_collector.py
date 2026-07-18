from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from pydantic import ValidationError

from aica.collectors.base import CollectionRequest
from aica.collectors.github import (
    GITHUB_API_URL,
    GITHUB_APP_PERMISSIONS,
    GitHubAppCredentials,
    GitHubAuthenticationError,
    GitHubCollector,
    generate_github_app_jwt,
)
from aica.config import Settings
from aica.domain.models import ResultStatus
from aica.evaluation.engine import RuleEngine, default_rules
from aica.pipeline import AssessmentPipeline
from aica.profiles import AssessmentProfile


def _private_key_pem() -> tuple[rsa.RSAPrivateKey, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return key, pem


def _decode_segment(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _request(tmp_path: Path) -> CollectionRequest:
    now = datetime.now(UTC)
    return CollectionRequest(
        run_id="run-test",
        observation_window_start=now - timedelta(hours=1),
        observation_window_end=now,
        scope=("github:octo-org/assurance",),
        output_dir=tmp_path,
        assessed_git_commit="a" * 40,
    )


def _mock_successful_collection(
    collector: GitHubCollector,
    *,
    critical_alerts: list[dict[str, object]] | None = None,
) -> None:
    endpoints = list(collector._endpoints.values())
    for endpoint in endpoints[:3]:
        body = (
            {"advanced_security": {"status": "enabled"}}
            if endpoint.endswith("code-security-configuration")
            else {"status": "synthetic"}
        )
        respx.get(f"{GITHUB_API_URL}{endpoint}").mock(return_value=httpx.Response(200, json=body))
    respx.get(
        f"{GITHUB_API_URL}/repos/octo-org/assurance/code-scanning/alerts"
        "?state=open&severity=critical&per_page=100&page=1"
    ).mock(return_value=httpx.Response(200, json=critical_alerts or []))
    respx.get(
        f"{GITHUB_API_URL}/repos/octo-org/assurance/actions/workflows/supply-chain.yml/"
        f"runs?status=success&head_sha={'a' * 40}&per_page=100"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {
                        "id": 123,
                        "head_sha": "a" * 40,
                        "conclusion": "success",
                        "run_attempt": 1,
                    }
                ]
            },
        )
    )
    respx.get(
        f"{GITHUB_API_URL}/repos/octo-org/assurance/actions/runs/123/artifacts"
        "?per_page=100&page=1"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "artifacts": [
                    {
                        "id": 456,
                        "name": "sbom-api",
                        "digest": "sha256:" + "c" * 64,
                        "expired": False,
                        "workflow_run": {"id": 123, "head_sha": "a" * 40},
                    }
                ]
            },
        )
    )


def test_github_app_jwt_uses_rs256_and_bounded_claims() -> None:
    key, pem = _private_key_pem()
    credentials = GitHubAppCredentials(app_id=123456, installation_id=789012, private_key_pem=pem)

    encoded = generate_github_app_jwt(credentials, now=1_800_000_000)
    header_segment, payload_segment, signature_segment = encoded.split(".")
    header = json.loads(_decode_segment(header_segment))
    payload = json.loads(_decode_segment(payload_segment))

    assert header == {"alg": "RS256", "typ": "JWT"}
    assert payload == {
        "iat": 1_799_999_940,
        "exp": 1_800_000_540,
        "iss": "123456",
    }
    key.public_key().verify(
        _decode_segment(signature_segment),
        f"{header_segment}.{payload_segment}".encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    assert pem not in repr(credentials)


def test_github_app_jwt_rejects_non_rsa_private_key() -> None:
    credentials = GitHubAppCredentials(
        app_id=123456,
        installation_id=789012,
        private_key_pem="not-a-private-key",
    )

    with pytest.raises(GitHubAuthenticationError, match="valid unencrypted RSA PEM"):
        generate_github_app_jwt(credentials)


def test_pipeline_requires_one_complete_github_authentication_method(tmp_path: Path) -> None:
    profile = AssessmentProfile(
        name="github-test",
        description="GitHub configuration test",
        trigger="manual",
        scope=("github:octo-org/assurance",),
        collectors=("github",),
        objective_path=tmp_path / "objectives.json",
    )
    missing = Settings(env="test", github_repository="octo-org/assurance")
    with pytest.raises(ValueError, match="complete GITHUB_APP_ID"):
        AssessmentPipeline(missing)._collectors(profile)

    complete = Settings(
        env="test",
        github_repository="octo-org/assurance",
        github_app_id=123456,
        github_app_installation_id=789012,
        github_app_private_key="synthetic-private-key",
    )
    collectors = AssessmentPipeline(complete)._collectors(profile)
    assert len(collectors) == 1
    assert "synthetic-private-key" not in repr(complete)

    ambiguous = Settings(
        env="test",
        github_repository="octo-org/assurance",
        github_app_id=123456,
        github_app_installation_id=789012,
        github_app_private_key="synthetic-private-key",
        github_installation_token="synthetic-installation-token",
    )
    with pytest.raises(ValueError, match="not both"):
        AssessmentPipeline(ambiguous)._collectors(profile)


def test_settings_reject_non_positive_github_identifiers() -> None:
    with pytest.raises(ValidationError):
        Settings(github_app_id=0)


@respx.mock
@pytest.mark.asyncio
async def test_collector_mints_repository_scoped_installation_token(tmp_path: Path) -> None:
    _, pem = _private_key_pem()
    installation_token = "ghs_test-installation-token-that-must-not-be-evidence"  # noqa: S105 -- synthetic
    token_route = respx.post(f"{GITHUB_API_URL}/app/installations/789012/access_tokens").mock(
        return_value=httpx.Response(
            201,
            json={"token": installation_token, "expires_at": "2026-07-16T17:00:00Z"},
        )
    )
    collector = GitHubCollector(
        "octo-org/assurance",
        app_credentials=GitHubAppCredentials(
            app_id=123456, installation_id=789012, private_key_pem=pem
        ),
    )
    private_alert = {"message": "alert contents must not enter evidence"}
    _mock_successful_collection(collector, critical_alerts=[private_alert])

    evidence = await collector.collect(_request(tmp_path))

    assert token_route.called
    token_request = token_route.calls.last.request
    assert token_request.headers["Authorization"].startswith("Bearer eyJ")
    assert json.loads(token_request.content) == {
        "repositories": ["assurance"],
        "permissions": GITHUB_APP_PERMISSIONS,
    }
    assert len(evidence) == 6
    assert all(item.item.authorized for item in evidence)
    serialized = json.dumps([item.model_dump(mode="json") for item in evidence])
    assert installation_token not in serialized
    assert pem not in serialized
    assert private_alert["message"] not in serialized
    critical = next(item for item in evidence if item.item.source.endswith("critical_alerts"))
    assert critical.item.payload["unresolved_critical_alerts"] == 1
    ci_artifacts = next(item for item in evidence if item.item.source == "github.ci.artifacts")
    assert ci_artifacts.item.payload["workflow_run_id"] == 123
    for call in respx.calls:
        if call.request.method == "GET":
            assert call.request.headers["Authorization"] == f"Bearer {installation_token}"


@respx.mock
@pytest.mark.asyncio
async def test_collector_fails_closed_without_leaking_auth_response(tmp_path: Path) -> None:
    _, pem = _private_key_pem()
    secret_from_github = "ghs_rejected-secret-that-must-not-be-evidence"  # noqa: S105 -- synthetic
    respx.post(f"{GITHUB_API_URL}/app/installations/789012/access_tokens").mock(
        return_value=httpx.Response(401, json={"token": secret_from_github})
    )
    collector = GitHubCollector(
        "octo-org/assurance",
        app_credentials=GitHubAppCredentials(
            app_id=123456, installation_id=789012, private_key_pem=pem
        ),
    )

    evidence = await collector.collect(_request(tmp_path))

    assert len(evidence) == 6
    assert all(not item.item.authorized for item in evidence)
    assert all(item.item.collection_error for item in evidence)
    serialized = json.dumps([item.model_dump(mode="json") for item in evidence])
    assert secret_from_github not in serialized
    assert pem not in serialized
    assert len([call for call in respx.calls if call.request.method == "GET"]) == 0


@respx.mock
@pytest.mark.asyncio
async def test_short_lived_installation_token_skips_app_token_request(tmp_path: Path) -> None:
    installation_token = "ghs_pre_minted_workflow_token"  # noqa: S105 -- synthetic
    collector = GitHubCollector("octo-org/assurance", installation_token=installation_token)
    _mock_successful_collection(collector)

    evidence = await collector.collect(_request(tmp_path))

    assert len(evidence) == 6
    assert not any("/app/installations/" in str(call.request.url) for call in respx.calls)
    assert all(
        call.request.headers["Authorization"] == f"Bearer {installation_token}"
        for call in respx.calls
    )


@respx.mock
@pytest.mark.asyncio
async def test_collector_rejects_unrelated_successful_run_and_skips_artifact_lookup(
    tmp_path: Path,
) -> None:
    collector = GitHubCollector(
        "octo-org/assurance",
        installation_token="ghs_pre_minted_workflow_token",
    )
    endpoints = list(collector._endpoints.values())
    for endpoint in endpoints[:3]:
        body = (
            {"advanced_security": {"status": "enabled"}}
            if endpoint.endswith("code-security-configuration")
            else {"status": "synthetic"}
        )
        respx.get(f"{GITHUB_API_URL}{endpoint}").mock(return_value=httpx.Response(200, json=body))
    respx.get(
        f"{GITHUB_API_URL}/repos/octo-org/assurance/code-scanning/alerts"
        "?state=open&severity=critical&per_page=100&page=1"
    ).mock(return_value=httpx.Response(200, json=[]))
    respx.get(
        f"{GITHUB_API_URL}/repos/octo-org/assurance/actions/workflows/supply-chain.yml/"
        f"runs?status=success&head_sha={'a' * 40}&per_page=100"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "workflow_runs": [
                    {"id": 999, "head_sha": "b" * 40, "conclusion": "success"}
                ]
            },
        )
    )

    evidence = await collector.collect(_request(tmp_path))

    artifacts = next(item for item in evidence if item.item.source == "github.ci.artifacts")
    assert artifacts.item.payload == {
        "assessed_commit": "a" * 40,
        "workflow_run_id": None,
        "artifacts": [],
    }
    rule = next(rule for rule in default_rules() if rule.id == "R-SA-11-01")
    result = RuleEngine((rule,)).evaluate("run-test", [item.item for item in evidence])[0]
    assert result.status == ResultStatus.FAIL
    assert not any("/actions/runs/999/artifacts" in str(call.request.url) for call in respx.calls)
