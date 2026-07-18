using '../main.bicep'

param environment = 'dev'
param controlLocation = 'canadacentral'
param sutLocation = 'eastus2'
param staticWebAppLocation = 'centralus'
param sentinelResourceGroupName = 'rg-sc200-sentinel-lab'
param sentinelWorkspaceName = 'law-sc200-sentinel-lab'
param budgetContactEmail = 'REPLACE_ME@example.com'
param monthlyBudgetAmount = 25

// Replace only after CI publishes signed images and Entra app registrations exist.
param githubRepository = 'SET_ME_OWNER/SET_ME_REPOSITORY'
param githubAppId = 'SET_ME_NUMERIC_GITHUB_APP_ID'
param githubAppInstallationId = 'SET_ME_NUMERIC_GITHUB_APP_INSTALLATION_ID'
param assessedGitCommit = 'SET_ME_40_HEX_SOURCE_COMMIT'
param assuranceApiImage = 'SET_ME_API_IMAGE_WITH_DIGEST'
param assuranceJobImage = 'SET_ME_JOB_IMAGE_WITH_DIGEST'
param consoleUiImage = 'SET_ME_CONSOLE_IMAGE_WITH_DIGEST'
param assistantUiImage = 'SET_ME_ASSISTANT_IMAGE_WITH_DIGEST'
param assuranceApiClientId = 'SET_ME_CONSOLE_ENTRA_CLIENT_ID'
param assistantClientId = 'SET_ME_ASSISTANT_ENTRA_CLIENT_ID'
param trustedSigningKeyFingerprints = 'SET_ME_KEY_VAULT_JWK_SHA256_FINGERPRINT'

// The secure pseudonymizationSecret and githubAppPrivateKey are intentionally absent.
// Supply them separately to the protected MCP What-If/deployment; never serialize them.
param enableWorkloads = true
param enableFoundry = false
param enableModelDeployment = false
param enablePhiFallback = false
param enableSentinelContent = true
param fixtureScenarioId = ''
param fixtureExpiresOn = ''
