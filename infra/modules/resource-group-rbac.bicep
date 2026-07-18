targetScope = 'resourceGroup'

@description('Narrow role assignments for this resource group. Role definition IDs must be built-in GUIDs.')
param assignments array

resource roleAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for assignment in assignments: {
  name: guid(resourceGroup().id, assignment.principalId, assignment.roleDefinitionId)
  properties: {
    principalId: assignment.principalId
    principalType: assignment.principalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', assignment.roleDefinitionId)
  }
}]
