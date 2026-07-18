targetScope = 'resourceGroup'

param location string
param workspaceName string
param collectorPrincipalId string
param assistantPrincipalId string
param sentinelContentPrincipalId string
param tags object

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-07-01' existing = {
  name: workspaceName
}

resource assuranceTable 'Microsoft.OperationalInsights/workspaces/tables@2025-07-01' = {
  parent: workspace
  name: 'AicaAssurance_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 30
    schema: {
      name: 'AicaAssurance_CL'
      description: 'Minimal assurance run security events; no evidence payloads or raw prompts.'
      displayName: 'AICA Assurance Runs'
      columns: [
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'RunId', type: 'string' }
        { name: 'Status', type: 'string' }
        { name: 'Scope', type: 'string' }
        { name: 'CorrelationId', type: 'string' }
        { name: 'GitCommit', type: 'string' }
      ]
    }
  }
}

resource toolSecurityTable 'Microsoft.OperationalInsights/workspaces/tables@2025-07-01' = {
  parent: workspace
  name: 'AicaToolSecurity_CL'
  properties: {
    plan: 'Analytics'
    retentionInDays: 30
    totalRetentionInDays: 30
    schema: {
      name: 'AicaToolSecurity_CL'
      description: 'Content-minimized pseudonymous assistant operational events; no prompt, response, or retrieved content.'
      displayName: 'AICA Assistant Operations'
      columns: [
        { name: 'SchemaVersion', type: 'string' }
        { name: 'TimeGenerated', type: 'datetime' }
        { name: 'EventName', type: 'string' }
        { name: 'CorrelationId', type: 'string' }
        { name: 'EvaluationId', type: 'string' }
        { name: 'UserPseudonym', type: 'string' }
        { name: 'SessionId', type: 'string' }
        { name: 'Model', type: 'string' }
        { name: 'ModelVersion', type: 'string' }
        { name: 'RetrievalDocumentIds', type: 'dynamic' }
        { name: 'RetrievalClassifications', type: 'dynamic' }
        { name: 'LatencyMs', type: 'long' }
        { name: 'InputTokens', type: 'long' }
        { name: 'OutputTokens', type: 'long' }
        { name: 'Status', type: 'string' }
        { name: 'GuardrailOutcomes', type: 'dynamic' }
        { name: 'ToolName', type: 'string' }
        { name: 'AuthorizationDecision', type: 'string' }
        { name: 'ConfirmationState', type: 'string' }
        { name: 'ToolResultStatus', type: 'string' }
        // Compatibility fields used by the existing read-only evidence collector.
        { name: 'Decision', type: 'string' }
        { name: 'Reason', type: 'string' }
      ]
    }
  }
}

resource dcr 'Microsoft.Insights/dataCollectionRules@2024-03-11' = {
  name: 'dcr-aica-security-events'
  location: location
  kind: 'Direct'
  tags: tags
  properties: {
    description: 'Direct ingestion for bounded assurance and content-minimized assistant operational schemas.'
    streamDeclarations: {
      'Custom-AicaAssurance_CL': {
        columns: [
          { name: 'TimeGenerated', type: 'datetime' }
          { name: 'RunId', type: 'string' }
          { name: 'Status', type: 'string' }
          { name: 'Scope', type: 'string' }
          { name: 'CorrelationId', type: 'string' }
          { name: 'GitCommit', type: 'string' }
        ]
      }
      'Custom-AicaToolSecurity_CL': {
        columns: [
          { name: 'SchemaVersion', type: 'string' }
          { name: 'TimeGenerated', type: 'datetime' }
          { name: 'EventName', type: 'string' }
          { name: 'CorrelationId', type: 'string' }
          { name: 'EvaluationId', type: 'string' }
          { name: 'UserPseudonym', type: 'string' }
          { name: 'SessionId', type: 'string' }
          { name: 'Model', type: 'string' }
          { name: 'ModelVersion', type: 'string' }
          { name: 'RetrievalDocumentIds', type: 'dynamic' }
          { name: 'RetrievalClassifications', type: 'dynamic' }
          { name: 'LatencyMs', type: 'long' }
          { name: 'InputTokens', type: 'long' }
          { name: 'OutputTokens', type: 'long' }
          { name: 'Status', type: 'string' }
          { name: 'GuardrailOutcomes', type: 'dynamic' }
          { name: 'ToolName', type: 'string' }
          { name: 'AuthorizationDecision', type: 'string' }
          { name: 'ConfirmationState', type: 'string' }
          { name: 'ToolResultStatus', type: 'string' }
          { name: 'Decision', type: 'string' }
          { name: 'Reason', type: 'string' }
        ]
      }
    }
    destinations: {
      logAnalytics: [
        {
          name: 'sentinel'
          workspaceResourceId: workspace.id
        }
      ]
    }
    dataFlows: [
      {
        streams: ['Custom-AicaAssurance_CL']
        destinations: ['sentinel']
        outputStream: 'Custom-AicaAssurance_CL'
        transformKql: 'source'
      }
      {
        streams: ['Custom-AicaToolSecurity_CL']
        destinations: ['sentinel']
        outputStream: 'Custom-AicaToolSecurity_CL'
        transformKql: 'source'
      }
    ]
  }
  dependsOn: [
    assuranceTable
    toolSecurityTable
  ]
}

resource collectorDcrPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: dcr
  name: guid(dcr.id, collectorPrincipalId, 'monitoring-publisher')
  properties: {
    principalId: collectorPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
  }
}

resource assistantDcrPublisher 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: dcr
  name: guid(dcr.id, assistantPrincipalId, 'monitoring-publisher')
  properties: {
    principalId: assistantPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb')
  }
}

resource collectorLogReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: workspace
  name: guid(workspace.id, collectorPrincipalId, 'log-reader')
  properties: {
    principalId: collectorPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '73c42c96-874c-492b-b04d-ab87d138a893')
  }
}

resource sentinelContentContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, sentinelContentPrincipalId, 'sentinel-contributor')
  properties: {
    principalId: sentinelContentPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ab8e14d6-4a74-4a29-9ba8-549422addade')
  }
}

var analyticsRules = [
  {
    key: 'risky-role-or-nsg-change'
    displayName: 'AICA - Risky RBAC or NSG control-plane change'
    description: 'Detects successful role-assignment and NSG changes for review, emphasizing privileged roles and broad ingress.'
    severity: 'High'
    query: loadTextContent('../../sentinel/queries/risky-role-or-nsg-change.kql')
    queryFrequency: 'PT15M'
    queryPeriod: 'PT30M'
    tactics: ['PrivilegeEscalation', 'DefenseEvasion']
    techniques: ['T1098', 'T1562']
    entityMappings: [
      {
        entityType: 'Account'
        fieldMappings: [
          { identifier: 'FullName', columnName: 'Caller' }
        ]
      }
      {
        entityType: 'AzureResource'
        fieldMappings: [
          { identifier: 'ResourceId', columnName: 'ResourceId' }
        ]
      }
    ]
  }
  {
    key: 'diagnostic-setting-deletion'
    displayName: 'AICA - Azure diagnostic setting deleted'
    description: 'Detects successful diagnostic-setting deletion, a direct threat to evidence availability.'
    severity: 'High'
    query: loadTextContent('../../sentinel/queries/diagnostic-setting-deletion.kql')
    queryFrequency: 'PT15M'
    queryPeriod: 'PT30M'
    tactics: ['DefenseEvasion']
    techniques: ['T1562.008']
    entityMappings: [
      {
        entityType: 'Account'
        fieldMappings: [
          { identifier: 'FullName', columnName: 'Caller' }
        ]
      }
      {
        entityType: 'AzureResource'
        fieldMappings: [
          { identifier: 'ResourceId', columnName: 'ResourceId' }
        ]
      }
    ]
  }
  {
    key: 'failed-or-stale-assurance-run'
    displayName: 'AICA - Failed or stale assurance run'
    description: 'Detects explicit run failures and the absence of a successful scheduled run for 26 hours.'
    severity: 'Medium'
    query: loadTextContent('../../sentinel/queries/failed-or-stale-assurance-run.kql')
    queryFrequency: 'PT1H'
    queryPeriod: 'P2D'
    tactics: ['Impact']
    techniques: ['T1496']
    entityMappings: []
  }
  {
    key: 'repeated-rejected-ai-tool-escalation'
    displayName: 'AICA - Repeated rejected AI tool escalation'
    description: 'Detects at least three rejected consequential-tool requests by one pseudonymous session in five minutes.'
    severity: 'Medium'
    query: loadTextContent('../../sentinel/queries/repeated-rejected-ai-tool-escalation.kql')
    queryFrequency: 'PT5M'
    queryPeriod: 'PT15M'
    tactics: ['PrivilegeEscalation']
    techniques: ['T1548']
    entityMappings: []
  }
]

resource rules 'Microsoft.SecurityInsights/alertRules@2024-09-01' = [for rule in analyticsRules: {
  scope: workspace
  name: guid(workspace.id, rule.key)
  kind: 'Scheduled'
  properties: {
    alertRuleTemplateName: null
    customDetails: {}
    description: rule.description
    displayName: rule.displayName
    enabled: true
    entityMappings: rule.entityMappings
    eventGroupingSettings: {
      aggregationKind: 'AlertPerResult'
    }
    incidentConfiguration: {
      createIncident: true
      groupingConfiguration: {
        enabled: true
        groupByAlertDetails: []
        groupByCustomDetails: []
        groupByEntities: []
        lookbackDuration: 'PT5H'
        matchingMethod: 'AllEntities'
        reopenClosedIncident: false
      }
    }
    query: rule.query
    queryFrequency: rule.queryFrequency
    queryPeriod: rule.queryPeriod
    severity: rule.severity
    suppressionDuration: 'PT5H'
    suppressionEnabled: false
    tactics: rule.tactics
    techniques: rule.techniques
    triggerOperator: 'GreaterThan'
    triggerThreshold: 0
  }
  dependsOn: [
    assuranceTable
    toolSecurityTable
  ]
}]

resource workbook 'Microsoft.Insights/workbooks@2023-06-01' = {
  name: guid(workspace.id, 'aica-security-workbook')
  location: location
  kind: 'shared'
  tags: tags
  properties: {
    category: 'sentinel'
    description: 'Focused assurance and AI security monitoring. Not a certification dashboard.'
    displayName: 'Azure AI Continuous Assurance'
    serializedData: loadTextContent('../../sentinel/workbook.json')
    sourceId: workspace.id
    version: 'Notebook/1.0'
  }
}

output dcrId string = dcr.id
output dcrImmutableId string = dcr.properties.immutableId
output logsIngestionEndpoint string = dcr.properties.endpoints.logsIngestion
output workbookId string = workbook.id
