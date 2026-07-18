export interface Citation {
  documentId: string;
  title: string;
  section: string;
  excerpt: string;
  classification: 'SYNTHETIC_INTERNAL';
}

export interface ToolEvent {
  name: 'policy_lookup' | 'create_access_exception';
  kind: 'READ_ONLY' | 'CONSEQUENTIAL';
  status: 'SUCCEEDED' | 'CONFIRMATION_REQUIRED' | 'CANCELLED' | 'CREATED' | 'BLOCKED';
  detail: string;
}

export interface PendingException {
  proposalId: string;
  system: string;
  access: string;
  justification: string;
  durationDays: number;
  policyReference: string;
  confirmationToken?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  citations?: Citation[];
  correlationId?: string;
  evaluationId?: string;
  latencyMs?: number;
  guardrail?: 'ALLOWED' | 'BLOCKED' | 'ABSTAINED';
  toolEvent?: ToolEvent;
  pendingException?: PendingException;
}

export interface ChatResponse {
  message: ChatMessage;
}

export interface PolicyLookupResult {
  query: string;
  documentId: string;
  section: string;
  owner: string;
  approvalRequirement: string;
  classification: 'SYNTHETIC_INTERNAL';
  correlationId: string;
}

export interface ExceptionReceipt {
  requestId: string;
  status: 'CREATED';
  createdAt: string;
  synthetic: true;
  correlationId: string;
}

export type ReplayScenario = 'grounded' | 'injection' | 'exception';
export type UiState = 'ready' | 'loading' | 'error' | 'empty' | 'stale';
