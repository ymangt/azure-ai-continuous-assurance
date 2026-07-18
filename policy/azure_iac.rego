package aica.azure

import rego.v1

resources := [resource |
  some _, resource in walk(input)
  is_object(resource)
  object.get(resource, "type", "") != ""
]

properties(resource) := object.get(resource, "properties", {})
tags(resource) := object.get(resource, "tags", {})
resource_type(resource) := lower(object.get(resource, "type", ""))

valid_image_reference(image) if {
  contains(image, "@sha256:")
}

# Compiled parameterized templates are accepted here; preflight.sh validates concrete values.
valid_image_reference(image) if {
  regex.match(`^\[parameters\('[A-Za-z][A-Za-z0-9]*Image'\)\]$`, image)
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.storage/storageaccounts"
  object.get(properties(resource), "allowBlobPublicAccess", true) != false
  message := sprintf("%s permits blob public access", [object.get(resource, "name", "unnamed-storage")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.storage/storageaccounts"
  object.get(properties(resource), "allowSharedKeyAccess", true) != false
  message := sprintf("%s permits Shared Key authentication", [object.get(resource, "name", "unnamed-storage")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.storage/storageaccounts"
  object.get(properties(resource), "supportsHttpsTrafficOnly", false) != true
  message := sprintf("%s does not require HTTPS", [object.get(resource, "name", "unnamed-storage")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.storage/storageaccounts"
  object.get(properties(resource), "minimumTlsVersion", "") != "TLS1_2"
  message := sprintf("%s does not require TLS 1.2", [object.get(resource, "name", "unnamed-storage")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.storage/storageaccounts/blobservices"
  object.get(properties(resource), "isVersioningEnabled", false) != true
  message := sprintf("%s does not enable Blob versioning", [object.get(resource, "name", "unnamed-blob-service")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.storage/storageaccounts/blobservices"
  retention := object.get(properties(resource), "deleteRetentionPolicy", {})
  object.get(retention, "enabled", false) != true
  message := sprintf("%s does not enable Blob soft delete", [object.get(resource, "name", "unnamed-blob-service")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.storage/storageaccounts/blobservices/containers"
  object.get(properties(resource), "publicAccess", "None") != "None"
  message := sprintf("%s has anonymous container access", [object.get(resource, "name", "unnamed-container")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.keyvault/vaults"
  object.get(properties(resource), "enableRbacAuthorization", false) != true
  message := sprintf("%s does not use Key Vault RBAC authorization", [object.get(resource, "name", "unnamed-vault")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.keyvault/vaults"
  object.get(properties(resource), "enablePurgeProtection", false) != true
  message := sprintf("%s does not enable purge protection", [object.get(resource, "name", "unnamed-vault")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.cognitiveservices/accounts"
  object.get(properties(resource), "disableLocalAuth", false) != true
  message := sprintf("%s permits Foundry local/API-key authentication", [object.get(resource, "name", "unnamed-foundry")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.app/containerapps"
  scale := object.get(object.get(properties(resource), "template", {}), "scale", {})
  object.get(scale, "minReplicas", -1) != 0
  message := sprintf("%s does not scale to zero", [object.get(resource, "name", "unnamed-container-app")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.app/containerapps"
  scale := object.get(object.get(properties(resource), "template", {}), "scale", {})
  object.get(scale, "maxReplicas", 999) > 2
  message := sprintf("%s exceeds the two-replica cost ceiling", [object.get(resource, "name", "unnamed-container-app")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.app/containerapps"
  some container in object.get(object.get(properties(resource), "template", {}), "containers", [])
  image := object.get(container, "image", "")
  not valid_image_reference(image)
  message := sprintf("%s uses an image that is not pinned by digest: %s", [object.get(resource, "name", "unnamed-container-app"), image])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.app/jobs"
  some container in object.get(object.get(properties(resource), "template", {}), "containers", [])
  image := object.get(container, "image", "")
  not valid_image_reference(image)
  message := sprintf("%s uses a job image that is not pinned by digest: %s", [object.get(resource, "name", "unnamed-container-job"), image])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.app/jobs"
  timeout := object.get(properties(resource), "configuration", {}).replicaTimeout
  timeout > 900
  message := sprintf("%s exceeds the 900-second scheduled-job cost ceiling", [object.get(resource, "name", "unnamed-container-job")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.app/containerapps"
  some secret in object.get(object.get(properties(resource), "configuration", {}), "secrets", [])
  object.get(secret, "value", "") != ""
  message := sprintf("%s embeds a Container Apps secret instead of using a Key Vault identity reference", [object.get(resource, "name", "unnamed-container-app")])
}

deny contains message if {
  some resource in resources
  object.get(tags(resource), "fixture", "false") == "true"
  required := {"expiresOn", "scenarioId", "owner", "dataClassification"}
  missing := {key | some key in required; object.get(tags(resource), key, "") == ""}
  count(missing) > 0
  message := sprintf("%s fixture tags are missing: %v", [object.get(resource, "name", "unnamed-fixture"), missing])
}

deny contains message if {
  some resource in resources
  object.get(tags(resource), "fixture", "false") == "true"
  object.get(tags(resource), "dataClassification", "") != "synthetic"
  message := sprintf("%s fixture is not classified synthetic", [object.get(resource, "name", "unnamed-fixture")])
}

deny contains message if {
  some resource in resources
  object.get(tags(resource), "fixture", "false") == "true"
  resource_type(resource) in {"microsoft.compute/virtualmachines", "microsoft.network/publicipaddresses"}
  message := sprintf("%s is a prohibited deployable fixture type", [object.get(resource, "name", "unnamed-fixture")])
}

forbidden_role_ids := {
  "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
  "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9",
}

expected_command_worker_actions := {
  "microsoft.app/jobs/read",
  "microsoft.app/jobs/execution/read",
  "microsoft.app/jobs/start/action",
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.authorization/roledefinitions"
  lower(object.get(properties(resource), "roleName", "")) == "aica assessment job starter"
  actual_actions := {lower(action) |
    some permission in object.get(properties(resource), "permissions", [])
    some action in object.get(permission, "actions", [])
  }
  actual_actions != expected_command_worker_actions
  message := sprintf("%s must contain only assessment-job read/execution-status/start actions", [object.get(resource, "name", "unnamed-role-definition")])
}

deny contains message if {
  some resource in resources
  resource_type(resource) == "microsoft.authorization/roleassignments"
  role_parts := split(object.get(properties(resource), "roleDefinitionId", ""), "/")
  role_id := lower(role_parts[count(role_parts) - 1])
  role_id in forbidden_role_ids
  message := sprintf("%s grants Owner or User Access Administrator, which is prohibited", [object.get(resource, "name", "unnamed-role-assignment")])
}

warn contains message if {
  some resource in resources
  resource_type(resource) in {
    "microsoft.storage/storageaccounts",
    "microsoft.keyvault/vaults",
    "microsoft.cognitiveservices/accounts",
  }
  object.get(properties(resource), "publicNetworkAccess", "Enabled") == "Enabled"
  message := sprintf("%s uses an accepted public-service-endpoint residual risk", [object.get(resource, "name", "unnamed-resource")])
}
