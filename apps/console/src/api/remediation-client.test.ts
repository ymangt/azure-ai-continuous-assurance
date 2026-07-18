import { vi } from 'vitest';

describe('live remediation command adapter', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv('VITE_DATA_SOURCE', 'api');
    vi.stubEnv('VITE_API_BASE_URL', '/api/v1');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('serializes all traceable remediation fields to the dedicated endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 'cmd-remediation', status: 'QUEUED', expected_version: 4, created_at: '2026-07-17T12:00:00Z',
    }), { status: 202, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    const { assuranceApi } = await import('./client');
    const body = {
      finding_id: 'FND-001',
      artifact_run_id: 'run-signed',
      owner: 'Cloud Owner',
      action: 'Remove the broad ingress rule through reviewed infrastructure code.',
      target_date: '2026-08-01T00:00:00.000Z',
      commit_or_pr: 'PR-101',
      evidence_refs: ['EVD-001'],
      expected_version: 4,
    };

    await assuranceApi.createRemediation(body);

    expect(fetchMock).toHaveBeenCalledWith('/api/v1/remediations', expect.objectContaining({ method: 'POST' }));
    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toEqual(body);
  });
});
