from datetime import UTC, datetime, timedelta

import pytest

from aica.fixtures.cleanup import FixtureCleanupError, select_expired_resources

SUBSCRIPTION = "00000000-0000-4000-8000-000000000001"
GROUP = "rg-aica-fixture-eus2"


def _resource(*, expired: bool = True, fixture: str = "true") -> dict[str, object]:
    expiry = datetime.now(UTC) + (timedelta(hours=-1) if expired else timedelta(hours=1))
    return {
        "id": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{GROUP}/providers/"
            "Microsoft.Storage/storageAccounts/stfixture"
        ),
        "type": "Microsoft.Storage/storageAccounts",
        "tags": {
            "fixture": fixture,
            "managedBy": "bicep",
            "dataClassification": "synthetic",
            "expiresOn": expiry.isoformat(),
        },
    }


def test_selects_only_expired_tagged_fixture_resources() -> None:
    resources = [_resource(), _resource(expired=False), _resource(fixture="false")]
    selected = select_expired_resources(
        resources,
        subscription_id=SUBSCRIPTION,
        resource_group=GROUP,
        required_tags=["managedBy=bicep", "dataClassification=synthetic"],
    )
    assert len(selected) == 1


def test_rejects_fixture_resource_outside_approved_scope() -> None:
    resource = _resource()
    resource["id"] = str(resource["id"]).replace(GROUP, "rg-other")
    with pytest.raises(FixtureCleanupError, match="crossed"):
        select_expired_resources(
            [resource],
            subscription_id=SUBSCRIPTION,
            resource_group=GROUP,
            required_tags=["managedBy=bicep"],
        )


def test_rejects_missing_required_tag() -> None:
    with pytest.raises(FixtureCleanupError, match="managedBy"):
        select_expired_resources(
            [_resource()],
            subscription_id=SUBSCRIPTION,
            resource_group=GROUP,
            required_tags=["managedBy=terraform"],
        )
