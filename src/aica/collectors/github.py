"""Read-only GitHub collector using least-privilege GitHub App authentication."""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from aica.collectors.base import CollectedEvidence, CollectionRequest, envelope

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
GITHUB_APP_PERMISSIONS = {
    "actions": "read",
    "administration": "read",
    "security_events": "read",
}
MAX_GITHUB_PAGES = 100


class GitHubAuthenticationError(RuntimeError):
    """GitHub App authentication failed without exposing credential material."""


@dataclass(frozen=True)
class GitHubAppCredentials:
    """Long-lived inputs used only to mint a short-lived installation token."""

    app_id: int
    installation_id: int
    private_key_pem: str = field(repr=False)

    def __post_init__(self) -> None:
        if self.app_id <= 0:
            raise ValueError("GitHub App ID must be a positive integer")
        if self.installation_id <= 0:
            raise ValueError("GitHub App installation ID must be a positive integer")
        if not self.private_key_pem.strip():
            raise ValueError("GitHub App private key must not be empty")


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def generate_github_app_jwt(credentials: GitHubAppCredentials, *, now: int | None = None) -> str:
    """Create GitHub's RS256 App JWT without adding a JWT dependency."""

    timestamp = int(time.time()) if now is None else now
    header = _base64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _base64url(
        json.dumps(
            {
                "iat": timestamp - 60,
                "exp": timestamp + 9 * 60,
                "iss": str(credentials.app_id),
            },
            separators=(",", ":"),
        ).encode()
    )
    signing_input = f"{header}.{payload}".encode("ascii")
    try:
        loaded_key = serialization.load_pem_private_key(
            credentials.private_key_pem.encode("utf-8"), password=None
        )
    except (TypeError, ValueError) as exc:
        raise GitHubAuthenticationError(
            "GitHub App private key is not a valid unencrypted RSA PEM key"
        ) from exc
    if not isinstance(loaded_key, rsa.RSAPrivateKey):
        raise GitHubAuthenticationError("GitHub App private key must be an RSA key")
    signature = loaded_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_base64url(signature)}"


class GitHubCollector:
    name = "github"
    version = "3.0.0"

    def __init__(
        self,
        repository: str,
        *,
        app_credentials: GitHubAppCredentials | None = None,
        installation_token: str | None = None,
    ):
        owner, separator, name = repository.partition("/")
        if (
            not separator
            or not owner
            or not name
            or "/" in name
            or any(character.isspace() for character in repository)
        ):
            raise ValueError("GitHub repository must use owner/name form")
        if (app_credentials is None) == (installation_token is None):
            raise ValueError(
                "configure exactly one GitHub authentication method: App credentials or an installation token"
            )
        if installation_token is not None and not installation_token.strip():
            raise ValueError("GitHub installation token must not be empty")
        self.repository = repository
        self.repository_name = name
        self._app_credentials = app_credentials
        self._installation_token = installation_token.strip() if installation_token else None

    @property
    def _endpoints(self) -> dict[str, str]:
        return {
            "github.branch_protection": (f"/repos/{self.repository}/branches/main/protection"),
            "github.actions.permissions": f"/repos/{self.repository}/actions/permissions",
            "github.code_security": f"/repos/{self.repository}/code-security-configuration",
            "github.code_security.critical_alerts": (
                f"/repos/{self.repository}/code-scanning/alerts"
                "?state=open&severity=critical&per_page=100"
            ),
            "github.ci.runs": (
                f"/repos/{self.repository}/actions/workflows/supply-chain.yml/"
                "runs?status=success&head_sha={assessed_commit}&per_page=100"
            ),
            "github.ci.artifacts": (
                f"/repos/{self.repository}/actions/runs/"
                "{workflow_run_id}/artifacts?per_page=100"
            ),
        }

    async def _get_installation_token(self, client: httpx.AsyncClient) -> str:
        if self._installation_token is not None:
            return self._installation_token
        if self._app_credentials is None:  # pragma: no cover - guarded by __init__
            raise GitHubAuthenticationError("GitHub App credentials are unavailable")

        app_jwt = generate_github_app_jwt(self._app_credentials)
        try:
            response = await client.post(
                f"/app/installations/{self._app_credentials.installation_id}/access_tokens",
                headers={"Authorization": f"Bearer {app_jwt}"},
                json={
                    "repositories": [self.repository_name],
                    "permissions": GITHUB_APP_PERMISSIONS,
                },
            )
        except httpx.HTTPError as exc:
            raise GitHubAuthenticationError(
                "GitHub installation-token request failed in transit"
            ) from exc
        if response.status_code != 201:
            raise GitHubAuthenticationError(
                f"GitHub rejected the installation-token request with HTTP {response.status_code}"
            )
        try:
            token = response.json().get("token")
        except (AttributeError, ValueError) as exc:
            raise GitHubAuthenticationError(
                "GitHub installation-token response was malformed"
            ) from exc
        if not isinstance(token, str) or not token:
            raise GitHubAuthenticationError("GitHub installation-token response omitted the token")
        return token

    def _authentication_failure(
        self, request: CollectionRequest, error: GitHubAuthenticationError
    ) -> list[CollectedEvidence]:
        return [
            envelope(
                request=request,
                source=source,
                collector_version=self.version,
                query={"method": "GET", "url": url},
                raw_payload={"error_type": type(error).__name__},
                authorized=False,
                collection_error="GitHub App authentication failed before evidence collection",
            )
            for source, url in self._endpoints.items()
        ]

    def _evidence(
        self,
        request: CollectionRequest,
        *,
        source: str,
        url: str,
        payload: Any,
        status: int | None = None,
        error: str | None = None,
    ) -> CollectedEvidence:
        return envelope(
            request=request,
            source=source,
            collector_version=self.version,
            query={"method": "GET", "url": url},
            raw_payload=payload,
            authorized=status not in {401, 403},
            collection_error=(
                error
                if error is not None
                else (
                    None
                    if status is not None and 200 <= status < 300
                    else f"GitHub returned HTTP {status}"
                )
            ),
        )

    async def _collect_simple_endpoint(
        self,
        client: httpx.AsyncClient,
        request: CollectionRequest,
        *,
        token: str,
        source: str,
        url: str,
    ) -> CollectedEvidence:
        try:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            return self._evidence(
                request,
                source=source,
                url=url,
                payload={"error_type": type(exc).__name__},
                error=f"collector transport failure: {type(exc).__name__}",
            )
        try:
            body: Any = response.json() if response.content else {}
        except ValueError:
            body = {"response_type": "non-json"}
        return self._evidence(
            request,
            source=source,
            url=url,
            payload=body,
            status=response.status_code,
        )

    async def _collect_critical_alert_count(
        self,
        client: httpx.AsyncClient,
        request: CollectionRequest,
        *,
        token: str,
    ) -> CollectedEvidence:
        base_url = f"/repos/{self.repository}/code-scanning/alerts"
        count = 0
        pages = 0
        status: int | None = None
        for page in range(1, MAX_GITHUB_PAGES + 1):
            url = (
                f"{base_url}?state=open&severity=critical&per_page=100&page={page}"
            )
            try:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                return self._evidence(
                    request,
                    source="github.code_security.critical_alerts",
                    url=base_url,
                    payload={"unresolved_critical_alerts": None, "pages_completed": pages},
                    error=f"collector transport failure: {type(exc).__name__}",
                )
            status = response.status_code
            if not 200 <= status < 300:
                return self._evidence(
                    request,
                    source="github.code_security.critical_alerts",
                    url=base_url,
                    payload={"unresolved_critical_alerts": None, "pages_completed": pages},
                    status=status,
                )
            try:
                body = response.json()
            except ValueError:
                body = None
            if not isinstance(body, list):
                return self._evidence(
                    request,
                    source="github.code_security.critical_alerts",
                    url=base_url,
                    payload={"unresolved_critical_alerts": None, "pages_completed": pages},
                    status=status,
                    error="GitHub code-scanning response was malformed",
                )
            count += len(body)
            pages = page
            if len(body) < 100:
                break
        else:
            return self._evidence(
                request,
                source="github.code_security.critical_alerts",
                url=base_url,
                payload={"unresolved_critical_alerts": None, "pages_completed": pages},
                status=status,
                error="GitHub code-scanning alert pagination exceeded the safe bound",
            )
        return self._evidence(
            request,
            source="github.code_security.critical_alerts",
            url=base_url,
            payload={"unresolved_critical_alerts": count, "pages_completed": pages},
            status=status,
        )

    async def _collect_ci_evidence(
        self,
        client: httpx.AsyncClient,
        request: CollectionRequest,
        *,
        token: str,
    ) -> list[CollectedEvidence]:
        commit = (request.assessed_git_commit or "").casefold()
        runs_url = (
            f"/repos/{self.repository}/actions/workflows/supply-chain.yml/"
            f"runs?status=success&head_sha={commit}&per_page=100"
        )
        artifact_template = f"/repos/{self.repository}/actions/runs/{{run_id}}/artifacts"
        if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", commit):
            error = "assessed Git commit is unavailable or invalid"
            return [
                self._evidence(
                    request,
                    source="github.ci.runs",
                    url=runs_url,
                    payload={"assessed_commit": commit, "workflow_runs": []},
                    error=error,
                ),
                self._evidence(
                    request,
                    source="github.ci.artifacts",
                    url=artifact_template,
                    payload={
                        "assessed_commit": commit,
                        "workflow_run_id": None,
                        "artifacts": [],
                    },
                    error=error,
                ),
            ]
        try:
            response = await client.get(
                runs_url,
                headers={"Authorization": f"Bearer {token}"},
            )
        except httpx.HTTPError as exc:
            error = f"collector transport failure: {type(exc).__name__}"
            return [
                self._evidence(
                    request,
                    source="github.ci.runs",
                    url=runs_url,
                    payload={"assessed_commit": commit, "workflow_runs": []},
                    error=error,
                ),
                self._evidence(
                    request,
                    source="github.ci.artifacts",
                    url=artifact_template,
                    payload={
                        "assessed_commit": commit,
                        "workflow_run_id": None,
                        "artifacts": [],
                    },
                    error=error,
                ),
            ]
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = None
        if not 200 <= response.status_code < 300 or not isinstance(body, dict):
            response_error = (
                None
                if isinstance(body, dict)
                else "GitHub workflow-runs response was malformed"
            )
            return [
                self._evidence(
                    request,
                    source="github.ci.runs",
                    url=runs_url,
                    payload={"assessed_commit": commit, "workflow_runs": []},
                    status=response.status_code,
                    error=response_error,
                ),
                self._evidence(
                    request,
                    source="github.ci.artifacts",
                    url=artifact_template,
                    payload={
                        "assessed_commit": commit,
                        "workflow_run_id": None,
                        "artifacts": [],
                    },
                    status=response.status_code,
                    error=response_error,
                ),
            ]
        raw_runs = body.get("workflow_runs", [])
        if not isinstance(raw_runs, list):
            raw_runs = []
        runs = [
            {
                "run_id": item.get("id"),
                "head_sha": str(item.get("head_sha", "")).casefold(),
                "conclusion": item.get("conclusion"),
                "run_attempt": item.get("run_attempt"),
            }
            for item in raw_runs
            if isinstance(item, dict)
            and str(item.get("head_sha", "")).casefold() == commit
            and str(item.get("conclusion", "")).casefold() == "success"
            and isinstance(item.get("id"), int)
        ]
        runs_evidence = self._evidence(
            request,
            source="github.ci.runs",
            url=runs_url,
            payload={"assessed_commit": commit, "workflow_runs": runs},
            status=response.status_code,
        )
        selected = runs[0] if runs else None
        if selected is None:
            return [
                runs_evidence,
                self._evidence(
                    request,
                    source="github.ci.artifacts",
                    url=artifact_template,
                    payload={
                        "assessed_commit": commit,
                        "workflow_run_id": None,
                        "artifacts": [],
                    },
                    status=200,
                ),
            ]
        selected_run_id = selected.get("run_id")
        if not isinstance(selected_run_id, int):  # pragma: no cover - filtered above
            raise RuntimeError("selected GitHub workflow run omitted its numeric ID")
        run_id = selected_run_id
        artifacts: list[dict[str, Any]] = []
        pages = 0
        for page in range(1, MAX_GITHUB_PAGES + 1):
            artifacts_url = (
                f"/repos/{self.repository}/actions/runs/{run_id}/artifacts"
                f"?per_page=100&page={page}"
            )
            try:
                artifact_response = await client.get(
                    artifacts_url,
                    headers={"Authorization": f"Bearer {token}"},
                )
            except httpx.HTTPError as exc:
                return [
                    runs_evidence,
                    self._evidence(
                        request,
                        source="github.ci.artifacts",
                        url=artifacts_url,
                        payload={
                            "assessed_commit": commit,
                            "workflow_run_id": run_id,
                            "artifacts": artifacts,
                        },
                        error=f"collector transport failure: {type(exc).__name__}",
                    ),
                ]
            try:
                artifact_body = artifact_response.json() if artifact_response.content else {}
            except ValueError:
                artifact_body = None
            if not 200 <= artifact_response.status_code < 300 or not isinstance(
                artifact_body, dict
            ):
                return [
                    runs_evidence,
                    self._evidence(
                        request,
                        source="github.ci.artifacts",
                        url=artifacts_url,
                        payload={
                            "assessed_commit": commit,
                            "workflow_run_id": run_id,
                            "artifacts": artifacts,
                        },
                        status=artifact_response.status_code,
                        error=(
                            None
                            if isinstance(artifact_body, dict)
                            else "GitHub workflow-artifacts response was malformed"
                        ),
                    ),
                ]
            raw_artifacts = artifact_body.get("artifacts", [])
            if not isinstance(raw_artifacts, list):
                raw_artifacts = []
            for item in raw_artifacts:
                if not isinstance(item, dict):
                    continue
                workflow_run = item.get("workflow_run", {})
                if not isinstance(workflow_run, dict):
                    workflow_run = {}
                artifacts.append(
                    {
                        "artifact_id": item.get("id"),
                        "name": item.get("name"),
                        "digest": item.get("digest"),
                        "expired": item.get("expired"),
                        "workflow_run_id": workflow_run.get("id"),
                        "head_sha": str(workflow_run.get("head_sha", "")).casefold(),
                    }
                )
            pages = page
            if len(raw_artifacts) < 100:
                return [
                    runs_evidence,
                    self._evidence(
                        request,
                        source="github.ci.artifacts",
                        url=artifacts_url,
                        payload={
                            "assessed_commit": commit,
                            "workflow_run_id": run_id,
                            "pages_completed": pages,
                            "artifacts": artifacts,
                        },
                        status=artifact_response.status_code,
                    ),
                ]
        return [
            runs_evidence,
            self._evidence(
                request,
                source="github.ci.artifacts",
                url=artifact_template.format(run_id=run_id),
                payload={
                    "assessed_commit": commit,
                    "workflow_run_id": run_id,
                    "pages_completed": pages,
                    "artifacts": artifacts,
                },
                status=200,
                error="GitHub workflow-artifact pagination exceeded the safe bound",
            ),
        ]

    async def collect(self, request: CollectionRequest) -> list[CollectedEvidence]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        async with httpx.AsyncClient(
            base_url=GITHUB_API_URL, headers=headers, timeout=30
        ) as client:
            try:
                token = await self._get_installation_token(client)
            except GitHubAuthenticationError as exc:
                return self._authentication_failure(request, exc)

            output = [
                await self._collect_simple_endpoint(
                    client,
                    request,
                    token=token,
                    source=source,
                    url=url,
                )
                for source, url in list(self._endpoints.items())[:3]
            ]
            output.append(
                await self._collect_critical_alert_count(
                    client,
                    request,
                    token=token,
                )
            )
            output.extend(await self._collect_ci_evidence(client, request, token=token))
            return output
