import {
  baselineManifest,
  baselinePackage,
  remediatedManifest,
  remediatedPackage,
  sampleDiff,
} from 'virtual:aica-sample-artifacts';
import {
  normalizeControls,
  normalizeDiff,
  normalizeEvidence,
  normalizeFindings,
  normalizeRisks,
  normalizeRun,
  normalizeSystem,
} from './api/client';
import type {
  AssessmentRun,
  ConsoleSnapshot,
  ControlObjective,
  EvaluationCase,
  EvaluationSummary,
  ResultStatus,
  RunDiff,
} from './types';

type JsonRecord = Record<string, unknown>;

function record(value: unknown): JsonRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonRecord
    : {};
}

function rows(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function number(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function manifestRun(rawPackage: unknown, rawManifest: unknown): AssessmentRun {
  const packageRecord = record(rawPackage);
  const signed = record(rawManifest);
  const manifest = record(signed.manifest);
  const run = normalizeRun(packageRecord.run);
  const manifestDigest = text(signed.manifest_sha256);
  const signingKeyId = text(signed.key_id);
  const keyFingerprint = text(signed.key_fingerprint);

  return {
    ...run,
    shortId: `${run.id.slice(0, 8)}…${run.id.slice(-4)}`,
    manifestDigest: manifestDigest || undefined,
    signed: Boolean(manifestDigest && signingKeyId && signed.signature),
    signingKeyId: signingKeyId || undefined,
    keyFingerprint: keyFingerprint || undefined,
    estimatedCostCad: number(manifest.cost_estimate_cad, run.estimatedCostCad),
  };
}

export const baselineRun = manifestRun(baselinePackage, baselineManifest);
export const remediatedRun = manifestRun(remediatedPackage, remediatedManifest);

const normalizedDiff = normalizeDiff(sampleDiff, baselineRun.id, remediatedRun.id);
const baselineResults = new Map(
  rows(record(baselinePackage).test_results).map((result) => [
    text(result.objective_id),
    text(result.status),
  ]),
);
const remediatedResults = rows(record(remediatedPackage).test_results);
const resolvedObjectives = new Set(normalizedDiff.resolved);
const unavailableCategories = new Set(['NOT_APPLICABLE']);

export const diff: RunDiff = {
  ...normalizedDiff,
  unchanged: remediatedResults
    .filter((result) => {
      const id = text(result.objective_id);
      const status = text(result.status);
      return !resolvedObjectives.has(id)
        && !unavailableCategories.has(status)
        && baselineResults.get(id) === status;
    })
    .map((result) => text(result.objective_id)),
};

function changeForObjective(id: string): ControlObjective['changed'] {
  if (diff.resolved.includes(id)) return 'resolved';
  if (diff.regressed.includes(id)) return 'regressed';
  if (diff.new.includes(id)) return 'new';
  if (diff.stale.includes(id)) return 'stale';
  if (diff.errored.includes(id)) return 'errored';
  return 'unchanged';
}

export const controls = normalizeControls(remediatedPackage).map((control) => ({
  ...control,
  changed: changeForObjective(control.id),
}));
export const evidence = normalizeEvidence(remediatedPackage);
export const risks = normalizeRisks(record(remediatedPackage).risks);
const baselineFindingIds = new Set(rows(record(baselinePackage).findings).map((finding) => text(finding.id)));
export const findings = normalizeFindings(
  record(remediatedPackage).findings,
  remediatedPackage,
  remediatedRun,
  risks,
).map((finding) => ({
  ...finding,
  openedAt: baselineFindingIds.has(finding.id)
    ? baselineRun.startedAt.slice(0, 10)
    : remediatedRun.startedAt.slice(0, 10),
}));

const categoryLabels: Record<string, EvaluationCase['category']> = {
  grounded_answer: 'Grounding',
  citation_integrity: 'Grounding',
  service_fault: 'Grounding',
  indirect_prompt_injection: 'Prompt injection',
  direct_prompt_injection: 'Prompt injection',
  content_filter: 'Prompt injection',
  release_gate: 'Tool authorization',
  tool_authorization: 'Tool authorization',
  rate_limit: 'Tool authorization',
  sensitive_data: 'Data handling',
  telemetry_contract: 'Data handling',
  scope_control: 'Abstention',
  policy_conflict: 'Abstention',
  stale_policy: 'Abstention',
};

function resultStatus(value: unknown): ResultStatus {
  return value === true ? 'PASS' : 'FAIL';
}

function recordedStatus(value: unknown, fallback: ResultStatus = 'NOT_RUN'): ResultStatus {
  return value === 'PASS'
    || value === 'FAIL'
    || value === 'ERROR'
    || value === 'NOT_RUN'
    || value === 'NOT_APPLICABLE'
    ? value
    : fallback;
}

function guardrail(disposition: string): EvaluationCase['guardrail'] {
  if (disposition === 'REFUSE' || disposition === 'REQUEST_CONFIRMATION' || disposition === 'WARN_AND_ANSWER') return 'BLOCKED';
  if (disposition === 'CLARIFY') return 'ABSTAINED';
  return 'ALLOWED';
}

const objectiveIds = new Set(controls.map((control) => control.id));

function objectiveReference(controlId: string): string {
  if (objectiveIds.has(controlId)) return controlId;
  const firstObjective = `${controlId}.1`;
  return objectiveIds.has(firstObjective) ? firstObjective : controlId;
}

const evaluationEvidence = rows(record(remediatedPackage).evidence).filter((item) => (
  text(item.source).toLowerCase().replaceAll(/[^a-z0-9]/g, '') === 'aibehavioralevaluation'
));

if (evaluationEvidence.length !== 1) {
  throw new Error('The signed remediated package must contain exactly one AI behavioral evaluation.');
}

const signedEvaluation = record(evaluationEvidence[0].payload);
const signedAdapter = record(signedEvaluation.adapter);
const signedSummary = record(signedEvaluation.summary);
const signedMappingMetrics = record(signedEvaluation.mapping_metrics);
const signedNodes = rows(signedEvaluation.nodes);

const evaluationCases: EvaluationCase[] = signedNodes.map((node) => {
  const disposition = text(node.disposition, 'UNKNOWN');
  const category = text(node.category);
  const observedTools = rows(node.tool_calls);
  const latency = node.latency_ms;
  return {
    id: text(node.id),
    category: categoryLabels[category] ?? 'Grounding',
    inputSha256: text(node.prompt_sha256),
    result: resultStatus(node.passed),
    baselineResult: recordedStatus(node.baseline_result),
    guardrail: guardrail(disposition),
    responseSha256: text(node.response_sha256) || undefined,
    retrievedDocuments: Array.isArray(node.retrieved_documents)
      ? node.retrieved_documents.map(String)
      : [],
    toolCalls: observedTools.map((tool) => text(tool.name)).filter(Boolean),
    controlIds: Array.isArray(node.control_ids)
      ? node.control_ids.map((control) => objectiveReference(String(control)))
      : [],
    correlationId: text(node.correlation_id) || undefined,
    latencyMs: typeof latency === 'number' && Number.isFinite(latency) ? latency : undefined,
  };
});

function signedSuggestion(): EvaluationSummary['suggestedMapping'] {
  const suggestion = record(signedEvaluation.suggested_mapping);
  const id = text(suggestion.id);
  if (!id) return undefined;
  if (
    text(suggestion.artifact_run_id) !== remediatedRun.id
    || text(suggestion.evaluation_id) !== text(signedEvaluation.evaluation_id)
  ) {
    throw new Error('The signed AI mapping suggestion is not bound to this assessment run.');
  }

  let state = text(suggestion.state, 'SUGGESTED');
  let reviewVersion = number(suggestion.review_version);
  const decisions = rows(record(remediatedPackage).decisions)
    .filter((decision) => text(decision.subject_type) === 'AI_SUGGESTION' && text(decision.subject_id) === id)
    .sort((left, right) => number(left.version) - number(right.version));
  const latest = decisions.at(-1);
  if (latest) {
    const decision = text(latest.decision).toUpperCase();
    if (decision === 'ACCEPT' || decision === 'ACCEPTED') state = 'ACCEPTED';
    if (decision === 'REJECT' || decision === 'REJECTED') state = 'REJECTED';
    reviewVersion = number(latest.version, reviewVersion);
  }
  if (state !== 'SUGGESTED' && state !== 'ACCEPTED' && state !== 'REJECTED') {
    throw new Error('The signed AI mapping suggestion has an invalid review state.');
  }
  return {
    id,
    text: text(suggestion.text),
    state,
    reviewVersion,
  };
}

const executionMode = text(signedEvaluation.evaluation_mode);
if (executionMode !== 'LIVE' && executionMode !== 'REPLAY') {
  throw new Error('The signed AI evaluation has an invalid execution mode.');
}

export const evaluation: EvaluationSummary = {
  id: text(signedEvaluation.evaluation_id, 'Evaluation ID not provided'),
  model: text(signedAdapter.name, 'Adapter not provided'),
  executionMode,
  promptVersion: `sha256:${text(signedEvaluation.configuration_sha256, 'not provided')}`,
  datasetVersion: text(signedEvaluation.dataset_version, 'Dataset version not provided'),
  createdAt: text(signedEvaluation.evaluated_at, remediatedRun.completedAt ?? remediatedRun.startedAt),
  total: number(signedSummary.cases),
  passed: number(signedSummary.passed),
  precision: number(signedMappingMetrics.precision),
  recall: number(signedMappingMetrics.recall),
  f1: number(signedMappingMetrics.f1),
  citationValidity: number(signedMappingMetrics.citation_validity),
  abstentionQuality: number(signedMappingMetrics.abstention_f1),
  reviewerRejectionRate: number(signedMappingMetrics.reviewer_rejection_rate),
  suggestedMapping: signedSuggestion(),
  cases: evaluationCases,
};

const generatedAt = text(record(record(remediatedManifest).manifest).generated_at, remediatedRun.completedAt ?? remediatedRun.startedAt);

export const publicSampleSnapshot: ConsoleSnapshot = {
  selectedRun: remediatedRun,
  priorRun: baselineRun,
  comparisonAvailable: true,
  runs: [remediatedRun, baselineRun],
  controls,
  evidence,
  findings,
  risks,
  evaluation,
  diff,
  system: normalizeSystem(record(remediatedPackage).system),
  generatedAt,
  sanitized: true,
};

export function cloneSnapshot(): ConsoleSnapshot {
  return structuredClone(publicSampleSnapshot);
}
