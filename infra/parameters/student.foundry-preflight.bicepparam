using '../main.bicep'

param environment = 'dev'
param controlLocation = 'canadacentral'
param sutLocation = 'eastus2'
param staticWebAppLocation = 'centralus'
param sentinelResourceGroupName = 'rg-sc200-sentinel-lab'
param sentinelWorkspaceName = 'law-sc200-sentinel-lab'
param budgetContactEmail = 'REPLACE_ME@example.com'
param monthlyBudgetAmount = 25

// Account/project only. Query quota and run a tiny MCP smoke request after this deployment.
param enableFoundry = true
param enableModelDeployment = false
param enableWorkloads = false
param enableSentinelContent = true
param fixtureScenarioId = ''
param fixtureExpiresOn = ''
