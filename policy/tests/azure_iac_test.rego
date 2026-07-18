package aica.azure

import rego.v1

test_compliant_storage_has_no_denies if {
  test_input := {
    "resources": [
      {
        "type": "Microsoft.Storage/storageAccounts",
        "name": "safe",
        "properties": {
          "allowBlobPublicAccess": false,
          "allowSharedKeyAccess": false,
          "supportsHttpsTrafficOnly": true,
          "minimumTlsVersion": "TLS1_2",
          "publicNetworkAccess": "Enabled",
        },
      },
    ],
  }
  results := deny with input as test_input
  count(results) == 0
}

test_public_storage_is_denied if {
  test_input := {
    "resources": [
      {
        "type": "Microsoft.Storage/storageAccounts",
        "name": "unsafe",
        "properties": {
          "allowBlobPublicAccess": true,
          "allowSharedKeyAccess": false,
          "supportsHttpsTrafficOnly": true,
          "minimumTlsVersion": "TLS1_2",
        },
      },
    ],
  }
  results := deny with input as test_input
  some message in results
  contains(message, "permits blob public access")
}

test_floating_container_image_is_denied if {
  test_input := {
    "resources": [
      {
        "type": "Microsoft.App/containerApps",
        "name": "floating",
        "properties": {
          "template": {
            "containers": [{"image": "ghcr.io/example/aica:latest"}],
            "scale": {"minReplicas": 0, "maxReplicas": 2},
          },
        },
      },
    ],
  }
  results := deny with input as test_input
  some message in results
  contains(message, "not pinned by digest")
}

test_floating_job_image_is_denied if {
  test_input := {
    "resources": [
      {
        "type": "Microsoft.App/jobs",
        "name": "floating-job",
        "properties": {
          "template": {
            "containers": [{"image": "ghcr.io/example/aica-job:latest"}],
          },
        },
      },
    ],
  }
  results := deny with input as test_input
  some message in results
  contains(message, "job image that is not pinned by digest")
}

test_long_running_job_is_denied if {
  test_input := {
    "resources": [
      {
        "type": "Microsoft.App/jobs",
        "name": "expensive-job",
        "properties": {
          "configuration": {"replicaTimeout": 1800},
          "template": {
            "containers": [{"image": "ghcr.io/example/aica-job@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],
          },
        },
      },
    ],
  }
  results := deny with input as test_input
  some message in results
  contains(message, "scheduled-job cost ceiling")
}

test_overprivileged_command_worker_role_is_denied if {
  test_input := {
    "resources": [
      {
        "type": "Microsoft.Authorization/roleDefinitions",
        "name": "unsafe-worker-role",
        "properties": {
          "roleName": "AICA Assessment Job Starter",
          "permissions": [{"actions": ["Microsoft.App/jobs/*"]}],
        },
      },
    ],
  }
  results := deny with input as test_input
  some message in results
  contains(message, "only assessment-job read/execution-status/start actions")
}

test_exact_command_worker_role_is_allowed if {
  test_input := {
    "resources": [
      {
        "type": "Microsoft.Authorization/roleDefinitions",
        "name": "safe-worker-role",
        "properties": {
          "roleName": "AICA Assessment Job Starter",
          "permissions": [{"actions": [
            "Microsoft.App/jobs/read",
            "Microsoft.App/jobs/execution/read",
            "Microsoft.App/jobs/start/action",
          ]}],
        },
      },
    ],
  }
  results := deny with input as test_input
  count(results) == 0
}

test_inline_container_app_secret_is_denied if {
  test_input := {
    "resources": [
      {
        "type": "Microsoft.App/containerApps",
        "name": "inline-secret",
        "properties": {
          "configuration": {"secrets": [{"name": "token", "value": "not-allowed"}]},
          "template": {
            "containers": [{"image": "ghcr.io/example/aica@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],
            "scale": {"minReplicas": 0, "maxReplicas": 2},
          },
        },
      },
    ],
  }
  results := deny with input as test_input
  some message in results
  contains(message, "embeds a Container Apps secret")
}

test_fixture_missing_tags_is_denied if {
  test_input := {
    "resources": [
      {
        "type": "Microsoft.ManagedIdentity/userAssignedIdentities",
        "name": "fixture",
        "tags": {"fixture": "true", "scenarioId": "identity"},
        "properties": {},
      },
    ],
  }
  results := deny with input as test_input
  some message in results
  contains(message, "fixture tags are missing")
}
