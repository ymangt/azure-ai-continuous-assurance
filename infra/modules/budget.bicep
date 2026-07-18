targetScope = 'subscription'

param budgetName string
@minValue(1)
param amount int
param contactEmail string
param startDate string

resource budget 'Microsoft.Consumption/budgets@2024-08-01' = {
  name: budgetName
  properties: {
    amount: amount
    category: 'Cost'
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: '${startDate}T00:00:00Z'
    }
    notifications: {
      Actual50: {
        contactEmails: [contactEmail]
        enabled: true
        locale: 'en-us'
        operator: 'GreaterThanOrEqualTo'
        threshold: 50
        thresholdType: 'Actual'
      }
      Actual75: {
        contactEmails: [contactEmail]
        enabled: true
        locale: 'en-us'
        operator: 'GreaterThanOrEqualTo'
        threshold: 75
        thresholdType: 'Actual'
      }
      Actual90: {
        contactEmails: [contactEmail]
        enabled: true
        locale: 'en-us'
        operator: 'GreaterThanOrEqualTo'
        threshold: 90
        thresholdType: 'Actual'
      }
      Forecast100: {
        contactEmails: [contactEmail]
        enabled: true
        locale: 'en-us'
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
      }
      Actual100: {
        contactEmails: [contactEmail]
        enabled: true
        locale: 'en-us'
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
      }
    }
  }
}

output budgetId string = budget.id
