"""Delete only expired, explicitly tagged synthetic fixture resources."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from azure.core.credentials import AccessToken
from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential

ARM_SCOPE = "https://management.azure.com/.default"
ARM_ENDPOINT = "https://management.azure.com"
RESOURCE_API_VERSION = "2021-04-01"


class FixtureCleanupError(RuntimeError):
    """Raised when inventory or deletion crosses a fixture safety boundary."""


@dataclass(frozen=True)
class FixtureResource:
    resource_id: str
    resource_type: str
    expires_on: datetime


def _parse_tag_requirements(values: Sequence[str]) -> dict[str, str]:
    requirements: dict[str, str] = {}
    for value in values:
        key, separator, expected = value.partition("=")
        if not separator or not key or not expected:
            raise FixtureCleanupError(f"invalid required tag {value!r}; expected key=value")
        requirements[key] = expected
    return requirements


def _parse_expiry(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FixtureCleanupError("fixture expiresOn tag is not valid RFC3339") from exc
    if parsed.tzinfo is None:
        raise FixtureCleanupError("fixture expiresOn tag must include a timezone")
    return parsed.astimezone(UTC)


def select_expired_resources(
    resources: Sequence[Mapping[str, Any]],
    *,
    subscription_id: str,
    resource_group: str,
    required_tags: Sequence[str],
    now: datetime | None = None,
) -> tuple[FixtureResource, ...]:
    """Return a deletion allowlist; untagged resources are ignored, never inferred."""

    requirements = {
        "fixture": "true",
        "dataClassification": "synthetic",
        **_parse_tag_requirements(required_tags),
    }
    expected_prefix = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/providers/".casefold()
    )
    current = (now or datetime.now(UTC)).astimezone(UTC)
    selected: list[FixtureResource] = []
    for resource in resources:
        resource_id = str(resource.get("id", ""))
        resource_type = str(resource.get("type", ""))
        tags = resource.get("tags") or {}
        if not isinstance(tags, Mapping):
            continue
        if str(tags.get("fixture", "")).casefold() != "true":
            continue
        if not resource_id.casefold().startswith(expected_prefix):
            raise FixtureCleanupError("fixture inventory crossed the approved Azure scope")
        if not resource_type or "/" not in resource_type:
            raise FixtureCleanupError("fixture inventory contains an invalid resource type")
        for key, expected in requirements.items():
            if str(tags.get(key, "")) != expected:
                raise FixtureCleanupError(f"fixture resource lacks required tag {key}={expected}")
        expiry = _parse_expiry(str(tags.get("expiresOn", "")))
        if expiry <= current:
            selected.append(FixtureResource(resource_id, resource_type, expiry))
    return tuple(sorted(selected, key=lambda item: item.resource_id))


class AzureFixtureJanitor:
    """Minimal ARM client with a tag-derived allowlist and post-delete verification."""

    def __init__(
        self,
        subscription_id: str,
        resource_group: str,
        *,
        managed_identity_client_id: str | None,
        required_tags: Sequence[str],
    ):
        self.subscription_id = subscription_id
        self.resource_group = resource_group
        self.required_tags = tuple(required_tags)
        self.credential = (
            ManagedIdentityCredential(client_id=managed_identity_client_id)
            if managed_identity_client_id
            else DefaultAzureCredential()
        )

    async def _token(self) -> AccessToken:
        return await self.credential.get_token(ARM_SCOPE)

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        token = await self._token()
        headers = {"Authorization": f"Bearer {token.token}"}
        headers.update(kwargs.pop("headers", {}))
        response = await client.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def _inventory_url(self) -> str:
        return (
            f"{ARM_ENDPOINT}/subscriptions/{self.subscription_id}/resourceGroups/"
            f"{self.resource_group}/resources?api-version={RESOURCE_API_VERSION}"
        )

    async def _inventory(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        response = await self._request(client, "GET", self._inventory_url())
        payload = response.json()
        resources = list(payload.get("value", []))
        next_link = payload.get("nextLink")
        while next_link:
            response = await self._request(client, "GET", str(next_link))
            payload = response.json()
            resources.extend(payload.get("value", []))
            next_link = payload.get("nextLink")
        return resources

    async def _api_version(self, client: httpx.AsyncClient, resource_type: str) -> str:
        namespace, type_path = resource_type.split("/", 1)
        response = await self._request(
            client,
            "GET",
            f"{ARM_ENDPOINT}/subscriptions/{self.subscription_id}/providers/{namespace}",
            params={"api-version": RESOURCE_API_VERSION},
        )
        candidates: list[str] = []
        for item in response.json().get("resourceTypes", []):
            if str(item.get("resourceType", "")).casefold() == type_path.casefold():
                candidates = [str(version) for version in item.get("apiVersions", [])]
                break
        stable = [version for version in candidates if "preview" not in version.casefold()]
        if not stable:
            raise FixtureCleanupError(f"no stable ARM API version for {resource_type}")
        return stable[0]

    async def _delete(self, client: httpx.AsyncClient, resource: FixtureResource) -> None:
        api_version = await self._api_version(client, resource.resource_type)
        response = await self._request(
            client,
            "DELETE",
            f"{ARM_ENDPOINT}{resource.resource_id}",
            params={"api-version": api_version},
        )
        operation = response.headers.get("azure-asyncoperation") or response.headers.get("location")
        if not operation:
            return
        for _ in range(60):
            poll = await self._request(client, "GET", operation)
            status = str(poll.json().get("status", "Succeeded")).casefold()
            if status == "succeeded":
                return
            if status in {"failed", "canceled", "cancelled"}:
                raise FixtureCleanupError(f"ARM deletion ended with status {status}")
            await asyncio.sleep(2)
        raise FixtureCleanupError("ARM deletion did not complete within 120 seconds")

    async def cleanup(self) -> dict[str, Any]:
        limits = httpx.Limits(max_connections=4, max_keepalive_connections=2)
        async with self.credential, httpx.AsyncClient(timeout=30, limits=limits) as client:
            inventory = await self._inventory(client)
            selected = select_expired_resources(
                inventory,
                subscription_id=self.subscription_id,
                resource_group=self.resource_group,
                required_tags=self.required_tags,
            )
            for resource in selected:
                await self._delete(client, resource)

            remaining_ids = {
                str(item.get("id", "")).casefold() for item in await self._inventory(client)
            }
            not_deleted = [
                item.resource_id
                for item in selected
                if item.resource_id.casefold() in remaining_ids
            ]
            if not_deleted:
                raise FixtureCleanupError(
                    f"{len(not_deleted)} expired fixture resource(s) remain after cleanup"
                )
            return {
                "deleted_count": len(selected),
                "resource_types": sorted({item.resource_type for item in selected}),
                "resource_group_deleted": False,
            }
