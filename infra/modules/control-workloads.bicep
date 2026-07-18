targetScope = 'resourceGroup'

param location string
param environment string
param tags object
param tenantId string
param githubRepository string
param githubAppId string
param githubAppInstallationId string
param githubAppPrivateKeySecretUri string
param assessedGitCommit string
param assuranceApiClientId string
param assuranceApiImage string
param assuranceApiImageSha256 string
param assuranceJobImage string
param assuranceJobImageSha256 string
param assistantUiImageSha256 string
param consoleUiImage string
param containerEnvironmentName string
param consoleIdentityId string
param consoleIdentityClientId string
param collectorIdentityId string
param collectorIdentityClientId string
param janitorIdentityId string
param janitorIdentityClientId string
param commandWorkerIdentityId string
param commandWorkerIdentityPrincipalId string
param commandWorkerIdentityClientId string
param commandWorkerJobStarterRoleDefinitionId string
param storageBlobEndpoint string
param storageTableEndpoint string
param keyVaultUrl string
param signingKeyName string
param trustedSigningKeyFingerprints string
param trustedSigningKeyIdPrefix string
param appInsightsConnectionString string
param sentinelWorkspaceCustomerId string
param sentinelDcrEndpoint string
param sentinelDcrImmutableId string
param fixtureResourceGroupName string
param modelAdapter string
param modelDeployment string
param foundryEndpoint string
param phiEndpoint string
param phiTokenScope string
param deployedConfigurationUrl string

var openIdIssuer = '${az.environment().authentication.loginEndpoint}${tenantId}/v2.0'

resource containerEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' existing = {
  name: containerEnvironmentName
}

resource assuranceConsole 'Microsoft.App/containerApps@2025-01-01' = {
  name: 'ca-aica-console-${environment}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${consoleIdentityId}': {}
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
    }
    template: {
      containers: [
        {
          name: 'console-ui'
          image: consoleUiImage
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
        {
          name: 'assurance-api'
          image: assuranceApiImage
          env: [
            { name: 'AICA_ENV', value: 'production' }
            { name: 'AICA_PUBLIC_MODE', value: 'false' }
            { name: 'AICA_ASSISTANT_ENABLED', value: 'false' }
            { name: 'AICA_ASSURANCE_ENABLED', value: 'true' }
            { name: 'AZURE_CLIENT_ID', value: consoleIdentityClientId }
            { name: 'AICA_AZURE_CLIENT_ID', value: consoleIdentityClientId }
            { name: 'AICA_AZURE_TENANT_ID', value: tenantId }
            { name: 'AICA_AZURE_BLOB_ENDPOINT', value: storageBlobEndpoint }
            { name: 'AICA_AZURE_PUBLIC_EVIDENCE_CONTAINER', value: 'sanitized' }
            { name: 'AICA_AZURE_PRIVATE_EVIDENCE_CONTAINER', value: 'sanitized' }
            { name: 'AICA_AZURE_TABLE_ENDPOINT', value: storageTableEndpoint }
            { name: 'AICA_AZURE_COMMAND_TABLE', value: 'commandrequests' }
            { name: 'AICA_TRUSTED_SIGNING_KEY_FINGERPRINTS', value: trustedSigningKeyFingerprints }
            { name: 'AICA_TRUSTED_SIGNING_KEY_ID_PREFIX', value: trustedSigningKeyIdPrefix }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'AICA_LOG_CONTENT', value: 'false' }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: 2
        rules: [
          {
            name: 'http'
            http: {
              metadata: {
                concurrentRequests: '20'
              }
            }
          }
        ]
      }
    }
  }
}

resource assuranceAuth 'Microsoft.App/containerApps/authConfigs@2025-01-01' = {
  parent: assuranceConsole
  name: 'current'
  properties: {
    globalValidation: {
      excludedPaths: ['/healthz']
      redirectToProvider: 'azureactivedirectory'
      unauthenticatedClientAction: 'Return401'
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
          clientId: assuranceApiClientId
          openIdIssuer: openIdIssuer
        }
        validation: {
          allowedAudiences: ['api://${assuranceApiClientId}']
          defaultAuthorizationPolicy: {
            allowedApplications: [assuranceApiClientId]
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

resource assessmentJob 'Microsoft.App/jobs@2025-01-01' = {
  name: 'caj-aica-assess-${environment}'
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
      '${collectorIdentityId}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      replicaRetryLimit: 1
      // Transient 429 backoff remains bounded by the scheduled-job cost ceiling.
      replicaTimeout: 900
      secrets: [
        {
          name: 'github-app-private-key'
          keyVaultUrl: githubAppPrivateKeySecretUri
          identity: collectorIdentityId
        }
      ]
      scheduleTriggerConfig: {
        cronExpression: '0 6 * * *'
        parallelism: 1
        replicaCompletionCount: 1
      }
      triggerType: 'Schedule'
    }
    template: {
      containers: [
        {
          name: 'assessor'
          image: assuranceJobImage
          command: ['assure']
          args: [
            'collect'
            '--profile'
            'azure-dev'
            '--release-gate'
          ]
          env: [
            { name: 'AICA_ENV', value: 'production' }
            { name: 'AICA_PUBLIC_MODE', value: 'false' }
            { name: 'AICA_ARTIFACT_DIR', value: '/tmp/aica-artifacts' }
            { name: 'AICA_AI_EVALUATION_MODE', value: 'live' }
            { name: 'AICA_MODEL_ADAPTER', value: modelAdapter }
            { name: 'AICA_MODEL_DEPLOYMENT', value: modelDeployment }
            { name: 'AICA_FOUNDRY_ENDPOINT', value: foundryEndpoint }
            { name: 'AICA_PHI_ENDPOINT', value: phiEndpoint }
            { name: 'AICA_PHI_TOKEN_SCOPE', value: phiTokenScope }
            { name: 'AICA_DEPLOYED_CONFIGURATION_URL', value: deployedConfigurationUrl }
            { name: 'AICA_DEPLOYED_SOURCE_COMMIT', value: assessedGitCommit }
            { name: 'AICA_ASSURANCE_API_IMAGE_SHA256', value: assuranceApiImageSha256 }
            { name: 'AICA_ASSISTANT_UI_IMAGE_SHA256', value: assistantUiImageSha256 }
            { name: 'AICA_ASSURANCE_JOB_IMAGE_SHA256', value: assuranceJobImageSha256 }
            { name: 'AZURE_CLIENT_ID', value: collectorIdentityClientId }
            { name: 'AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
            { name: 'AICA_AZURE_CLIENT_ID', value: collectorIdentityClientId }
            { name: 'AICA_AZURE_TENANT_ID', value: tenantId }
            { name: 'AICA_AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
            { name: 'AICA_AZURE_LOG_ANALYTICS_WORKSPACE_ID', value: sentinelWorkspaceCustomerId }
            { name: 'AICA_AZURE_BLOB_ENDPOINT', value: storageBlobEndpoint }
            { name: 'AICA_AZURE_PRIVATE_EVIDENCE_CONTAINER', value: 'raw' }
            { name: 'AICA_AZURE_PUBLIC_EVIDENCE_CONTAINER', value: 'sanitized' }
            { name: 'AICA_AZURE_TABLE_ENDPOINT', value: storageTableEndpoint }
            { name: 'AICA_AZURE_REVIEW_TABLE', value: 'reviewdecisions' }
            { name: 'AICA_ASSESSED_GIT_COMMIT', value: assessedGitCommit }
            { name: 'AICA_AUTHORIZATION_PROBE_ENDPOINT', value: 'https://${assuranceConsole.properties.configuration.ingress.fqdn}/api/v1/runs' }
            { name: 'AICA_AUTHORIZATION_PROBE_SCOPE', value: 'api://${assuranceApiClientId}/.default' }
            { name: 'AICA_AZURE_KEY_VAULT_URL', value: keyVaultUrl }
            { name: 'AICA_AZURE_KEY_NAME', value: signingKeyName }
            { name: 'AICA_TRUSTED_SIGNING_KEY_FINGERPRINTS', value: trustedSigningKeyFingerprints }
            { name: 'AICA_TRUSTED_SIGNING_KEY_ID_PREFIX', value: trustedSigningKeyIdPrefix }
            { name: 'AICA_GITHUB_REPOSITORY', value: githubRepository }
            { name: 'AICA_GITHUB_APP_ID', value: githubAppId }
            { name: 'AICA_GITHUB_APP_INSTALLATION_ID', value: githubAppInstallationId }
            { name: 'AICA_GITHUB_APP_PRIVATE_KEY', secretRef: 'github-app-private-key' }
            { name: 'AICA_SENTINEL_DCR_ENDPOINT', value: sentinelDcrEndpoint }
            { name: 'AICA_SENTINEL_DCR_IMMUTABLE_ID', value: sentinelDcrImmutableId }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'AICA_LOG_CONTENT', value: 'false' }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
    }
  }
}

// Only the command worker receives this custom role, and the assignment is on
// the assessment job itself rather than the resource group or subscription.
resource commandWorkerAssessmentStarter 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: assessmentJob
  name: guid(assessmentJob.id, commandWorkerIdentityId, 'assessment-job-starter')
  properties: {
    principalId: commandWorkerIdentityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: commandWorkerJobStarterRoleDefinitionId
  }
}

resource commandWorkerJob 'Microsoft.App/jobs@2025-01-01' = {
  name: 'caj-aica-commands-${environment}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${commandWorkerIdentityId}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      replicaRetryLimit: 1
      replicaTimeout: 180
      scheduleTriggerConfig: {
        cronExpression: '*/5 * * * *'
        parallelism: 1
        replicaCompletionCount: 1
      }
      triggerType: 'Schedule'
    }
    template: {
      containers: [
        {
          name: 'command-worker'
          image: assuranceJobImage
          command: ['assure']
          args: [
            'commands'
            'process'
            '--once'
          ]
          env: [
            { name: 'AICA_ENV', value: 'production' }
            { name: 'AZURE_CLIENT_ID', value: commandWorkerIdentityClientId }
            { name: 'AICA_AZURE_CLIENT_ID', value: commandWorkerIdentityClientId }
            { name: 'AICA_AZURE_TENANT_ID', value: tenantId }
            { name: 'AICA_AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
            { name: 'AICA_AZURE_TABLE_ENDPOINT', value: storageTableEndpoint }
            { name: 'AICA_AZURE_COMMAND_TABLE', value: 'commandrequests' }
            { name: 'AICA_AZURE_REVIEW_TABLE', value: 'reviewdecisions' }
            { name: 'AICA_AZURE_ASSESSMENT_JOB_RESOURCE_ID', value: assessmentJob.id }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
            { name: 'AICA_LOG_CONTENT', value: 'false' }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
  }
  // Prevent the first five-minute poll from racing the initial RBAC deployment.
  dependsOn: [commandWorkerAssessmentStarter]
}

resource janitorJob 'Microsoft.App/jobs@2025-01-01' = {
  name: 'caj-aica-janitor-${environment}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${janitorIdentityId}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      replicaRetryLimit: 0
      replicaTimeout: 600
      scheduleTriggerConfig: {
        cronExpression: '15 3 * * *'
        parallelism: 1
        replicaCompletionCount: 1
      }
      triggerType: 'Schedule'
    }
    template: {
      containers: [
        {
          name: 'fixture-janitor'
          image: assuranceJobImage
          command: ['assure']
          args: [
            'fixture'
            'cleanup-expired'
            '--resource-group'
            fixtureResourceGroupName
            '--require-tag'
            'managedBy=bicep'
            '--require-tag'
            'dataClassification=synthetic'
          ]
          env: [
            { name: 'AICA_ENV', value: 'production' }
            { name: 'AZURE_CLIENT_ID', value: janitorIdentityClientId }
            { name: 'AICA_AZURE_CLIENT_ID', value: janitorIdentityClientId }
            { name: 'AICA_AZURE_TENANT_ID', value: tenantId }
            { name: 'AICA_AZURE_SUBSCRIPTION_ID', value: subscription().subscriptionId }
            { name: 'AICA_FIXTURE_GROUP', value: fixtureResourceGroupName }
            { name: 'AICA_DELETE_RESOURCE_GROUP', value: 'false' }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
          ]
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
    }
  }
}

output assuranceConsoleFqdn string = assuranceConsole.properties.configuration.ingress.fqdn
output assessmentJobName string = assessmentJob.name
output janitorJobName string = janitorJob.name
output commandWorkerJobName string = commandWorkerJob.name
