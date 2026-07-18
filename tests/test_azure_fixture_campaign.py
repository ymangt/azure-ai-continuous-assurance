from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from aica.collectors.azure import AzureEvidenceCollector, AzureQuery
from aica.collectors.base import CollectionRequest
from aica.config import Settings
from aica.domain.models import ResultStatus
from aica.evaluation.engine import RuleEngine, default_rules
from aica.pipeline import AssessmentPipeline
from aica.profiles import AssessmentProfile, load_profile

SUBSCRIPTION_ID = "00000000-0000-4000-8000-000000000000"
FIXTURE_GROUP = "rg-aica-fixture-eus2"
FIXTURE_SCOPE = f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/{FIXTURE_GROUP}"
READER_ROLE_ID = "acdd72a7-3385-48ef-bd42-f606fba81ae7"
STORAGE_BLOB_DATA_OWNER_ROLE_ID = "b7e6dc6d-f1e8-4753-8033-0f276bb0955b"


class CampaignAzureClient:
    """Small ARM transcript for the two deployable fixture campaigns."""

    def __init__(self, active_scenario: str | None):
        self.active_scenario = active_scenario
        self.requests: list[AzureQuery] = []

    @property
    def control_storage_id(self) -> str:
        return (
            f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-aica-control-cc/"
            "providers/Microsoft.Storage/storageAccounts/staicacontrol"
        )

    @property
    def fixture_storage_id(self) -> str:
        return (
            f"{FIXTURE_SCOPE}/providers/Microsoft.Storage/storageAccounts/staicafixture"
        )

    @property
    def fixture_identity_id(self) -> str:
        return (
            f"{FIXTURE_SCOPE}/providers/Microsoft.ManagedIdentity/"
            "userAssignedIdentities/id-aica-fixture-excessive"
        )

    @staticmethod
    def _diagnostic_setting() -> dict[str, Any]:
        return {
            "name": "send-audit-to-operations",
            "properties": {
                "workspaceId": (
                    f"/subscriptions/{SUBSCRIPTION_ID}/resourceGroups/rg-aica-control-cc/"
                    "providers/Microsoft.OperationalInsights/workspaces/law-aica"
                ),
                "logs": [{"categoryGroup": "audit", "enabled": True}],
            },
        }

    async def request(self, query: AzureQuery) -> tuple[int, Any]:
        self.requests.append(query)
        if query.source == "azure.resource_graph.inventory":
            resources: list[dict[str, str]] = [
                {"id": self.control_storage_id, "type": "microsoft.storage/storageaccounts"}
            ]
            if self.active_scenario == "missing-diagnostic-settings":
                resources.append(
                    {"id": self.fixture_storage_id, "type": "microsoft.storage/storageaccounts"}
                )
            elif self.active_scenario == "excessive-managed-identity-privilege":
                resources.append(
                    {
                        "id": self.fixture_identity_id,
                        "type": "microsoft.managedidentity/userassignedidentities",
                    }
                )
            return 200, {"data": resources}

        if query.source.startswith("azure.rbac.assignments"):
            roles = [READER_ROLE_ID]
            if (
                self.active_scenario == "excessive-managed-identity-privilege"
                and FIXTURE_SCOPE.casefold() in query.url.casefold()
            ):
                roles.append(STORAGE_BLOB_DATA_OWNER_ROLE_ID)
            return 200, {
                "value": [
                    {
                        "properties": {
                            "roleDefinitionId": (
                                f"/subscriptions/{SUBSCRIPTION_ID}/providers/"
                                f"Microsoft.Authorization/roleDefinitions/{role_id}"
                            )
                        }
                    }
                    for role_id in roles
                ]
            }

        if query.source == "azure.monitor.diagnostic_settings":
            if self.fixture_identity_id.casefold() in query.url.casefold():
                return 404, {"error": {"code": "ResourceTypeNotSupported"}}
            if (
                self.active_scenario == "missing-diagnostic-settings"
                and self.fixture_storage_id.casefold() in query.url.casefold()
            ):
                return 200, {"value": []}
            return 200, {"value": [self._diagnostic_setting()]}

        return 200, {"value": []}

    async def close(self) -> None:
        return None


class ProbeAzureClient:
    def __init__(self) -> None:
        self.token_scopes: list[str] = []

    async def get_token(self, scope: str) -> str:
        self.token_scopes.append(scope)
        return "wrong-role-token"

    async def close(self) -> None:
        return None


def _rule_engine(rule_id: str) -> RuleEngine:
    rule = next(rule for rule in default_rules() if rule.id == rule_id)
    return RuleEngine((rule,))


def test_production_azure_dev_requires_authorization_probe_configuration(
    tmp_path: Path,
) -> None:
    profile = AssessmentProfile(
        name="azure-dev",
        description="Production collector contract",
        trigger="manual",
        scope=(FIXTURE_SCOPE,),
        collectors=("azure",),
        objective_path=tmp_path / "objectives.json",
    )
    settings = Settings(env="production", azure_subscription_id=SUBSCRIPTION_ID)

    with pytest.raises(ValueError, match="AUTHORIZATION_PROBE_ENDPOINT"):
        AssessmentPipeline(settings)._collectors(profile)


async def _collect_phase(
    tmp_path: Path,
    profile: AssessmentProfile,
    *,
    phase: str,
    active_scenario: str | None,
) -> tuple[list[Any], CampaignAzureClient]:
    client = CampaignAzureClient(active_scenario)
    now = datetime.now(UTC)
    request = CollectionRequest(
        run_id=f"run-{phase}",
        observation_window_start=now - timedelta(hours=1),
        observation_window_end=now,
        scope=profile.scope,
        output_dir=tmp_path / phase,
    )
    collected = await AzureEvidenceCollector(
        client, subscription_id=SUBSCRIPTION_ID
    ).collect(request)
    return [item.item for item in collected], client


@pytest.mark.parametrize(
    ("scenario", "rule_id"),
    [
        ("excessive-managed-identity-privilege", "R-AC-6-01"),
        ("missing-diagnostic-settings", "R-AU-2-01"),
    ],
)
@pytest.mark.asyncio
async def test_scoped_fixture_campaign_fails_then_passes_after_cleanup_and_retest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    rule_id: str,
) -> None:
    monkeypatch.setenv("AZURE_SUBSCRIPTION_ID", SUBSCRIPTION_ID)
    profile = load_profile("azure-dev")
    assert FIXTURE_SCOPE in profile.scope

    statuses: dict[str, ResultStatus] = {}
    for phase, active_scenario in (
        ("baseline", None),
        ("fixture", scenario),
        ("cleanup", None),
        ("retest", None),
    ):
        evidence, client = await _collect_phase(
            tmp_path,
            profile,
            phase=phase,
            active_scenario=active_scenario,
        )
        statuses[phase] = _rule_engine(rule_id).evaluate(f"run-{phase}", evidence)[0].status

        resource_graph = next(
            request for request in client.requests if request.source == "azure.resource_graph.inventory"
        )
        assert resource_graph.body is not None
        assert FIXTURE_SCOPE in str(resource_graph.body["query"])
        assert any(
            request.source.startswith("azure.rbac.assignments")
            and FIXTURE_SCOPE.casefold() in request.url.casefold()
            for request in client.requests
        )

    assert statuses == {
        "baseline": ResultStatus.PASS,
        "fixture": ResultStatus.FAIL,
        "cleanup": ResultStatus.PASS,
        "retest": ResultStatus.PASS,
    }


@respx.mock
@pytest.mark.asyncio
async def test_live_authorization_probe_records_only_denial_statuses(tmp_path: Path) -> None:
    endpoint = "https://console.example.test/api/v1/system"
    scope = "api://00000000-0000-4000-8000-000000000123/.default"
    private_response = "response-content-must-not-be-evidence"

    def deny(request: httpx.Request) -> httpx.Response:
        status = 403 if request.headers.get("Authorization") else 401
        return httpx.Response(status, json={"detail": private_response})

    respx.get(endpoint).mock(side_effect=deny)
    client = ProbeAzureClient()
    now = datetime.now(UTC)
    request = CollectionRequest(
        run_id="run-authz",
        observation_window_start=now - timedelta(hours=1),
        observation_window_end=now,
        scope=(FIXTURE_SCOPE,),
        output_dir=tmp_path,
    )
    collector = AzureEvidenceCollector(
        client,  # type: ignore[arg-type]
        subscription_id=SUBSCRIPTION_ID,
        authorization_probe_endpoint=endpoint,
        authorization_probe_scope=scope,
    )

    collected = await collector._collect_authorization_tests(request)

    assert collected.item.source == "application.authorization_tests"
    assert collected.item.payload == {
        "probe_method": "GET",
        "unauthenticated_status": 401,
        "wrong_role_status": 403,
    }
    assert collected.item.collection_error is None
    assert client.token_scopes == [scope]
    serialized = collected.model_dump_json()
    assert private_response not in serialized
    assert "wrong-role-token" not in serialized


@respx.mock
@pytest.mark.asyncio
async def test_live_authorization_probe_fails_control_when_wrong_role_is_allowed(
    tmp_path: Path,
) -> None:
    endpoint = "https://console.example.test/api/v1/system"

    def permissive(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200 if request.headers.get("Authorization") else 401)

    respx.get(endpoint).mock(side_effect=permissive)
    now = datetime.now(UTC)
    request = CollectionRequest(
        run_id="run-authz",
        observation_window_start=now - timedelta(hours=1),
        observation_window_end=now,
        scope=(FIXTURE_SCOPE,),
        output_dir=tmp_path,
    )
    collector = AzureEvidenceCollector(
        ProbeAzureClient(),  # type: ignore[arg-type]
        subscription_id=SUBSCRIPTION_ID,
        authorization_probe_endpoint=endpoint,
        authorization_probe_scope="api://assurance/.default",
    )

    collected = await collector._collect_authorization_tests(request)
    result = _rule_engine("R-AC-3-01").evaluate("run-authz", [collected.item])[0]

    assert collected.item.collection_error is None
    assert result.status == ResultStatus.FAIL


@pytest.mark.asyncio
async def test_diagnostic_unsupported_resource_is_explicitly_not_applicable(
    tmp_path: Path,
) -> None:
    profile = AssessmentProfile(
        name="diagnostic-applicability",
        description="Exercise explicit applicability",
        trigger="fixture",
        scope=(FIXTURE_SCOPE,),
        collectors=("azure",),
        objective_path=tmp_path / "objectives.json",
    )
    evidence, _ = await _collect_phase(
        tmp_path,
        profile,
        phase="unsupported",
        active_scenario="excessive-managed-identity-privilege",
    )
    diagnostic = next(
        item for item in evidence if item.source == "azure.monitor.diagnostic_settings"
    )

    resources = diagnostic.payload["resources"]
    unsupported = next(item for item in resources if item["applicability"] == "NOT_APPLICABLE")
    assert unsupported["applicability"] == "NOT_APPLICABLE"
    assert unsupported["reason_code"] == "RESOURCE_TYPE_NOT_SUPPORTED"
    assert _rule_engine("R-AU-2-01").evaluate("run-unsupported", evidence)[0].status == ResultStatus.PASS
