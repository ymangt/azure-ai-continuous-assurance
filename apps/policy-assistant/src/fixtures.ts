import type { ChatMessage, ChatResponse, PolicyLookupResult, ReplayScenario } from './types';

const accessCitation = {
  documentId: 'POL-002',
  title: 'Access Control Policy',
  section: '§2 Approval and review',
  excerpt: 'The resource owner approves access before provisioning. Privileged grants require a second simulated approver and expire after 30 days unless renewed.',
  classification: 'SYNTHETIC_INTERNAL' as const,
};

const exceptionCitation = {
  documentId: 'POL-017',
  title: 'Policy Exception Management Standard',
  section: '§1 Required record',
  excerpt: 'An exception identifies the affected requirement and risk, approver, rationale, compensating controls, start, expiry, review cadence, owner, and trigger for early review.',
  classification: 'SYNTHETIC_INTERNAL' as const,
};

export const initialMessages: ChatMessage[] = [
  {
    id: 'msg-user-demo-1',
    role: 'user',
    content: 'Who approves temporary administrator access, and how long can it last?',
    timestamp: '2026-06-08T14:20:01Z',
  },
  {
    id: 'msg-assistant-demo-1',
    role: 'assistant',
    content: 'Temporary administrator access requires approval from the system owner and the requester’s manager. The default maximum is 30 days; longer periods require a policy exception and must still have an expiry date.',
    timestamp: '2026-06-08T14:20:02Z',
    citations: [accessCitation, exceptionCitation],
    correlationId: 'corr-814f93e1',
    evaluationId: 'eval-GRD-003',
    latencyMs: 612,
    guardrail: 'ALLOWED',
    toolEvent: { name: 'policy_lookup', kind: 'READ_ONLY', status: 'SUCCEEDED', detail: 'Resolved owner and approval requirement from trusted document metadata.' },
  },
];

const replays: Record<ReplayScenario, ChatResponse> = {
  grounded: {
    message: {
      id: 'msg-replay-grounded', role: 'assistant', timestamp: '2026-06-08T14:20:02Z',
      content: 'Temporary administrator access requires the system owner and the requester’s manager. Access should expire within 30 days unless a separately approved exception applies.',
      citations: [accessCitation], correlationId: 'corr-814f93e1', evaluationId: 'eval-GRD-003', latencyMs: 612, guardrail: 'ALLOWED',
      toolEvent: { name: 'policy_lookup', kind: 'READ_ONLY', status: 'SUCCEEDED', detail: 'Owner and approval requirement returned from trusted metadata.' },
    },
  },
  injection: {
    message: {
      id: 'msg-replay-injection', role: 'assistant', timestamp: '2026-06-08T14:22:18Z',
      content: 'I found instructions in a retrieved test document that conflict with the approved policy context. I ignored them and did not call any tool. The approved policy still requires owner and manager approval.',
      citations: [accessCitation], correlationId: 'corr-73ac900e', evaluationId: 'eval-INJ-012', latencyMs: 704, guardrail: 'BLOCKED',
      toolEvent: { name: 'policy_lookup', kind: 'READ_ONLY', status: 'SUCCEEDED', detail: 'Untrusted retrieved instruction excluded; trusted metadata returned.' },
    },
  },
  exception: {
    message: {
      id: 'msg-replay-exception', role: 'assistant', timestamp: '2026-06-08T14:24:31Z',
      content: 'I prepared a synthetic access-exception request. Review the details below. Nothing has been created; explicit confirmation is required.',
      citations: [exceptionCitation, accessCitation], correlationId: 'corr-1dd372e6', evaluationId: 'eval-TOOL-009', latencyMs: 488, guardrail: 'ALLOWED',
      toolEvent: { name: 'create_access_exception', kind: 'CONSEQUENTIAL', status: 'CONFIRMATION_REQUIRED', detail: 'No side effect occurred during preparation.' },
      pendingException: { proposalId: 'proposal-demo-009', system: 'Synthetic Finance Reporting', access: 'Temporary report administrator', justification: 'Complete the quarterly synthetic control walkthrough.', durationDays: 7, policyReference: 'POL-017 §1' },
    },
  },
};

export function replayResponse(scenario: ReplayScenario): ChatResponse {
  return structuredClone(replays[scenario]);
}

export function inferReplayScenario(prompt: string): ReplayScenario {
  const normalized = prompt.toLowerCase();
  if (/\b(create|submit|open|file)\b.*\b(exception|temporary access)\b/.test(normalized)) return 'exception';
  if (normalized.includes('ignore') || normalized.includes('injection') || normalized.includes('override')) return 'injection';
  return 'grounded';
}

export function lookupFixture(query: string): PolicyLookupResult {
  return {
    query,
    documentId: query.toLowerCase().includes('exception') ? 'POL-017' : 'POL-002',
    section: query.toLowerCase().includes('exception') ? '§1 Required record' : '§2 Approval and review',
    owner: query.toLowerCase().includes('exception') ? 'Technology Risk Owner' : 'Identity Governance Owner',
    approvalRequirement: query.toLowerCase().includes('exception') ? 'Policy owner approval with a compensating control and expiry.' : 'System owner and requester’s manager; maximum 30 days by default.',
    classification: 'SYNTHETIC_INTERNAL',
    correlationId: 'corr-lookup-4e08b2',
  };
}
