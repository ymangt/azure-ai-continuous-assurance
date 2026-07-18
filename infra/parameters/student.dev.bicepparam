using '../main.bicep'

param environment = 'dev'
param controlLocation = 'canadacentral'
param sutLocation = 'eastus2'
param staticWebAppLocation = 'centralus'
param controlResourceGroupName = 'rg-aica-control-cc'
param sutResourceGroupName = 'rg-aica-sut-eus2'
param fixtureResourceGroupName = 'rg-aica-fixture-eus2'
param sentinelResourceGroupName = 'rg-sc200-sentinel-lab'
param sentinelWorkspaceName = 'law-sc200-sentinel-lab'

// Replace before MCP What-If. scripts/azure/preflight.sh rejects this value.
param budgetContactEmail = 'REPLACE_ME@example.com'
param monthlyBudgetAmount = 25

// Safe first deployment: foundational resources and Sentinel content only.
param githubRepository = ''
param enableWorkloads = false
param enableFoundry = false
param enableModelDeployment = false
param enableSentinelContent = true
param fixtureScenarioId = ''
param fixtureExpiresOn = ''
