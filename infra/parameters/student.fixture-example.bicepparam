using '../main.bicep'

param environment = 'dev'
param controlLocation = 'canadacentral'
param sutLocation = 'eastus2'
param staticWebAppLocation = 'centralus'
param sentinelResourceGroupName = 'rg-sc200-sentinel-lab'
param sentinelWorkspaceName = 'law-sc200-sentinel-lab'
param budgetContactEmail = 'REPLACE_ME@example.com'
param monthlyBudgetAmount = 25

// Replace the expiry with a future UTC time no more than 24 hours away.
param fixtureScenarioId = 'excessive-managed-identity-privilege'
param fixtureExpiresOn = 'REPLACE_WITH_RFC3339_UTC'
param fixtureOwner = 'portfolio-owner'
param enableFoundry = false
param enableModelDeployment = false
param enableWorkloads = false
param enableSentinelContent = true
