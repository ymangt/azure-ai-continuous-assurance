targetScope = 'subscription'

param assignments array

resource roleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for assignment in assignments: {
  name: guid(subscription().id, assignment.principalId, assignment.roleDefinitionId)
  properties: {
    principalId: assignment.principalId
    principalType: assignment.principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', assignment.roleDefinitionId)
  }
}]
