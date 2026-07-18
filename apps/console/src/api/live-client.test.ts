import { vi } from 'vitest';

describe('live Assurance API command adapter', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv('VITE_DATA_SOURCE', 'api');
    vi.stubEnv('VITE_API_BASE_URL', '/api/v1');
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('serializes a run request to the strict FastAPI contract', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      id: 'cmd-run-1', status: 'QUEUED', expected_version: null, created_at: '2026-06-08T12:00:00Z',
    }), { status: 202, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    const { assuranceApi } = await import('./client');

    const receipt = await assuranceApi.queueRun('full-approved-scope');
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(request.body))).toEqual({
      profile: 'azure-dev',
      reason: 'Manual assessment requested for full approved scope.',
    });
    expect(receipt.request_id).toBe('cmd-run-1');
  });

  it('maps reviewer decisions and exceptions to append-only command fields', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'cmd-decision', status: 'QUEUED', expected_version: 1, created_at: '2026-06-08T12:00:00Z' }), { status: 202, headers: { 'Content-Type': 'application/json' } }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ id: 'cmd-exception', status: 'QUEUED', expected_version: 1, created_at: '2026-06-08T12:01:00Z' }), { status: 202, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    const { assuranceApi } = await import('./client');

    await assuranceApi.recordDecision({ subject_type: 'suggestion', subject_id: 'sug-203', artifact_run_id: 'run-current', prior_state: 'SUGGESTED', decision: 'ACCEPTED', rationale: 'Evidence references are valid.', expected_version: 1 });
    await assuranceApi.createException({ finding_id: 'FND-005', artifact_run_id: 'run-current', rationale: 'Short-term acceptance for the synthetic demonstration.', compensating_control: 'Daily review of rejected assistant tool events.', expires_at: '2026-08-15', expected_version: 1 });

    expect(JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body))).toMatchObject({ subject_type: 'AI_SUGGESTION', artifact_run_id: 'run-current', prior_state: 'SUGGESTED', expected_version: 1 });
    expect(JSON.parse(String((fetchMock.mock.calls[1][1] as RequestInit).body))).toMatchObject({ artifact_run_id: 'run-current', compensating_controls: ['Daily review of rejected assistant tool events.'], review_cadence: 'monthly' });
  });

  it('normalizes the Python assessment package read model without mock verdict fallback', async () => {
    const prior = { id: '018f6d9a-7b10-7c01-8000-000000000001', trigger: 'manual', scope: ['fixture'], observation_window_start: '2026-06-01T11:00:00Z', observation_window_end: '2026-06-01T12:00:00Z', git_commit: '0000001', collector_version: '1.0.0', evaluator_version: '1.0.0', started_at: '2026-06-01T12:00:00Z', ended_at: '2026-06-01T12:10:00Z', status: 'COMPLETED', estimated_cost_cad: 0.1 };
    const current = { ...prior, id: '018f6d9a-7b10-7c01-8000-000000000002', trigger: 'retest', prior_run_id: prior.id, started_at: '2026-06-08T12:00:00Z', ended_at: '2026-06-08T12:10:00Z', manifest_digest: 'b'.repeat(64) };
    const assessmentPackage = {
      run: current,
      objectives: [{ id: 'SC-7.1', source_control: 'SC-7', title: 'Boundary protection', objective: 'No broad administrative ingress.', methods: ['TEST'], cadence: 'daily', owner: 'Cloud Owner', automated: true, limitations: ['Eventually consistent.'], crosswalk: { MCSB: ['NS-1'] } }],
      test_results: [{ objective_id: 'SC-7.1', status: 'PASS', reason: 'No broad rule.', evidence_refs: ['EVD-R-008'] }],
      assessments: [{ objective_id: 'SC-7.1', design_effectiveness: 'EFFECTIVE', operating_effectiveness: 'EFFECTIVE', evidence_freshness: 'FRESH', rationale: 'Fresh evidence supports the conclusion.', review_version: 4 }],
      evidence: [{ id: 'EVD-R-008', source: 'AZURE_RESOURCE_GRAPH', scope: ['fixture NSG'], captured_at: '2026-06-08T12:04:00Z', query_digest: 'a'.repeat(64), collector_version: '1.1.0', media_type: 'application/json', sha256: 'c'.repeat(64), sanitized_sha256: 'd'.repeat(64), blob_version: 'v2', classification: 'INTERNAL', freshness: 'FRESH', redaction_profile: 'public-v1', sanitized_summary: 'No Internet RDP rule.' }],
      remediations: [{ finding_id: 'FND-001', owner: 'Cloud Owner', action: 'Remove broad rule.', target_date: '2026-06-07', commit_or_pr: 'PR-101' }],
      retests: [{ finding_id: 'FND-001', after_run_id: current.id, tested_at: '2026-06-08T12:10:00Z', result: 'PASS', evidence_refs: ['EVD-R-008'], rationale: 'Fresh evidence supports closure.' }],
      exceptions: [],
    };
    const finding = { id: 'FND-001', title: 'Broad RDP rule', status: 'CLOSED', severity: 'HIGH', criteria: 'SC-7.1', condition: 'Rule existed.', cause: 'Legacy fixture.', consequence: 'Possible exposure.', severity_rationale: 'High baseline risk.', affected_controls: ['SC-7.1'], affected_assets: ['fixture'], review_version: 6 };
    const risk = { id: 'RSK-001', finding_id: 'FND-001', statement: 'Unsafe ingress could recur.', likelihood: 3, impact: 4, inherent_score: 12, residual_score: 3, confidence: 'HIGH', treatment: 'MITIGATE', owner: 'Cloud Owner' };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.endsWith('/runs') ? [current, prior]
        : url.includes(`/runs/${current.id}`) ? assessmentPackage
          : url.endsWith('/findings') ? [finding]
            : url.endsWith('/risks') ? [risk]
              : url.includes('/diffs?') ? { from_run_id: prior.id, to_run_id: current.id, changes: [{ objective_id: 'SC-7.1', category: 'resolved', from_status: 'FAIL', to_status: 'PASS' }] }
                : undefined;
      return Promise.resolve(payload === undefined
        ? new Response('not found', { status: 404 })
        : new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const { loadConsoleSnapshot } = await import('./client');

    const snapshot = await loadConsoleSnapshot();
    if (!snapshot) throw new Error('expected a two-run live snapshot');
    expect(snapshot.selectedRun.id).toBe(current.id);
    expect(snapshot.controls[0]).toMatchObject({ id: 'SC-7.1', result: 'PASS', freshness: 'CURRENT', changed: 'resolved', reviewVersion: 4 });
    expect(snapshot.evidence[0]).toMatchObject({ id: 'EVD-R-008', redaction: 'SANITIZED', controlIds: ['SC-7.1'] });
    expect(snapshot.findings[0]).toMatchObject({ id: 'FND-001', owner: 'Cloud Owner', status: 'CLOSED', reviewVersion: 6 });
    expect(snapshot.evaluation.total).toBe(0);
    expect(snapshot.system).toBeUndefined();
    expect(snapshot.runs).toHaveLength(2);
    expect(snapshot.comparisonAvailable).toBe(true);
  });

  it('returns an honest empty state when no signed runs exist', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify([]), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    vi.stubGlobal('fetch', fetchMock);
    const { loadConsoleSnapshot } = await import('./client');

    await expect(loadConsoleSnapshot()).resolves.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('loads one real run without inventing a comparison or calling the diff endpoint', async () => {
    const run = { id: 'run-only', trigger: 'manual', scope: ['fixture'], observation_window_start: '2026-07-16T11:00:00Z', observation_window_end: '2026-07-16T12:00:00Z', git_commit: 'abcdef0', collector_version: '1.0.0', evaluator_version: '1.0.0', started_at: '2026-07-16T12:00:00Z', ended_at: '2026-07-16T12:05:00Z', status: 'REVIEW_REQUIRED', manifest_digest: 'a'.repeat(64), estimated_cost_cad: 0.1 };
    const packageValue = { run, objectives: [], test_results: [], assessments: [], evidence: [], remediations: [], retests: [], exceptions: [] };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.endsWith('/runs') ? [run]
        : url.endsWith('/runs/run-only') ? packageValue
          : url.endsWith('/findings') || url.endsWith('/risks') ? []
            : undefined;
      return Promise.resolve(payload === undefined
        ? new Response('not found', { status: 404 })
        : new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const { loadConsoleSnapshot } = await import('./client');

    const snapshot = await loadConsoleSnapshot();
    expect(snapshot).not.toBeNull();
    expect(snapshot?.selectedRun.id).toBe('run-only');
    expect(snapshot?.selectedRun.status).toBe('REVIEW_REQUIRED');
    expect(snapshot?.priorRun.id).toBe('run-only');
    expect(snapshot?.comparisonAvailable).toBe(false);
    expect(fetchMock.mock.calls.some(([input]) => String(input).includes('/diffs?'))).toBe(false);
  });

  it('loads evaluation evidence by the selected signed run instead of a build-time fixture ID', async () => {
    const run = { id: 'run-evaluated', trigger: 'manual', scope: ['fixture'], observation_window_start: '2026-07-16T11:00:00Z', observation_window_end: '2026-07-16T12:00:00Z', git_commit: 'abcdef0', collector_version: '1.0.0', evaluator_version: '1.0.0', started_at: '2026-07-16T12:00:00Z', ended_at: '2026-07-16T12:05:00Z', status: 'REVIEW_REQUIRED', manifest_digest: 'a'.repeat(64), estimated_cost_cad: 0.1 };
    const packageValue = { run, objectives: [], test_results: [], assessments: [], evidence: [], remediations: [], retests: [], exceptions: [] };
    const evaluation = { id: 'eval-bound', model: 'FoundryModelAdapter', executionMode: 'LIVE', promptVersion: `sha256:${'b'.repeat(64)}`, datasetVersion: '1.1.0', createdAt: '2026-07-16T12:04:00Z', total: 1, passed: 1, precision: 0.95, recall: 0.94, f1: 0.945, citationValidity: 1, abstentionQuality: 0.97, reviewerRejectionRate: 0.03, suggestedMapping: { id: 'suggestion:run-evaluated', text: 'Candidate mapping bound to the signed run.', state: 'SUGGESTED', reviewVersion: 0 }, cases: [] };
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      const payload = url.endsWith('/runs') ? [run]
        : url.endsWith('/runs/run-evaluated') ? packageValue
          : url.endsWith('/evaluations/run-evaluated') ? evaluation
            : url.endsWith('/findings') || url.endsWith('/risks') ? []
              : undefined;
      return Promise.resolve(payload === undefined
        ? new Response('not found', { status: 404 })
        : new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const { loadConsoleSnapshot } = await import('./client');

    const snapshot = await loadConsoleSnapshot();
    expect(snapshot?.evaluation).toMatchObject({ id: 'eval-bound', executionMode: 'LIVE', suggestedMapping: { state: 'SUGGESTED', reviewVersion: 0 } });
    expect(fetchMock.mock.calls.some(([input]) => String(input).endsWith('/evaluations/run-evaluated'))).toBe(true);
  });
});
