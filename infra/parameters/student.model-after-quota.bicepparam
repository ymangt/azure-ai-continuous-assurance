using '../main.bicep'

param environment = 'dev'
param controlLocation = 'canadacentral'
param sutLocation = 'eastus2'
param staticWebAppLocation = 'centralus'
param sentinelResourceGroupName = 'rg-sc200-sentinel-lab'
param sentinelWorkspaceName = 'law-sc200-sentinel-lab'
param budgetContactEmail = 'REPLACE_ME@example.com'
param monthlyBudgetAmount = 25

// Do not use until MCP evidence proves non-zero East US 2 quota.
param enableFoundry = true
param enableModelDeployment = true
param foundryModelName = 'gpt-4o-mini'
param foundryModelVersion = '2024-07-18'
param foundryModelCapacity = 1
param enableWorkloads = false
param enableSentinelContent = true
param fixtureScenarioId = ''
param fixtureExpiresOn = ''
