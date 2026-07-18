targetScope = 'resourceGroup'

param location string
param environment string
param suffix string
param tags object
param enableWorkloads bool
param assessedGitCommit string
param assuranceApiImage string
param assuranceApiImageSha256 string
param assistantUiImage string
param assistantUiImageSha256 string
param assuranceJobImageSha256 string
param phiImage string
param enablePhiFallback bool
param assistantClientId string
param tenantId string
param assistantIdentityId string
param assistantIdentityPrincipalId string
param assistantIdentityClientId string
param collectorIdentityPrincipalId string
param collectorIdentityClientId string
param operationsWorkspaceId string
param operationsWorkspaceCustomerId string
@secure()
param operationsWorkspaceSharedKey string
param appInsightsConnectionString string
param corpusBlobEndpoint string
param corpusBlobPrefix string
param storageTableEndpoint string
param pseudonymizationSecretUri string
param sentinelDcrEndpoint string
param sentinelDcrImmutableId string
param enableFoundry bool
param enableModelDeployment bool
param foundryModelName string
param foundryModelVersion string
param foundryModelCapacity int

var foundryAccountName = 'aif-aica-${take(suffix, 8)}'
var foundryProjectName = 'policy-assistant'
var modelDeploymentName = 'policy-${replace(foundryModelName, '.', '-')}'
var environmentName = 'cae-aica-sut-${environment}'
var openIdIssuer = '${az.environment().authentication.loginEndpoint}${tenantId}/v2.0'

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = if (enableFoundry) {
  name: foundryAccountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned, UserAssigned'
    userAssignedIdentities: {
      '${assistantIdentityId}': {}
    }
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: foundryAccountName
    disableLocalAuth: true
    dynamicThrottlingEnabled: true
    publicNetworkAccess: 'Enabled'
    restrictOutboundNetworkAccess: false
    networkAcls: {
      defaultAction: 'Allow'
      ipRules: []
      virtualNetworkRules: []
    }
  }
}

resource foundryProject 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = if (enableFoundry) {
  parent: foundry
  name: foundryProjectName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${assistantIdentityId}': {}
    }
  }
  properties: {
    description: 'Synthetic internal policy assistant system under assurance.'
    displayName: 'AICA Policy Assistant'
  }
}

resource modelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = if (enableModelDeployment) {
  parent: foundry
  name: modelDeploymentName
  sku: {
    name: 'GlobalStandard'
    capacity: foundryModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: foundryModelName
      version: foundryModelVersion
    }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
  }
}

resource assistantFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableFoundry) {
  scope: foundry
  name: guid(foundry.id, assistantIdentityId, 'openai-user')
  properties: {
    principalId: assistantIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}

resource collectorFoundryUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableFoundry) {
  scope: foundry
  name: guid(foundry.id, collectorIdentityPrincipalId, 'controlled-evaluation-openai-user')
  properties: {
    principalId: collectorIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd')
  }
}

resource foundryDiagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (enableFoundry) {
  scope: foundry
  name: 'send-audit-to-operations'
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

resource containerEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: operationsWorkspaceCustomerId
        sharedKey: operationsWorkspaceSharedKey
      }
    }
    zoneRedundant: false
  }
}

resource phiModel 'Microsoft.App/containerApps@2025-01-01' = if (enableWorkloads && enablePhiFallback) {
  name: 'ca-aica-phi-${environment}'
  location: location
  tags: union(tags, {
    costProfile: 'manual-demo-only'
    model: 'Phi-4-mini-instruct-onnx-int4'
  })
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        // The model is reachable cross-environment only through Entra-authenticated ingress.
        external: true
        targetPort: 8000
        transport: 'http'
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
    }
    template: {
      containers: [
        {
          name: 'phi-4-mini'
          image: phiImage
          env: [
            {
              name: 'PHI_MODEL_PATH'
              value: '/models/phi'
            }
          ]
          resources: {
            cpu: json('4.0')
            memory: '8Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 1
        rules: [
          {
            name: 'internal-http'
            http: {
              metadata: {
                concurrentRequests: '1'
              }
            }
          }
        ]
      }
    }
  }
}

resource phiAuth 'Microsoft.App/containerApps/authConfigs@2025-01-01' = if (enableWorkloads && enablePhiFallback) {
  parent: phiModel
  name: 'current'
  properties: {
    globalValidation: {
      excludedPaths: ['/healthz']
      unauthenticatedClientAction: 'Return401'
    }
    httpSettings: {
      requireHttps: true
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        isAutoProvisioned: false
        registration: {
          clientId: assistantClientId
          openIdIssuer: openIdIssuer
        }
        validation: {
          allowedAudiences: ['api://${assistantClientId}']
          defaultAuthorizationPolicy: {
            allowedApplications: [
              assistantIdentityClientId
              collectorIdentityClientId
            ]
          }
        }
      }
    }
    login: {
      tokenStore: {
        enabled: false
      }
    }
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
  }
}

resource policyAssistant 'Microsoft.App/containerApps@2025-01-01' = if (enableWorkloads) {
  name: 'ca-aica-assistant-${environment}'
  location: location
  tags: union(tags, {
    deployedSourceCommit: assessedGitCommit
    assuranceApiImageSha256: assuranceApiImageSha256
    assistantUiImageSha256: assistantUiImageSha256
    assuranceJobImageSha256: assuranceJobImageSha256
  })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${assistantIdentityId}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        allowInsecure: false
        external: true
        targetPort: 8080
        transport: 'auto'
        traffic: [
          {
            latestRevision: true
            weight: 100
          }
        ]
      }
      secrets: [
        {
          name: 'pseudonymization-secret'
          keyVaultUrl: pseudonymizationSecretUri
          identity: assistantIdentityId
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'policy-assistant-ui'
          image: assistantUiImage
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
        {
          name: 'policy-assistant-api'
          image: assuranceApiImage
          env: [
            {
              name: 'AICA_ENV'
              value: 'production'
            }
            {
              name: 'AICA_PUBLIC_MODE'
              value: 'true'
            }
            {
              name: 'AICA_ASSISTANT_ENABLED'
              value: 'true'
            }
            {
              name: 'AICA_ASSURANCE_ENABLED'
              value: 'false'
            }
            {
              name: 'AICA_ARTIFACT_DIR'
              value: '/tmp/aica-artifacts'
            }
            {
              name: 'AZURE_CLIENT_ID'
              value: assistantIdentityClientId
            }
            {
              name: 'AICA_AZURE_CLIENT_ID'
              value: assistantIdentityClientId
            }
            {
              name: 'AICA_CORPUS_BLOB_ENDPOINT'
              value: corpusBlobEndpoint
            }
            {
              name: 'AICA_CORPUS_BLOB_PREFIX'
              value: corpusBlobPrefix
            }
            {
              name: 'AICA_MODEL_ADAPTER'
              value: enableModelDeployment ? 'foundry' : (enablePhiFallback ? 'phi' : 'replay')
            }
            {
              name: 'AICA_FOUNDRY_ENDPOINT'
              value: enableFoundry ? foundry!.properties.endpoint : ''
            }
            {
              name: 'AICA_MODEL_DEPLOYMENT'
              value: enableModelDeployment ? modelDeployment.name : ''
            }
            {
              name: 'AICA_PHI_ENDPOINT'
              value: enablePhiFallback ? 'https://${phiModel!.properties.configuration.ingress.fqdn}' : ''
            }
            {
              name: 'AICA_PHI_TOKEN_SCOPE'
              value: enablePhiFallback ? 'api://${assistantClientId}/.default' : ''
            }
            {
              name: 'AICA_MODEL_MAX_OUTPUT_TOKENS'
              value: '400'
            }
            {
              name: 'AICA_DEPLOYED_SOURCE_COMMIT'
              value: assessedGitCommit
            }
            {
              name: 'AICA_ASSURANCE_API_IMAGE_SHA256'
              value: assuranceApiImageSha256
            }
            {
              name: 'AICA_ASSISTANT_UI_IMAGE_SHA256'
              value: assistantUiImageSha256
            }
            {
              name: 'AICA_ASSURANCE_JOB_IMAGE_SHA256'
              value: assuranceJobImageSha256
            }
            {
              name: 'AICA_REQUEST_LIMIT_PER_USER_PER_HOUR'
              value: '10'
            }
            {
              name: 'AICA_CONFIRMATION_TTL_SECONDS'
              value: '300'
            }
            {
              name: 'AICA_AZURE_TABLE_ENDPOINT'
              value: storageTableEndpoint
            }
            {
              name: 'AICA_AZURE_RATE_LIMIT_TABLE'
              value: 'assistantratelimits'
            }
            {
              name: 'AICA_PSEUDONYMIZATION_SECRET'
              secretRef: 'pseudonymization-secret'
            }
            {
              name: 'AICA_REQUIRE_TOOL_CONFIRMATION'
              value: 'true'
            }
            {
              name: 'AICA_LOG_CONTENT'
              value: 'false'
            }
            {
              name: 'AICA_SENTINEL_DCR_ENDPOINT'
              value: sentinelDcrEndpoint
            }
            {
              name: 'AICA_SENTINEL_DCR_IMMUTABLE_ID'
              value: sentinelDcrImmutableId
            }
            {
              name: 'APPLICATIONINSIGHTS_CONNECTION_STRING'
              value: appInsightsConnectionString
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        // Confirmation tokens and per-user limits are process-local, so the
        // consequential-tool boundary is intentionally single-replica.
        maxReplicas: 1
        rules: [
          {
            name: 'http'
            http: {
              metadata: {
                concurrentRequests: '10'
              }
            }
          }
        ]
      }
    }
  }
}

resource assistantAuth 'Microsoft.App/containerApps/authConfigs@2025-01-01' = if (enableWorkloads) {
  parent: policyAssistant
  name: 'current'
  properties: {
    globalValidation: {
      excludedPaths: ['/healthz']
      redirectToProvider: 'azureactivedirectory'
      unauthenticatedClientAction: 'RedirectToLoginPage'
    }
    httpSettings: {
      requireHttps: true
      routes: {
        apiPrefix: '/.auth'
      }
    }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        isAutoProvisioned: false
        registration: {
          clientId: assistantClientId
          openIdIssuer: openIdIssuer
        }
        validation: {
          allowedAudiences: ['api://${assistantClientId}']
          defaultAuthorizationPolicy: {
            allowedApplications: [assistantClientId]
          }
        }
      }
    }
    login: {
      preserveUrlFragmentsForLogins: false
      routes: {
        logoutEndpoint: '/.auth/logout'
      }
      tokenStore: {
        enabled: false
      }
    }
    platform: {
      enabled: true
      runtimeVersion: '~1'
    }
  }
}

output foundryAccountName string = enableFoundry ? foundry!.name : ''
output foundryProjectName string = enableFoundry ? foundryProject!.name : ''
output foundryEndpoint string = enableFoundry ? foundry!.properties.endpoint : ''
output modelDeploymentName string = enableModelDeployment ? modelDeployment!.name : ''
output containerEnvironmentDefaultDomain string = containerEnvironment.properties.defaultDomain
output policyAssistantFqdn string = enableWorkloads ? policyAssistant!.properties.configuration.ingress.fqdn : ''
output phiFqdn string = enableWorkloads && enablePhiFallback ? phiModel!.properties.configuration.ingress.fqdn : ''
