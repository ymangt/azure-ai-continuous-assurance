"""Read-only Azure REST collectors authenticated with Entra credentials."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import Any
from urllib.parse import urlsplit

import httpx
from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential

from aica.collectors.base import CollectedEvidence, CollectionRequest, envelope

ARM_SCOPE = "https://management.azure.com/.default"
LOG_SCOPE = "https://api.loganalytics.io/.default"


@dataclass(frozen=True)
class AzureQuery:
    source: str
    method: str
    url: str
    api_version: str | None = None
    params: dict[str, str] | None = None
    body: dict[str, Any] | None = None
    token_scope: str = ARM_SCOPE


class AzureRestClient:
    def __init__(self, *, managed_identity_client_id: str | None = None):
        self.credential = (
            ManagedIdentityCredential(client_id=managed_identity_client_id)
            if managed_identity_client_id
            else DefaultAzureCredential(exclude_interactive_browser_credential=True)
        )

    async def request(self, query: AzureQuery) -> tuple[int, Any]:
        token = await self.credential.get_token(query.token_scope)
        parameters = dict(query.params or {})
        if query.api_version:
            parameters["api-version"] = query.api_version
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.request(
                query.method,
                query.url,
                params=parameters or None,
                json=query.body,
                headers={"Authorization": f"Bearer {token.token}"},
            )
            try:
                body = response.json()
            except ValueError:
                body = {"text": response.text[:2_000]}
            if 200 <= response.status_code < 300 and isinstance(body, dict):
                while body.get("nextLink"):
                    page = await client.get(
                        str(body["nextLink"]),
                        headers={"Authorization": f"Bearer {token.token}"},
                    )
                    page.raise_for_status()
                    next_body = page.json()
                    body.setdefault("value", []).extend(next_body.get("value", []))
                    body["nextLink"] = next_body.get("nextLink")
        return response.status_code, body

    async def get_token(self, scope: str) -> str:
        """Return a short-lived token for a configured negative authorization probe."""

        token = await self.credential.get_token(scope)
        return token.token

    async def close(self) -> None:
        await self.credential.close()


class AzureEvidenceCollector:
    name = "azure"
    version = "1.0.0"

    def __init__(
        self,
        client: AzureRestClient,
        *,
        subscription_id: str,
        log_analytics_workspace_id: str | None = None,
        authorization_probe_endpoint: str | None = None,
        authorization_probe_scope: str | None = None,
    ):
        if (authorization_probe_endpoint is None) != (authorization_probe_scope is None):
            raise ValueError(
                "authorization probe endpoint and token scope must be configured together"
            )
        if authorization_probe_endpoint is not None:
            parsed = urlsplit(authorization_probe_endpoint)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    "authorization probe endpoint must be an HTTPS URL without credentials, query, or fragment"
                )
            if not parsed.path.startswith("/api/"):
                raise ValueError("authorization probe endpoint must target an API path")
        self.client = client
        self.subscription_id = subscription_id
        self.log_analytics_workspace_id = log_analytics_workspace_id
        self.authorization_probe_endpoint = authorization_probe_endpoint
        self.authorization_probe_scope = authorization_probe_scope

    def queries(self, request: CollectionRequest) -> list[AzureQuery]:
        subscription = f"/subscriptions/{self.subscription_id}"
        management = "https://management.azure.com"
        scope_filter = " or ".join(f"id startswith '{scope}'" for scope in request.scope)
        resource_graph_query = "Resources"
        if scope_filter:
            resource_graph_query += f" | where {scope_filter}"
        queries = [
            AzureQuery(
                source="azure.resource_graph.inventory",
                method="POST",
                url=f"{management}/providers/Microsoft.ResourceGraph/resources",
                api_version="2022-10-01",
                body={"subscriptions": [self.subscription_id], "query": resource_graph_query},
            ),
            AzureQuery(
                source="azure.policy.assignments",
                method="GET",
                url=f"{management}{subscription}/providers/Microsoft.Authorization/policyAssignments",
                api_version="2023-04-01",
            ),
            AzureQuery(
                source="azure.policy.states",
                method="POST",
                url=(
                    f"{management}{subscription}/providers/Microsoft.PolicyInsights/"
                    "policyStates/latest/queryResults"
                ),
                api_version="2019-10-01",
                body={"$top": 1000},
            ),
            AzureQuery(
                source="azure.activity.changes",
                method="GET",
                url=f"{management}{subscription}/providers/Microsoft.Insights/eventtypes/management/values",
                api_version="2015-04-01",
                params={
                    "$filter": (
                        f"eventTimestamp ge '{request.observation_window_start.astimezone(UTC).isoformat()}' "
                        f"and eventTimestamp le '{request.observation_window_end.astimezone(UTC).isoformat()}'"
                    )
                },
            ),
        ]
        approved_rbac_scopes = [
            scope.rstrip("/")
            for scope in request.scope
            if scope.casefold().startswith(f"{subscription}/resourcegroups/".casefold())
        ]
        # A profile should normally name project resource groups. Falling back to the
        # subscription keeps collection useful, but never silently drops RBAC evidence.
        for index, rbac_scope in enumerate(approved_rbac_scopes or [subscription], start=1):
            queries.append(
                AzureQuery(
                    source=f"azure.rbac.assignments.scope-{index}",
                    method="GET",
                    url=(
                        f"{management}{rbac_scope}/providers/"
                        "Microsoft.Authorization/roleAssignments"
                    ),
                    api_version="2022-04-01",
                )
            )
        if self.log_analytics_workspace_id:
            queries.extend(
                [
                    AzureQuery(
                        source="sentinel.risky_changes",
                        method="POST",
                        url=(
                            "https://api.loganalytics.azure.com/v1/workspaces/"
                            f"{self.log_analytics_workspace_id}/query"
                        ),
                        body={
                            "query": (
                                "AzureActivity | where TimeGenerated >= ago(14d) "
                                "| summarize Changes=count() by OperationNameValue, ActivityStatusValue "
                                "| union (print OperationNameValue='AICA_MONITOR_HEALTH', "
                                "ActivityStatusValue='Healthy', Changes=0)"
                            )
                        },
                        token_scope=LOG_SCOPE,
                    ),
                    AzureQuery(
                        source="sentinel.assurance_health",
                        method="POST",
                        url=(
                            "https://api.loganalytics.azure.com/v1/workspaces/"
                            f"{self.log_analytics_workspace_id}/query"
                        ),
                        body={
                            "query": (
                                "AicaAssurance_CL | where TimeGenerated >= ago(14d) "
                                "| summarize arg_max(TimeGenerated, *) by RunId"
                            )
                        },
                        token_scope=LOG_SCOPE,
                    ),
                    AzureQuery(
                        source="ai.operational_events",
                        method="POST",
                        url=(
                            "https://api.loganalytics.azure.com/v1/workspaces/"
                            f"{self.log_analytics_workspace_id}/query"
                        ),
                        body={
                            "query": (
                                "AicaToolSecurity_CL | where TimeGenerated >= ago(14d) "
                                "| project evaluation_id=CorrelationId, requested_tool=ToolName, "
                                "confirmation_state=Reason, tool_result_status=Decision"
                            )
                        },
                        token_scope=LOG_SCOPE,
                    ),
                ]
            )
        return queries

    @staticmethod
    def _normalize_log_query(body: Any) -> Any:
        """Add named row records while preserving the original Log Analytics result."""

        if not isinstance(body, dict):
            return body
        records: list[dict[str, Any]] = []
        for table in body.get("tables", []):
            if not isinstance(table, dict):
                continue
            columns = [
                str(column.get("name", ""))
                for column in table.get("columns", [])
                if isinstance(column, dict)
            ]
            for row in table.get("rows", []):
                if isinstance(row, list):
                    records.append(dict(zip(columns, row, strict=False)))
        return {**body, "records": records}

    async def _collect_diagnostic_settings(
        self,
        request: CollectionRequest,
        resource_graph_body: Any,
    ) -> CollectedEvidence:
        resources = (
            resource_graph_body.get("data", []) if isinstance(resource_graph_body, dict) else []
        )
        resource_records = [
            {
                "resource_id": str(item.get("id")),
                "resource_type": str(item.get("type", "unknown")),
            }
            for item in resources
            if isinstance(item, dict) and item.get("id")
        ][:200]
        results: list[dict[str, Any]] = []
        authorized = True
        errors: list[str] = []
        for resource in resource_records:
            resource_id = resource["resource_id"]
            query = AzureQuery(
                source="azure.monitor.diagnostic_settings",
                method="GET",
                url=(
                    f"https://management.azure.com{resource_id}/providers/"
                    "Microsoft.Insights/diagnosticSettings"
                ),
                api_version="2021-05-01-preview",
            )
            try:
                status, body = await self.client.request(query)
            except (httpx.HTTPError, TimeoutError) as exc:
                errors.append(type(exc).__name__)
                continue
            if status in {401, 403}:
                authorized = False
            if 200 <= status < 300:
                settings = body.get("value", []) if isinstance(body, dict) else []
                results.append(
                    {
                        **resource,
                        "applicability": "APPLICABLE",
                        "settings": settings,
                    }
                )
            elif status == 404 and self._azure_error_code(body) == "resourcetypenotsupported":
                results.append(
                    {
                        **resource,
                        "applicability": "NOT_APPLICABLE",
                        "reason_code": "RESOURCE_TYPE_NOT_SUPPORTED",
                        "settings": [],
                    }
                )
            else:
                results.append(
                    {
                        **resource,
                        "applicability": "UNKNOWN",
                        "reason_code": f"HTTP_{status}",
                        "settings": [],
                    }
                )
                errors.append(f"HTTP_{status}")
        return envelope(
            request=request,
            source="azure.monitor.diagnostic_settings",
            collector_version=self.version,
            query={"resource_ids_sha256_input_count": len(resource_records)},
            raw_payload={
                "resources": results,
                "queried_count": len(resource_records),
                "applicable_count": sum(
                    item["applicability"] == "APPLICABLE" for item in results
                ),
                "not_applicable_count": sum(
                    item["applicability"] == "NOT_APPLICABLE" for item in results
                ),
            },
            authorized=authorized,
            collection_error=(
                f"diagnostic collection failures: {sorted(set(errors))}" if errors else None
            ),
        )

    @staticmethod
    def _azure_error_code(body: Any) -> str:
        if not isinstance(body, dict):
            return ""
        error = body.get("error")
        if not isinstance(error, dict):
            return ""
        return str(error.get("code", "")).replace("_", "").casefold()

    async def _collect_authorization_tests(
        self,
        request: CollectionRequest,
    ) -> CollectedEvidence:
        """Probe one read-only API route without auth and with the collector's wrong role."""

        endpoint = self.authorization_probe_endpoint
        scope = self.authorization_probe_scope
        if endpoint is None or scope is None:
            raise RuntimeError("authorization probe is not configured")
        payload: dict[str, Any] = {
            "probe_method": "GET",
            "unauthenticated_status": None,
            "wrong_role_status": None,
        }
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            try:
                unauthenticated = await client.get(endpoint)
                payload["unauthenticated_status"] = unauthenticated.status_code
            except (httpx.HTTPError, TimeoutError) as exc:
                errors.append(f"unauthenticated:{type(exc).__name__}")
            try:
                token = await self.client.get_token(scope)
                wrong_role = await client.get(
                    endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                )
                payload["wrong_role_status"] = wrong_role.status_code
            except (httpx.HTTPError, TimeoutError) as exc:
                errors.append(f"wrong_role:{type(exc).__name__}")
            except Exception as exc:  # Azure Identity has a broad credential exception hierarchy.
                errors.append(f"wrong_role_token:{type(exc).__name__}")
        return envelope(
            request=request,
            source="application.authorization_tests",
            collector_version=self.version,
            query={"method": "GET", "endpoint": endpoint, "token_scope": scope},
            raw_payload=payload,
            authorized=True,
            collection_error=(
                f"authorization probe failures: {sorted(set(errors))}" if errors else None
            ),
        )

    async def collect(self, request: CollectionRequest) -> list[CollectedEvidence]:
        output: list[CollectedEvidence] = []
        resource_graph_body: Any = {}
        try:
            for query in self.queries(request):
                query_metadata = {
                    "method": query.method,
                    "url": query.url,
                    "api_version": query.api_version,
                    "params": query.params,
                    "body": query.body,
                }
                try:
                    status, body = await self.client.request(query)
                    if query.source == "azure.resource_graph.inventory" and 200 <= status < 300:
                        resource_graph_body = body
                    normalized = (
                        self._normalize_log_query(body)
                        if query.token_scope == LOG_SCOPE and 200 <= status < 300
                        else body
                    )
                    authorized = status not in {401, 403}
                    error = None if 200 <= status < 300 else f"Azure REST returned HTTP {status}"
                    output.append(
                        envelope(
                            request=request,
                            source=query.source,
                            collector_version=self.version,
                            query=query_metadata,
                            raw_payload=body,
                            normalized_payload=normalized,
                            authorized=authorized,
                            collection_error=error,
                        )
                    )
                except (httpx.HTTPError, TimeoutError) as exc:
                    output.append(
                        envelope(
                            request=request,
                            source=query.source,
                            collector_version=self.version,
                            query=query_metadata,
                            raw_payload={"error_type": type(exc).__name__},
                            authorized=True,
                            collection_error=f"collector transport failure: {type(exc).__name__}",
                        )
                    )
            output.append(await self._collect_diagnostic_settings(request, resource_graph_body))
            if self.authorization_probe_endpoint is not None:
                output.append(await self._collect_authorization_tests(request))
            return output
        finally:
            await self.client.close()
