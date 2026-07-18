targetScope = 'resourceGroup'

param location string
param staticWebAppLocation string
param environment string
param suffix string
param tags object
param githubRepository string
param enableWorkloads bool
param tenantId string
@secure()
param pseudonymizationSecret string
@secure()
param githubAppPrivateKey string

var storageName = 'staica${suffix}'
var keyVaultName = 'kv-aica-${take(suffix, 8)}'
var workspaceName = 'law-aica-ops-${environment}'
var appInsightsName = 'appi-aica-${environment}'
var environmentName = 'cae-aica-control-${environment}'
var staticWebAppName = 'stapp-aica-${environment}-${take(suffix, 5)}'

resource storage 'Microsoft.Storage/storageAccounts@2025-06-01' = {
  name: storageName
  location: location
  tags: tags
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

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-06-01' = {
  parent: storage
  name: 'default'
  properties: {
    automaticSnapshotPolicyEnabled: true
    changeFeed: {
      enabled: true
      retentionInDays: 30
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 14
    }
    deleteRetentionPolicy: {
      allowPermanentDelete: false
      enabled: true
      days: 14
    }
    isVersioningEnabled: true
    restorePolicy: {
      enabled: false
    }
  }
}

var evidenceContainerNames = [
  'raw'
  'normalized'
  'sanitized'
  'manifests'
]

resource evidenceContainers 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' = [for containerName in evidenceContainerNames: {
  parent: blobService
  name: containerName
  properties: {
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: true
    publicAccess: 'None'
  }
}]

resource corpusContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-06-01' = {
  parent: blobService
  name: 'synthetic-corpus'
  properties: {
    defaultEncryptionScope: '$account-encryption-key'
    denyEncryptionScopeOverride: true
    publicAccess: 'None'
  }
}

resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2025-06-01' = {
  parent: storage
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'expire-private-evidence'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: [
                'raw/'
                'normalized/'
              ]
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: 90
                }
              }
              snapshot: {
                delete: {
                  daysAfterCreationGreaterThan: 30
                }
              }
              version: {
                delete: {
                  daysAfterCreationGreaterThan: 30
                }
              }
            }
          }
        }
        {
          name: 'expire-sanitized-evidence'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: ['sanitized/']
            }
            actions: {
              baseBlob: {
                delete: {
                  daysAfterModificationGreaterThan: 365
                }
              }
              version: {
                delete: {
                  daysAfterCreationGreaterThan: 90
                }
              }
            }
          }
        }
        {
          name: 'expire-corpus-versions'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: {
              blobTypes: ['blockBlob']
              prefixMatch: ['synthetic-corpus/']
            }
            actions: {
              version: {
                delete: {
                  daysAfterCreationGreaterThan: 30
                }
              }
            }
          }
        }
      ]
    }
  }
}

resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2025-06-01' = {
  parent: storage
  name: 'default'
  properties: {
    cors: {
      corsRules: []
    }
  }
}

resource reviewDecisionsTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2025-06-01' = {
  parent: tableService
  name: 'reviewdecisions'
}

resource commandRequestsTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2025-06-01' = {
  parent: tableService
  name: 'commandrequests'
}

resource assistantRateLimitsTable 'Microsoft.Storage/storageAccounts/tableServices/tables@2025-06-01' = {
  parent: tableService
  name: 'assistantratelimits'
}

resource operationsWorkspace 'Microsoft.OperationalInsights/workspaces@2025-07-01' = {
  name: workspaceName
  location: location
  tags: tags
  properties: {
    features: {
      disableLocalAuth: false
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
    retentionInDays: 30
    sku: {
      name: 'PerGB2018'
    }
    workspaceCapping: {
      dailyQuotaGb: 1
    }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  tags: tags
  properties: {
    Application_Type: 'web'
    Flow_Type: 'Bluefield'
    IngestionMode: 'LogAnalytics'
    Request_Source: 'rest'
    RetentionInDays: 30
    SamplingPercentage: 20
    WorkspaceResourceId: operationsWorkspace.id
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource keyVault 'Microsoft.KeyVault/vaults@2024-11-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    createMode: 'default'
    enablePurgeProtection: true
    enableRbacAuthorization: true
    enableSoftDelete: true
    publicNetworkAccess: 'Enabled'
    softDeleteRetentionInDays: 90
    tenantId: tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Allow'
    }
  }
}

resource signingKey 'Microsoft.KeyVault/vaults/keys@2024-11-01' = {
  parent: keyVault
  name: 'assessment-manifest-es256'
  properties: {
    attributes: {
      enabled: true
      exportable: false
    }
    curveName: 'P-256'
    keyOps: [
      'sign'
      'verify'
    ]
    kty: 'EC'
  }
}

resource pseudonymizationSecretValue 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = if (enableWorkloads) {
  parent: keyVault
  name: 'aica-pseudonymization-secret'
  properties: {
    attributes: {
      enabled: true
    }
    // substring is evaluated only for enabled workloads and enforces the 32-character floor.
    contentType: 'AICA pseudonymous security-event HMAC input; minimum=${length(substring(pseudonymizationSecret, 0, 32))}'
    value: pseudonymizationSecret
  }
}

resource githubAppPrivateKeyValue 'Microsoft.KeyVault/vaults/secrets@2024-11-01' = if (enableWorkloads) {
  parent: keyVault
  name: 'aica-github-app-private-key'
  properties: {
    attributes: {
      enabled: true
    }
    // substring is evaluated only for enabled workloads and prevents an empty secure parameter.
    contentType: 'GitHub App RSA private key; minimum=${length(substring(githubAppPrivateKey, 0, 27))}'
    value: githubAppPrivateKey
  }
}

resource bootstrapIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aica-bootstrap-${environment}'
  location: location
  tags: tags
}

resource githubDeployIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aica-github-deploy-${environment}'
  location: location
  tags: tags
}

resource assistantIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aica-assistant-${environment}'
  location: location
  tags: tags
}

resource collectorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aica-collector-${environment}'
  location: location
  tags: tags
}

resource consoleIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aica-console-${environment}'
  location: location
  tags: tags
}

resource sentinelContentIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aica-sentinel-content-${environment}'
  location: location
  tags: tags
}

resource janitorIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aica-fixture-janitor-${environment}'
  location: location
  tags: tags
}

// The command processor is deliberately separate from both the browser-facing
// console and the evidence collector. It can claim command/event rows, but it
// receives no evidence-container, Key Vault, or general Azure deployment rights.
resource commandWorkerIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aica-command-worker-${environment}'
  location: location
  tags: tags
}

resource assistantPseudonymSecretReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableWorkloads) {
  scope: pseudonymizationSecretValue
  name: guid(pseudonymizationSecretValue.id, assistantIdentity.id, 'key-vault-secrets-user')
  properties: {
    principalId: assistantIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

resource collectorGithubAppSecretReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableWorkloads) {
  scope: githubAppPrivateKeyValue
  name: guid(githubAppPrivateKeyValue.id, collectorIdentity.id, 'key-vault-secrets-user')
  properties: {
    principalId: collectorIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6')
  }
}

resource bootstrapFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository)) {
  parent: bootstrapIdentity
  name: 'github-bootstrap'
  properties: {
    audiences: ['api://AzureADTokenExchange']
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:environment:azure-bootstrap'
  }
}

resource deployFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository)) {
  parent: githubDeployIdentity
  name: 'github-deploy'
  properties: {
    audiences: ['api://AzureADTokenExchange']
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:environment:azure-deploy'
  }
}

resource fixtureFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository)) {
  parent: githubDeployIdentity
  name: 'github-failure-injection'
  properties: {
    audiences: ['api://AzureADTokenExchange']
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:environment:failure-injection'
  }
}

resource collectorFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository)) {
  parent: collectorIdentity
  name: 'github-assessment'
  properties: {
    audiences: ['api://AzureADTokenExchange']
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:environment:assessment'
  }
}

resource sentinelFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepository)) {
  parent: sentinelContentIdentity
  name: 'github-sentinel'
  properties: {
    audiences: ['api://AzureADTokenExchange']
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:environment:sentinel-content'
  }
}

// The collector writes evidence and signs manifests. It may only read the
// append-only reviewer table so a retest can seal prior, artifact-bound
// lifecycle events into the new signed package; it cannot create decisions.
resource collectorBlobContributors 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (containerName, index) in evidenceContainerNames: {
  scope: evidenceContainers[index]
  name: guid(evidenceContainers[index].id, collectorIdentity.id, 'blob-contributor')
  properties: {
    principalId: collectorIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
  }
}]

resource collectorDecisionReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: reviewDecisionsTable
  name: guid(reviewDecisionsTable.id, collectorIdentity.id, 'table-reader')
  properties: {
    principalId: collectorIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '76199698-9eea-4c19-bc75-cec21354c6b6')
  }
}

resource collectorCryptoUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, collectorIdentity.id, 'crypto-user')
  properties: {
    principalId: collectorIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '12338af0-0e69-4776-bea7-57ae8d297424')
  }
}

resource collectorOperationsLogReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: operationsWorkspace
  name: guid(operationsWorkspace.id, collectorIdentity.id, 'log-reader')
  properties: {
    principalId: collectorIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '73c42c96-874c-492b-b04d-ab87d138a893')
  }
}

resource assistantCorpusReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: corpusContainer
  name: guid(corpusContainer.id, assistantIdentity.id, 'blob-reader')
  properties: {
    principalId: assistantIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
  }
}

resource consoleEvidenceReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: evidenceContainers[2]
  name: guid(evidenceContainers[2].id, consoleIdentity.id, 'blob-reader')
  properties: {
    principalId: consoleIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '2a2b9908-6ea1-4ae2-8e65-a410df84e7d1')
  }
}

resource consoleDecisionReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: reviewDecisionsTable
  name: guid(reviewDecisionsTable.id, consoleIdentity.id, 'table-reader')
  properties: {
    principalId: consoleIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '76199698-9eea-4c19-bc75-cec21354c6b6')
  }
}

resource consoleCommandWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: commandRequestsTable
  name: guid(commandRequestsTable.id, consoleIdentity.id, 'table-contributor')
  properties: {
    principalId: consoleIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
  }
}

resource assistantRateLimitWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: assistantRateLimitsTable
  name: guid(assistantRateLimitsTable.id, assistantIdentity.id, 'table-contributor')
  properties: {
    principalId: assistantIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
  }
}

resource commandWorkerDecisionWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: reviewDecisionsTable
  name: guid(reviewDecisionsTable.id, commandWorkerIdentity.id, 'table-contributor')
  properties: {
    principalId: commandWorkerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
  }
}

resource commandWorkerCommandWriter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: commandRequestsTable
  name: guid(commandRequestsTable.id, commandWorkerIdentity.id, 'table-contributor')
  properties: {
    principalId: commandWorkerIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3')
  }
}

resource keyVaultDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: keyVault
  name: 'send-audit-to-operations'
  properties: {
    workspaceId: operationsWorkspace.id
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

resource storageDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: blobService
  name: 'send-blob-audit-to-operations'
  properties: {
    workspaceId: operationsWorkspace.id
    logs: [
      {
        categoryGroup: 'audit'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'Transaction'
        enabled: true
      }
    ]
  }
}

resource storageAccountMetrics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: storage
  name: 'send-account-metrics-to-operations'
  properties: {
    workspaceId: operationsWorkspace.id
    logs: []
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
  }
}

resource tableDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: tableService
  name: 'send-table-audit-to-operations'
  properties: {
    workspaceId: operationsWorkspace.id
    logs: [
      {
        categoryGroup: 'audit'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'Transaction'
        enabled: true
      }
    ]
  }
}

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' = {
  name: staticWebAppName
  location: staticWebAppLocation
  tags: tags
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {
    allowConfigFileUpdates: true
    enterpriseGradeCdnStatus: 'Disabled'
    provider: 'Custom'
    publicNetworkAccess: 'Enabled'
    stagingEnvironmentPolicy: 'Disabled'
  }
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: operationsWorkspace.properties.customerId
        sharedKey: operationsWorkspace.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
  }
}


output storageAccountName string = storage.name
output storageAccountId string = storage.id
output storageBlobEndpoint string = storage.properties.primaryEndpoints.blob
output storageTableEndpoint string = storage.properties.primaryEndpoints.table
output corpusBlobEndpoint string = '${storage.properties.primaryEndpoints.blob}synthetic-corpus'
output keyVaultId string = keyVault.id
output keyVaultUrl string = keyVault.properties.vaultUri
output signingKeyId string = signingKey.id
output signingKeyName string = signingKey.name
output pseudonymizationSecretUri string = enableWorkloads ? pseudonymizationSecretValue!.properties.secretUriWithVersion : ''
output githubAppPrivateKeySecretUri string = enableWorkloads ? githubAppPrivateKeyValue!.properties.secretUriWithVersion : ''
output operationsWorkspaceId string = operationsWorkspace.id
output operationsWorkspaceCustomerId string = operationsWorkspace.properties.customerId
@secure()
output operationsWorkspaceSharedKey string = operationsWorkspace.listKeys().primarySharedKey
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output staticWebAppName string = staticWebApp.name
output staticWebAppDefaultHostname string = staticWebApp.properties.defaultHostname
output containerEnvironmentName string = containerEnvironment.name
output containerEnvironmentDefaultDomain string = containerEnvironment.properties.defaultDomain
output bootstrapIdentityPrincipalId string = bootstrapIdentity.properties.principalId
output bootstrapIdentityClientId string = bootstrapIdentity.properties.clientId
output githubDeployIdentityPrincipalId string = githubDeployIdentity.properties.principalId
output githubDeployIdentityClientId string = githubDeployIdentity.properties.clientId
output assistantIdentityId string = assistantIdentity.id
output assistantIdentityPrincipalId string = assistantIdentity.properties.principalId
output assistantIdentityClientId string = assistantIdentity.properties.clientId
output collectorIdentityId string = collectorIdentity.id
output collectorIdentityPrincipalId string = collectorIdentity.properties.principalId
output collectorIdentityClientId string = collectorIdentity.properties.clientId
output consoleIdentityId string = consoleIdentity.id
output consoleIdentityPrincipalId string = consoleIdentity.properties.principalId
output consoleIdentityClientId string = consoleIdentity.properties.clientId
output sentinelContentIdentityPrincipalId string = sentinelContentIdentity.properties.principalId
output sentinelContentIdentityClientId string = sentinelContentIdentity.properties.clientId
output janitorIdentityId string = janitorIdentity.id
output janitorIdentityPrincipalId string = janitorIdentity.properties.principalId
output janitorIdentityClientId string = janitorIdentity.properties.clientId
output commandWorkerIdentityId string = commandWorkerIdentity.id
output commandWorkerIdentityPrincipalId string = commandWorkerIdentity.properties.principalId
output commandWorkerIdentityClientId string = commandWorkerIdentity.properties.clientId
