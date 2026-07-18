targetScope = 'resourceGroup'

param location string
param suffix string
param scenarioId string
param expiresOn string
param owner string
param tags object
param operationsWorkspaceId string

var fixtureActive = !empty(scenarioId)
var fixtureTags = union(tags, {
  expiresOn: empty(expiresOn) ? 'not-active' : expiresOn
  scenarioId: empty(scenarioId) ? 'none' : scenarioId
  owner: owner
  dataClassification: 'synthetic'
  fixture: 'true'
})

// This account is always private. The public-storage scenario exists only in policy/fixtures.
resource fixtureStorage 'Microsoft.Storage/storageAccounts@2025-06-01' = if (fixtureActive) {
  name: 'staicafix${take(suffix, 10)}'
  location: location
  tags: fixtureTags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowCrossTenantReplication: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    dnsEndpointType: 'Standard'
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: 'Enabled'
    supportsHttpsTrafficOnly: true
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

// Keep both deployable fixtures compliant with the storage baseline. The
// missing-diagnostics scenario is then defined by one omitted diagnostic
// setting, rather than accidentally combining recoverability and logging gaps.
resource fixtureBlobService 'Microsoft.Storage/storageAccounts/blobServices@2025-06-01' = if (fixtureActive) {
  parent: fixtureStorage
  name: 'default'
  properties: {
    automaticSnapshotPolicyEnabled: true
    changeFeed: {
      enabled: true
      retentionInDays: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    deleteRetentionPolicy: {
      allowPermanentDelete: false
      enabled: true
      days: 7
    }
    isVersioningEnabled: true
    restorePolicy: {
      enabled: false
    }
  }
}

resource fixtureDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (scenarioId == 'excessive-managed-identity-privilege') {
  scope: fixtureBlobService
  name: 'send-fixture-audit-to-operations'
  properties: {
    workspaceId: operationsWorkspaceId
    logs: [
      {
        categoryGroup: 'audit'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

resource fixtureAccountMetrics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (scenarioId == 'excessive-managed-identity-privilege') {
  scope: fixtureStorage
  name: 'send-fixture-account-metrics-to-operations'
  properties: {
    workspaceId: operationsWorkspaceId
    logs: []
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

// Deliberately has no credential, federated trust, application assignment, or workload attachment.
resource excessivePrivilegeIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = if (scenarioId == 'excessive-managed-identity-privilege') {
  name: 'id-aica-fixture-excessive'
  location: location
  tags: fixtureTags
}

resource excessiveBlobRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (scenarioId == 'excessive-managed-identity-privilege') {
  scope: fixtureStorage
  name: guid(fixtureStorage.id, excessivePrivilegeIdentity!.id, 'fixture-excessive-blob-owner')
  properties: {
    principalId: excessivePrivilegeIdentity!.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b')
  }
}

output active bool = fixtureActive
output scenarioId string = scenarioId
output fixtureStorageId string = fixtureActive ? fixtureStorage!.id : ''
output excessiveIdentityPrincipalId string = scenarioId == 'excessive-managed-identity-privilege' ? excessivePrivilegeIdentity!.properties.principalId : ''
