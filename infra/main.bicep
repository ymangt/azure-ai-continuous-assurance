targetScope = 'subscription'

@description('Short environment label used in names and tags.')
@allowed([
  'dev'
  'demo'
])
param environment string = 'dev'

@description('Region for the persistent assurance plane. Student policy allows Canada Central.')
@allowed([
  'canadacentral'
])
param controlLocation string = 'canadacentral'

@description('Region for the system under assurance and Foundry. Student policy allows East US 2.')
@allowed([
  'eastus2'
])
param sutLocation string = 'eastus2'

@description('Static Web Apps metadata region. Central US is an allowed Student region.')
@allowed([
  'centralus'
])
param staticWebAppLocation string = 'centralus'

param controlResourceGroupName string = 'rg-aica-control-cc'
param sutResourceGroupName string = 'rg-aica-sut-eus2'
param fixtureResourceGroupName string = 'rg-aica-fixture-eus2'
param sentinelResourceGroupName string = 'rg-sc200-sentinel-lab'
param sentinelWorkspaceName string = 'law-sc200-sentinel-lab'

@description('Repository in owner/name form. Required before federated credentials are enabled.')
param githubRepository string = ''

@description('Numeric ID of the read-only GitHub App used by the evidence collector.')
param githubAppId string = ''

@description('Numeric installation ID for the collector GitHub App on the target repository.')
param githubAppInstallationId string = ''

@description('Exact source commit assessed by scheduled workloads and bound to GitHub workflow artifacts.')
param assessedGitCommit string = ''

@description('Immutable public GHCR API image from deploy/api.Dockerfile, including @sha256:...')
param assuranceApiImage string = ''

@description('Immutable public GHCR job image from deploy/job.Dockerfile, including @sha256:...')
param assuranceJobImage string = ''

@description('Immutable public GHCR private Console UI image, including @sha256:...')
param consoleUiImage string = ''

@description('Immutable public GHCR Policy Assistant UI image, including @sha256:...')
param assistantUiImage string = ''

@description('Immutable public GHCR Phi-4 fallback image, including @sha256:...')
param phiImage string = ''

@description('Deploy Container Apps only after signed immutable images and Entra application registrations exist.')
param enableWorkloads bool = false

@description('Entra application/client ID protecting the assurance API.')
param assuranceApiClientId string = ''

@description('Entra application/client ID protecting the Policy Assistant.')
param assistantClientId string = ''

@description('Comma-delimited SHA-256 JWK thumbprints accepted for signed assessment packages. Obtain the Key Vault public-key thumbprint after the foundation deployment and supply it for workloads.')
param trustedSigningKeyFingerprints string = ''

@secure()
@description('High-entropy stable HMAC input for pseudonymous assistant security events. Supply only through the protected Azure MCP deployment, never a committed parameter file.')
param pseudonymizationSecret string = ''

@secure()
@description('RSA private key for the collector GitHub App. Supply only through the protected Azure MCP deployment, never a committed parameter file.')
param githubAppPrivateKey string = ''

@description('Create the Foundry account and project. This is independent of model quota.')
param enableFoundry bool = false

@description('Deploy the model only after an MCP quota check and smoke-test gate has passed.')
param enableModelDeployment bool = false

@description('Deploy the scale-to-zero Phi-4 CPU fallback behind identity-restricted Easy Auth only after Foundry quota is confirmed unavailable.')
param enablePhiFallback bool = false

param foundryModelName string = 'gpt-4o-mini'
param foundryModelVersion string = '2024-07-18'

@minValue(1)
@maxValue(10)
@description('Global Standard capacity in thousands of TPM. Keep at the smallest quota-supported value.')
param foundryModelCapacity int = 1

@description('Budget notification recipient. Deployment preflight rejects placeholder domains.')
param budgetContactEmail string

@minValue(1)
@maxValue(25)
param monthlyBudgetAmount int = 25

@description('Stable first day of the initial budget month (YYYY-MM-DD). Keep unchanged on later deployments.')
param budgetStartDate string = '2026-07-01'

@description('Create the Sentinel custom tables, Direct DCR, four rules, and workbook in the existing workspace.')
param enableSentinelContent bool = true

@description('Fixture scenario. Empty means no injected condition.')
@allowed([
  ''
  'excessive-managed-identity-privilege'
  'missing-diagnostic-settings'
])
param fixtureScenarioId string = ''

@description('UTC RFC3339 expiry for fixture resources, required when a scenario is enabled.')
param fixtureExpiresOn string = ''

@description('Pseudonymous owner tag for fixture cleanup accountability.')
param fixtureOwner string = 'portfolio-owner'

var suffix = take(uniqueString(subscription().subscriptionId, environment), 10)
// Workload preflight accepts only immutable refs, and the protected image-set handoff binds all
// four refs to assessedGitCommit. Derive runtime provenance from those exact refs rather than
// accepting independently entered digest parameters.
var assuranceApiImageSha256 = enableWorkloads ? last(split(assuranceApiImage, '@sha256:')) : ''
var assuranceJobImageSha256 = enableWorkloads ? last(split(assuranceJobImage, '@sha256:')) : ''
var assistantUiImageSha256 = enableWorkloads ? last(split(assistantUiImage, '@sha256:')) : ''
// The runtime prefix is compiled from the same integrity-bound source manifest used by the
// Azure MCP corpus handoff. Changing corpus bytes without advancing the manifest version makes
// the create-only handoff fail rather than silently replacing a deployed corpus.
var corpusManifest = loadJsonContent('../data/policy-corpus/manifest.json')
var corpusBlobPrefix = '${corpusManifest.corpus_id}/${corpusManifest.version}'
var workloadModelPath = !enableWorkloads
  ? 'disabled'
  : enableModelDeployment && !enablePhiFallback
    ? (enableFoundry ? 'foundry' : fail('A Foundry model deployment requires enableFoundry=true.'))
    : !enableModelDeployment && enablePhiFallback
      ? 'phi'
      : fail('Workloads require exactly one live model path: Foundry or Phi.')
var baseTags = {
  project: 'azure-ai-continuous-assurance'
  environment: environment
  managedBy: 'bicep'
  dataClassification: 'synthetic'
  costCenter: 'portfolio'
  modelReleasePath: workloadModelPath
}

// A resource-group-limited custom role avoids the much broader built-in
// Container Apps Jobs Operator role (which also permits stop, exec, logstream,
// and general job mutation). The assignment itself is scoped to one job below.
resource commandWorkerJobStarterRole 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(subscription().id, 'aica-assessment-job-starter')
  properties: {
    roleName: 'AICA Assessment Job Starter'
    description: 'Allows the AICA command worker to read and start only its assigned assessment job.'
    type: 'CustomRole'
    permissions: [
      {
        actions: [
          'Microsoft.App/jobs/read'
          'Microsoft.App/jobs/execution/read'
          'Microsoft.App/jobs/start/action'
        ]
        notActions: []
        dataActions: []
        notDataActions: []
      }
    ]
    assignableScopes: [controlRg.id]
  }
}

// scripts/azure/preflight.sh enforces cross-parameter invariants before MCP What-If.
// The conditional Key Vault secret also fails ARM validation if a workload deployment omits
// the minimum-length secure value, without enabling experimental Bicep assertions.

resource controlRg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: controlResourceGroupName
  location: controlLocation
  tags: union(baseTags, {
    lifecycle: 'persistent'
    plane: 'assurance'
  })
}

resource sutRg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: sutResourceGroupName
  location: sutLocation
  tags: union(baseTags, {
    lifecycle: 'demonstration'
    plane: 'system-under-assurance'
  })
}

resource fixtureRg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: fixtureResourceGroupName
  location: sutLocation
  tags: union(baseTags, {
    lifecycle: 'ephemeral'
    plane: 'fixture'
    expiresOn: empty(fixtureExpiresOn) ? 'not-active' : fixtureExpiresOn
    scenarioId: empty(fixtureScenarioId) ? 'none' : fixtureScenarioId
    owner: fixtureOwner
  })
}

resource sentinelRg 'Microsoft.Resources/resourceGroups@2024-03-01' existing = {
  name: sentinelResourceGroupName
}

resource sentinelWorkspace 'Microsoft.OperationalInsights/workspaces@2025-07-01' existing = {
  scope: sentinelRg
  name: sentinelWorkspaceName
}

module control './modules/control-plane.bicep' = {
  name: 'aica-control-${environment}'
  scope: controlRg
  params: {
    location: controlLocation
    staticWebAppLocation: staticWebAppLocation
    environment: environment
    suffix: suffix
    tags: union(baseTags, {
      lifecycle: 'persistent'
      plane: 'assurance'
    })
    githubRepository: githubRepository
    enableWorkloads: enableWorkloads
    tenantId: tenant().tenantId
    pseudonymizationSecret: pseudonymizationSecret
    githubAppPrivateKey: githubAppPrivateKey
  }
}

module sut './modules/sut-plane.bicep' = {
  name: 'aica-sut-${environment}'
  scope: sutRg
  params: {
    location: sutLocation
    environment: environment
    suffix: suffix
    tags: union(baseTags, {
      lifecycle: 'demonstration'
      plane: 'system-under-assurance'
    })
    enableWorkloads: enableWorkloads
    assessedGitCommit: assessedGitCommit
    assuranceApiImage: assuranceApiImage
    assuranceApiImageSha256: assuranceApiImageSha256
    assistantUiImage: assistantUiImage
    assistantUiImageSha256: assistantUiImageSha256
    assuranceJobImageSha256: assuranceJobImageSha256
    phiImage: phiImage
    enablePhiFallback: enablePhiFallback
    assistantClientId: assistantClientId
    tenantId: tenant().tenantId
    assistantIdentityId: control.outputs.assistantIdentityId
    assistantIdentityPrincipalId: control.outputs.assistantIdentityPrincipalId
    assistantIdentityClientId: control.outputs.assistantIdentityClientId
    collectorIdentityPrincipalId: control.outputs.collectorIdentityPrincipalId
    collectorIdentityClientId: control.outputs.collectorIdentityClientId
    operationsWorkspaceId: control.outputs.operationsWorkspaceId
    operationsWorkspaceCustomerId: control.outputs.operationsWorkspaceCustomerId
    operationsWorkspaceSharedKey: control.outputs.operationsWorkspaceSharedKey
    appInsightsConnectionString: control.outputs.appInsightsConnectionString
    corpusBlobEndpoint: control.outputs.corpusBlobEndpoint
    corpusBlobPrefix: corpusBlobPrefix
    storageTableEndpoint: control.outputs.storageTableEndpoint
    pseudonymizationSecretUri: control.outputs.pseudonymizationSecretUri
    sentinelDcrEndpoint: enableSentinelContent ? sentinel!.outputs.logsIngestionEndpoint : ''
    sentinelDcrImmutableId: enableSentinelContent ? sentinel!.outputs.dcrImmutableId : ''
    enableFoundry: enableFoundry
    enableModelDeployment: enableModelDeployment
    foundryModelName: foundryModelName
    foundryModelVersion: foundryModelVersion
    foundryModelCapacity: foundryModelCapacity
  }
}

module fixture './modules/fixture-plane.bicep' = {
  name: 'aica-fixture-${environment}'
  scope: fixtureRg
  params: {
    location: sutLocation
    suffix: suffix
    scenarioId: fixtureScenarioId
    expiresOn: fixtureExpiresOn
    owner: fixtureOwner
    operationsWorkspaceId: control.outputs.operationsWorkspaceId
    tags: union(baseTags, {
      lifecycle: 'ephemeral'
      plane: 'fixture'
    })
  }
}

module controlRbac './modules/resource-group-rbac.bicep' = {
  name: 'aica-control-rbac-${environment}'
  scope: controlRg
  params: {
    assignments: [
      {
        principalId: control.outputs.bootstrapIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
      }
      {
        principalId: control.outputs.githubDeployIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
      }
      {
        principalId: control.outputs.collectorIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
      }
    ]
  }
}

module sutRbac './modules/resource-group-rbac.bicep' = {
  name: 'aica-sut-rbac-${environment}'
  scope: sutRg
  params: {
    assignments: [
      {
        principalId: control.outputs.bootstrapIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
      }
      {
        principalId: control.outputs.githubDeployIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
      }
      {
        principalId: control.outputs.collectorIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
      }
    ]
  }
}

module fixtureRbac './modules/resource-group-rbac.bicep' = {
  name: 'aica-fixture-rbac-${environment}'
  scope: fixtureRg
  params: {
    assignments: [
      {
        principalId: control.outputs.bootstrapIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: 'f58310d9-a9f6-439a-9e8d-f62e7b41a168'
      }
      {
        principalId: control.outputs.githubDeployIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
      }
      {
        principalId: control.outputs.collectorIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: 'acdd72a7-3385-48ef-bd42-f606fba81ae7'
      }
      {
        principalId: control.outputs.janitorIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: 'b24988ac-6180-42a0-ab88-20f7382dd24c'
      }
    ]
  }
}

module subscriptionRbac './modules/subscription-rbac.bicep' = {
  name: 'aica-subscription-read-${environment}'
  params: {
    assignments: [
      {
        principalId: control.outputs.collectorIdentityPrincipalId
        principalType: 'ServicePrincipal'
        roleDefinitionId: '39bc4728-0917-49c7-9d2c-d95423bc2eb4'
      }
    ]
  }
}

module sentinel './modules/sentinel-content.bicep' = if (enableSentinelContent) {
  name: 'aica-sentinel-${environment}'
  scope: sentinelRg
  params: {
    location: controlLocation
    workspaceName: sentinelWorkspaceName
    collectorPrincipalId: control.outputs.collectorIdentityPrincipalId
    assistantPrincipalId: control.outputs.assistantIdentityPrincipalId
    sentinelContentPrincipalId: control.outputs.sentinelContentIdentityPrincipalId
    tags: union(baseTags, {
      lifecycle: 'persistent'
      plane: 'security'
    })
  }
}

module controlWorkloads './modules/control-workloads.bicep' = if (enableWorkloads) {
  name: 'aica-control-workloads-${environment}'
  scope: controlRg
  params: {
    location: controlLocation
    environment: environment
    tags: union(baseTags, {
      lifecycle: 'persistent'
      plane: 'assurance'
    })
    tenantId: tenant().tenantId
    githubRepository: githubRepository
    githubAppId: githubAppId
    githubAppInstallationId: githubAppInstallationId
    githubAppPrivateKeySecretUri: control.outputs.githubAppPrivateKeySecretUri
    assessedGitCommit: assessedGitCommit
    assuranceApiClientId: assuranceApiClientId
    assuranceApiImage: assuranceApiImage
    assuranceApiImageSha256: assuranceApiImageSha256
    assuranceJobImage: assuranceJobImage
    assuranceJobImageSha256: assuranceJobImageSha256
    assistantUiImageSha256: assistantUiImageSha256
    consoleUiImage: consoleUiImage
    containerEnvironmentName: control.outputs.containerEnvironmentName
    consoleIdentityId: control.outputs.consoleIdentityId
    consoleIdentityClientId: control.outputs.consoleIdentityClientId
    collectorIdentityId: control.outputs.collectorIdentityId
    collectorIdentityClientId: control.outputs.collectorIdentityClientId
    janitorIdentityId: control.outputs.janitorIdentityId
    janitorIdentityClientId: control.outputs.janitorIdentityClientId
    commandWorkerIdentityId: control.outputs.commandWorkerIdentityId
    commandWorkerIdentityPrincipalId: control.outputs.commandWorkerIdentityPrincipalId
    commandWorkerIdentityClientId: control.outputs.commandWorkerIdentityClientId
    commandWorkerJobStarterRoleDefinitionId: commandWorkerJobStarterRole.id
    storageBlobEndpoint: control.outputs.storageBlobEndpoint
    storageTableEndpoint: control.outputs.storageTableEndpoint
    keyVaultUrl: control.outputs.keyVaultUrl
    signingKeyName: control.outputs.signingKeyName
    trustedSigningKeyFingerprints: trustedSigningKeyFingerprints
    trustedSigningKeyIdPrefix: '${control.outputs.keyVaultUrl}keys/${control.outputs.signingKeyName}/'
    appInsightsConnectionString: control.outputs.appInsightsConnectionString
    sentinelWorkspaceCustomerId: sentinelWorkspace.properties.customerId
    sentinelDcrEndpoint: sentinel!.outputs.logsIngestionEndpoint
    sentinelDcrImmutableId: sentinel!.outputs.dcrImmutableId
    fixtureResourceGroupName: fixtureResourceGroupName
    modelAdapter: enableModelDeployment ? 'foundry' : (enablePhiFallback ? 'phi' : 'replay')
    modelDeployment: sut.outputs.modelDeploymentName
    foundryEndpoint: sut.outputs.foundryEndpoint
    phiEndpoint: enablePhiFallback ? 'https://${sut.outputs.phiFqdn}' : ''
    phiTokenScope: enablePhiFallback ? 'api://${assistantClientId}/.default' : ''
    deployedConfigurationUrl: 'https://${sut.outputs.policyAssistantFqdn}/healthz'
  }
}

module budget './modules/budget.bicep' = {
  name: 'aica-budget-${environment}'
  params: {
    budgetName: 'budget-aica-${environment}'
    amount: monthlyBudgetAmount
    contactEmail: budgetContactEmail
    startDate: budgetStartDate
  }
}

output controlResourceGroupId string = controlRg.id
output sutResourceGroupId string = sutRg.id
output fixtureResourceGroupId string = fixtureRg.id
output evidenceStorageAccountName string = control.outputs.storageAccountName
output evidenceBlobEndpoint string = control.outputs.storageBlobEndpoint
output keyVaultUrl string = control.outputs.keyVaultUrl
output signingKeyId string = control.outputs.signingKeyId
output staticWebAppName string = control.outputs.staticWebAppName
output staticWebAppDefaultHostname string = control.outputs.staticWebAppDefaultHostname
output assuranceAuthRedirectUri string = 'https://ca-aica-console-${environment}.${control.outputs.containerEnvironmentDefaultDomain}/.auth/login/aad/callback'
output assistantAuthRedirectUri string = 'https://ca-aica-assistant-${environment}.${sut.outputs.containerEnvironmentDefaultDomain}/.auth/login/aad/callback'
output assuranceConsoleFqdn string = enableWorkloads ? controlWorkloads!.outputs.assuranceConsoleFqdn : ''
output policyAssistantFqdn string = sut.outputs.policyAssistantFqdn
output phiFqdn string = sut.outputs.phiFqdn
output foundryAccountName string = sut.outputs.foundryAccountName
output foundryEndpoint string = sut.outputs.foundryEndpoint
output modelDeploymentName string = sut.outputs.modelDeploymentName
output githubDeployClientId string = control.outputs.githubDeployIdentityClientId
output bootstrapClientId string = control.outputs.bootstrapIdentityClientId
output collectorClientId string = control.outputs.collectorIdentityClientId
output assistantIdentityClientId string = control.outputs.assistantIdentityClientId
output consoleIdentityClientId string = control.outputs.consoleIdentityClientId
output sentinelContentClientId string = control.outputs.sentinelContentIdentityClientId
output commandWorkerClientId string = control.outputs.commandWorkerIdentityClientId
output commandWorkerJobName string = enableWorkloads ? controlWorkloads!.outputs.commandWorkerJobName : ''
output sentinelWorkspaceCustomerId string = sentinelWorkspace.properties.customerId
output sentinelDcrImmutableId string = enableSentinelContent ? sentinel!.outputs.dcrImmutableId : ''
output sentinelLogsIngestionEndpoint string = enableSentinelContent ? sentinel!.outputs.logsIngestionEndpoint : ''
