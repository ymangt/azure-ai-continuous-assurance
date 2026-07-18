import { vi } from 'vitest';

const citation = {
  document_id: 'POL-017-exception-management', section_id: 'POL-017-exception-management-s01', title: 'Required record',
  excerpt: 'An exception records its owner, rationale, compensating controls, and expiry.', classification: 'INTERNAL', score: 0.9,
};

function apiResponse(tool: object | null) {
  return {
    correlation_id: 'corr-live-1', evaluation_id: 'eval-live-1', answer: 'Grounded answer.', citations: [citation], tool,
    guardrail_outcomes: [], model: 'replay', model_version: '1.0', latency_ms: 14, generated_at: '2026-06-08T12:00:00Z',
  };
}

describe('live Policy Assistant API adapter', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv('VITE_DATA_SOURCE', 'api');
    vi.stubEnv('VITE_API_BASE_URL', '/api/v1');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('uses separate unconfirmed and confirmed tool requests', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(apiResponse({ name: 'create_access_exception', authorization: 'ALLOWED', confirmation: 'MISSING', status: 'REJECTED', result: { reason: 'explicit confirmation is required', confirmation_token: 'server-issued-token-that-is-long-enough' } })), { status: 200, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify(apiResponse({ name: 'create_access_exception', authorization: 'ALLOWED', confirmation: 'CONFIRMED', status: 'EXECUTED', result: { request_id: 'AEX-001', status: 'PENDING_REVIEW' } })), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    const { assistantApi } = await import('./client');

    const prepared = await assistantApi.sendMessage('Create a synthetic access exception for a demonstration.', 'session-live-1', false);
    expect(prepared.message.pendingException).toBeDefined();
    const prepareBody = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
    expect(prepareBody.tool_confirmation_token).toBeUndefined();
    expect(prepareBody.requested_tool.name).toBe('create_access_exception');

    const receipt = await assistantApi.confirmException(prepared.message.pendingException!, 'session-live-1', false);
    const confirmBody = JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body));
    expect(confirmBody.tool_confirmation_token).toBe('server-issued-token-that-is-long-enough');
    expect(receipt.requestId).toBe('AEX-001');
  });

  it('performs read-only lookup through the non-consequential chat tool', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(apiResponse({ name: 'policy_lookup', authorization: 'NOT_REQUIRED', confirmation: 'NOT_REQUIRED', status: 'EXECUTED', result: { document_id: 'POL-002-access-control', section_id: 'POL-002-access-control-s01', owner: 'Policy Governance', approval_requirement: 'Policy owner approval required' } })), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    const { assistantApi } = await import('./client');

    const result = await assistantApi.lookupPolicy('temporary administrator access', false);
    const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
    expect(body.requested_tool).toMatchObject({ name: 'policy_lookup', consequential: false });
    expect(body.tool_confirmation_token).toBeUndefined();
    expect(result.owner).toBe('Policy Governance');
  });
});
