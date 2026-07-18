import { loadConsoleSnapshot } from './client';
import { remediatedPackage } from 'virtual:aica-sample-artifacts';

describe('console snapshot states', () => {
  it('keeps freshness separate and marks every available artifact stale', async () => {
    const snapshot = await loadConsoleSnapshot('stale');
    if (!snapshot) throw new Error('expected the checked-in stale snapshot');
    expect(snapshot.evidence).not.toHaveLength(0);
    expect(snapshot.evidence.every((item) => item.freshness === 'STALE')).toBe(true);
    expect(snapshot.controls.every((control) => control.freshness === 'STALE')).toBe(true);
  });

  it('derives the public snapshot from the two checked-in local-signed artifacts', async () => {
    const snapshot = await loadConsoleSnapshot();
    if (!snapshot) throw new Error('expected the checked-in public snapshot');
    expect(snapshot.priorRun.id).toBe('018f6d9a-7b10-7c01-8000-000000000001');
    expect(snapshot.selectedRun.id).toBe('018f6d9a-7b10-7c01-8000-000000000002');
    expect(snapshot.runs).toHaveLength(2);
    expect(snapshot.priorRun).toMatchObject({
      signingKeyId: 'local://aica-public-sample-signing.pem',
      signed: true,
    });
    expect(snapshot.priorRun.manifestDigest).toMatch(/^[a-f0-9]{64}$/);
    expect(snapshot.selectedRun).toMatchObject({
      signingKeyId: 'local://aica-public-sample-signing.pem',
      signed: true,
    });
    expect(snapshot.selectedRun.manifestDigest).toMatch(/^[a-f0-9]{64}$/);
    expect(snapshot.controls).toHaveLength(35);
    expect(snapshot.controls.some((control) => control.id === 'AI-DP-01.1')).toBe(true);
    expect(snapshot.controls.some((control) => control.id === 'AI-DP-01.2')).toBe(false);
    expect(snapshot.evaluation).toMatchObject({ model: 'ReplayModelAdapter', total: 50, passed: 50 });
    expect(snapshot.evaluation.cases.every((testCase) => testCase.response === undefined)).toBe(true);
    expect(snapshot.evaluation.cases.every((testCase) => /^[a-f0-9]{64}$/.test(testCase.inputSha256))).toBe(true);
    expect(snapshot.evaluation.cases.some((testCase) => testCase.correlationId?.startsWith('corr-'))).toBe(true);
    expect(snapshot.evaluation.cases).toHaveLength(50);
    expect(snapshot.system).toMatchObject({
      id: 'aica-student-assurance',
      schemaVersion: '1.0.0',
      name: 'Azure AI Continuous Assurance',
    });
    expect(snapshot.system?.dataFlows).toHaveLength(7);
    expect(snapshot.system?.inventory.length).toBeGreaterThanOrEqual(9);
    expect(snapshot.system?.classifications.map((item) => item.classification)).toEqual([
      'PUBLIC',
      'INTERNAL',
      'CONFIDENTIAL',
      'RESTRICTED_TEST_EVIDENCE',
    ]);
    expect(snapshot.system?.exclusions.length).toBeGreaterThanOrEqual(6);
  });

  it('projects public evaluation facts from the manifest-covered evidence payload', async () => {
    const snapshot = await loadConsoleSnapshot();
    if (!snapshot) throw new Error('expected the checked-in public snapshot');
    const signedPackage = remediatedPackage as {
      evidence: Array<{ source: string; payload: Record<string, unknown> }>;
    };
    const payload = signedPackage.evidence.find(
      (item) => item.source === 'AI_BEHAVIORAL_EVALUATION',
    )?.payload;
    if (!payload) throw new Error('expected signed AI evaluation evidence');
    const adapter = payload.adapter as Record<string, unknown>;
    const summary = payload.summary as Record<string, unknown>;
    const metrics = payload.mapping_metrics as Record<string, unknown>;
    const suggestion = payload.suggested_mapping as Record<string, unknown>;
    const nodes = payload.nodes as Array<Record<string, unknown>>;

    expect(snapshot.evaluation).toMatchObject({
      id: payload.evaluation_id,
      model: adapter.name,
      executionMode: payload.evaluation_mode,
      promptVersion: `sha256:${String(payload.configuration_sha256)}`,
      datasetVersion: payload.dataset_version,
      createdAt: payload.evaluated_at,
      total: summary.cases,
      passed: summary.passed,
      precision: metrics.precision,
      recall: metrics.recall,
      f1: metrics.f1,
      citationValidity: metrics.citation_validity,
      abstentionQuality: metrics.abstention_f1,
      reviewerRejectionRate: metrics.reviewer_rejection_rate,
      suggestedMapping: {
        id: suggestion.id,
        text: suggestion.text,
        state: suggestion.state,
        reviewVersion: suggestion.review_version,
      },
    });
    expect(snapshot.evaluation.cases).toHaveLength(nodes.length);
    const signedCase = nodes.find((item) => item.id === 'BEH-001');
    const publicCase = snapshot.evaluation.cases.find((item) => item.id === 'BEH-001');
    expect(publicCase).toMatchObject({
      inputSha256: signedCase?.prompt_sha256,
      responseSha256: signedCase?.response_sha256,
      baselineResult: signedCase?.baseline_result,
      correlationId: signedCase?.correlation_id,
      latencyMs: signedCase?.latency_ms,
    });
  });
});
