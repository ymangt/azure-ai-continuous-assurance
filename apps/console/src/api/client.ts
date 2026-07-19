import type {
  AssessmentRun,
  ConsoleSnapshot,
  ControlObjective,
  DemoDataState,
  EvidenceItem,
  EvaluationSummary,
  Finding,
  Risk,
  RunDiff,
  SystemRecord,
} from '../types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const LIVE_API = import.meta.env.VITE_DATA_SOURCE === 'api';
const DEV_REVIEWER = import.meta.env.DEV ? import.meta.env.VITE_DEV_REVIEWER_ID as string | undefined : undefined;
const DEV_ROLES = import.meta.env.DEV ? import.meta.env.VITE_DEV_ROLES as string | undefined : undefined;

export interface CommandReceipt {
  request_id: string;
  status: 'QUEUED' | 'RECORDED';
  version: number;
  received_at: string;
}

interface ApiCommand {
  id: string;
  status: string;
  expected_version: number | null;
  created_at: string;
}

export interface DecisionCommand {
  subject_type: 'control' | 'finding' | 'suggestion';
  subject_id: string;
  artifact_run_id: string;
  decision: string;
  rationale: string;
  expected_version: number;
  prior_state?: string;
}

export interface RemediationCommand {
  finding_id: string;
  artifact_run_id: string;
  owner: string;
  action: string;
  target_date: string;
  commit_or_pr: string;
  evidence_refs: string[];
  expected_version: number;
}

type JsonRecord = Record<string, unknown>;

export function object(value: unknown): JsonRecord {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonRecord : {};
}

export function records(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.map(object) : [];
}

export function stringValue(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

export function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

export function firstValue(record: JsonRecord, ...keys: string[]): unknown {
  for (const key of keys) if (record[key] !== undefined) return record[key];
  return undefined;
}

export function normalizeRun(rawValue: unknown): AssessmentRun {
  const raw = object(rawValue);
  const id = stringValue(firstValue(raw, 'id', 'run_id'));
  const rawStatus = stringValue(raw.status, 'FAILED').toUpperCase();
  const status: AssessmentRun['status'] = rawStatus === 'COMPLETE' || rawStatus === 'COMPLETED'
    ? 'COMPLETED'
    : rawStatus === 'REVIEW_REQUIRED' ? 'REVIEW_REQUIRED' : ['QUEUED'].includes(rawStatus) ? 'QUEUED' : ['COLLECTING', 'EVALUATING', 'RUNNING'].includes(rawStatus) ? 'RUNNING' : 'FAILED';
  const triggerValue = stringValue(raw.trigger, 'manual').toLowerCase();
  const trigger: AssessmentRun['trigger'] = triggerValue === 'scheduled' ? 'Scheduled' : triggerValue === 'retest' ? 'Retest' : triggerValue === 'fixture' ? 'Fixture' : triggerValue === 'change' || triggerValue === 'change-triggered' ? 'Change-triggered' : 'Manual';
  const scopeValue = raw.scope;
  const scopeObject = object(scopeValue);
  const scope = Array.isArray(scopeValue)
    ? scopeValue.map(String).join(', ')
    : Array.isArray(scopeObject.selectors) ? scopeObject.selectors.map(String).join(', ') : stringValue(scopeValue, 'Approved assessment scope');
  const observation = object(raw.observation_window);
  const observationStart = stringValue(firstValue(raw, 'observation_window_start'), stringValue(observation.start));
  const observationEnd = stringValue(firstValue(raw, 'observation_window_end'), stringValue(observation.end));
  const cost = object(raw.cost);
  const standardizedLabel = id.endsWith('0001') ? 'Legacy baseline' : id.endsWith('0002') ? 'Remediated retest' : undefined;

  return {
    id,
    shortId: stringValue(raw.display_id, id.slice(0, 8)),
    label: standardizedLabel ?? `${trigger} assessment`,
    trigger,
    scope,
    observationWindow: observationStart && observationEnd ? `${observationStart} – ${observationEnd}` : 'Observation window unavailable',
    gitCommit: stringValue(raw.git_commit, 'unknown'),
    collectorVersion: stringValue(raw.collector_version, 'unknown'),
    evaluatorVersion: stringValue(raw.evaluator_version, 'unknown'),
    startedAt: stringValue(raw.started_at, new Date(0).toISOString()),
    completedAt: stringValue(firstValue(raw, 'ended_at', 'completed_at')) || undefined,
    status,
    manifestDigest: stringValue(raw.manifest_digest) || undefined,
    signed: Boolean(raw.manifest_digest),
    signingKeyId: stringValue(raw.signing_key_id) || undefined,
    keyFingerprint: stringValue(raw.key_fingerprint) || undefined,
    estimatedCostCad: numberValue(firstValue(raw, 'estimated_cost_cad'), numberValue(cost.total_estimate)),
  };
}

function normalizeFreshness(value: unknown): ControlObjective['freshness'] {
  const freshness = stringValue(value).toUpperCase();
  return freshness === 'FRESH' || freshness === 'CURRENT' ? 'CURRENT' : freshness === 'STALE' ? 'STALE' : 'UNAVAILABLE';
}

function normalizeConclusion(value: unknown): ControlObjective['operatingEffectiveness'] {
  const conclusion = stringValue(value, 'NOT_CONCLUDED').toUpperCase();
  return ['EFFECTIVE', 'PARTIALLY_EFFECTIVE', 'INEFFECTIVE', 'NOT_CONCLUDED'].includes(conclusion)
    ? conclusion as ControlObjective['operatingEffectiveness']
    : 'NOT_CONCLUDED';
}

export function normalizeControls(packageValue: unknown): ControlObjective[] {
  const assessmentPackage = object(packageValue);
  const objectives = records(firstValue(assessmentPackage, 'objectives', 'control_objectives'));
  const results = records(firstValue(assessmentPackage, 'test_results', 'results'));
  const assessments = records(firstValue(assessmentPackage, 'assessments', 'control_assessments'));

  return objectives.map((objective) => {
    const id = stringValue(objective.id);
    const result = results.find((candidate) => stringValue(candidate.objective_id) === id) ?? {};
    const assessment = assessments.find((candidate) => stringValue(candidate.objective_id) === id) ?? {};
    const methods = Array.isArray(objective.methods) ? objective.methods.map((value) => String(value).toUpperCase()) : [];
    const crosswalk = object(objective.crosswalk);
    const frameworkMappings = Object.entries(crosswalk).flatMap(([framework, values]) => Array.isArray(values) ? values.map((value) => `${framework}: ${String(value)}`) : []);
    const sourceControl = stringValue(firstValue(objective, 'source_control', 'control_id'), id.split('.')[0]);
    return {
      id,
      family: sourceControl.startsWith('AI-') ? 'AI Governance' : sourceControl.split('-')[0] ?? 'Cross-family',
      title: stringValue(objective.title, sourceControl),
      objective: stringValue(objective.objective, stringValue(result.reason, 'Assessment objective metadata unavailable.')),
      method: Boolean(objective.automated) ? 'Automated' : methods.includes('HYBRID') ? 'Hybrid' : 'Manual',
      result: stringValue(result.status, 'NOT_RUN') as ControlObjective['result'],
      designEffectiveness: normalizeConclusion(assessment.design_effectiveness),
      operatingEffectiveness: normalizeConclusion(assessment.operating_effectiveness),
      owner: stringValue(objective.owner, 'Unassigned'),
      freshness: normalizeFreshness(firstValue(assessment, 'evidence_freshness', 'freshness')),
      cadence: stringValue(objective.cadence, 'Not declared'),
      evidenceIds: Array.isArray(result.evidence_refs) ? result.evidence_refs.map(String) : [],
      limitations: Array.isArray(objective.limitations) ? objective.limitations.map(String).join(' ') || 'No additional limitations declared.' : stringValue(objective.limitations, 'No additional limitations declared.'),
      frameworkMappings,
      assessorNote: stringValue(firstValue(assessment, 'rationale', 'assessor_conclusion'), stringValue(result.reason, 'No reviewer conclusion recorded.')),
      reviewerConclusion: assessment.reviewer_conclusion === undefined ? undefined : normalizeConclusion(assessment.reviewer_conclusion),
      reviewerRationale: stringValue(assessment.reviewer_rationale) || undefined,
      reviewer: stringValue(assessment.reviewer) || undefined,
      reviewVersion: typeof assessment.review_version === 'number' ? assessment.review_version : undefined,
    };
  });
}

export function normalizeEvidence(packageValue: unknown): EvidenceItem[] {
  const assessmentPackage = object(packageValue);
  const results = records(firstValue(assessmentPackage, 'test_results', 'results'));
  return records(assessmentPackage.evidence).map((raw) => {
    const id = stringValue(firstValue(raw, 'id', 'evidence_id'));
    const linkedObjectives = results.filter((result) => Array.isArray(result.evidence_refs) && result.evidence_refs.map(String).includes(id)).map((result) => stringValue(result.objective_id)).filter(Boolean);
    const scope = Array.isArray(raw.scope) ? raw.scope.map(String).join(', ') : stringValue(raw.scope, 'Approved scope');
    const classificationValue = stringValue(raw.classification, 'INTERNAL').toUpperCase();
    const classification: EvidenceItem['sensitivity'] = classificationValue === 'PUBLIC' ? 'PUBLIC' : classificationValue === 'INTERNAL' ? 'INTERNAL' : 'CONFIDENTIAL';
    const sanitizedHash = stringValue(raw.sanitized_sha256);
    const redactionProfile = stringValue(firstValue(raw, 'redaction_profile'), stringValue(object(raw.redaction).status));
    const payload = object(raw.payload);
    return {
      id,
      source: stringValue(raw.source, 'Unknown collector').replaceAll('_', ' '),
      method: stringValue(firstValue(raw, 'method', 'collection_method'), 'Method not provided by package'),
      queryDigest: stringValue(firstValue(raw, 'query_digest', 'api_query_digest'), 'Digest unavailable'),
      collectorVersion: stringValue(raw.collector_version, 'unknown'),
      capturedAt: stringValue(raw.captured_at, new Date(0).toISOString()),
      resourceScope: scope,
      sensitivity: classification,
      redaction: sanitizedHash || /applied|public/i.test(redactionProfile) ? 'SANITIZED' : classification === 'PUBLIC' ? 'NOT_REQUIRED' : 'PRIVATE_ONLY',
      hash: sanitizedHash || stringValue(raw.sha256, 'Hash unavailable'),
      blobVersion: stringValue(firstValue(raw, 'blob_version', 'blob_version_id'), 'Withheld'),
      freshness: normalizeFreshness(object(raw.freshness).state ?? raw.freshness),
      controlIds: [...new Set(linkedObjectives)],
      summary: stringValue(firstValue(raw, 'sanitized_summary', 'summary'), stringValue(payload.sanitized_summary, stringValue(raw.collection_error, 'Summary not provided by package.'))),
      mediaType: stringValue(raw.media_type, 'application/json'),
    };
  });
}

export function normalizeRisks(values: unknown): Risk[] {
  return records(values).map((raw) => {
    const confidenceValue = stringValue(raw.confidence, 'LOW').toUpperCase();
    return {
      id: stringValue(firstValue(raw, 'id', 'risk_id')),
      statement: stringValue(raw.statement, 'Risk statement unavailable.'),
      likelihood: numberValue(raw.likelihood, 1),
      impact: numberValue(raw.impact, 1),
      inherentScore: numberValue(raw.inherent_score, 1),
      residualScore: numberValue(raw.residual_score, 1),
      confidence: confidenceValue === 'HIGH' ? 'HIGH' : confidenceValue === 'MODERATE' || confidenceValue === 'MEDIUM' ? 'MEDIUM' : 'LOW',
      treatment: stringValue(raw.treatment, 'Not assigned').replaceAll('_', ' '),
      owner: stringValue(raw.owner, 'Unassigned'),
      findingId: stringValue(raw.finding_id, Array.isArray(raw.finding_refs) ? String(raw.finding_refs[0] ?? '') : ''),
    };
  });
}

function shortenFindingTitle(value: string): string {
  return value.length > 72 ? `${value.slice(0, 69).trimEnd()}…` : value;
}

function titleFromCriteria(raw: JsonRecord): string | undefined {
  const criteria = stringValue(raw.criteria).trim();
  const requiresMatch = criteria.match(/\brequires\s+(.+)$/i);
  if (!requiresMatch) return undefined;
  const phrase = requiresMatch[1].replace(/[.?!]+$/, '').trim();
  if (!phrase) return undefined;
  return shortenFindingTitle(phrase.charAt(0).toUpperCase() + phrase.slice(1));
}

function isWeakFindingTitle(title: string, id: string): boolean {
  if (!title || title === id) return true;
  const escapedId = id.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  // Package labels like "FND-001 — SC-7.1" are identifiers, not workpaper titles.
  if (new RegExp(`^${escapedId}\\s*[—\\-]\\s*\\S+$`, 'i').test(title)) return true;
  if (/^[A-Z]{1,3}-[A-Z0-9-]+\.\d+$/.test(title)) return true;
  return false;
}

function deriveFindingTitle(raw: JsonRecord, id: string): string {
  const explicit = stringValue(raw.title).trim();
  if (explicit && !isWeakFindingTitle(explicit, id)) return explicit;

  const fromCriteria = titleFromCriteria(raw);
  if (fromCriteria) return fromCriteria;

  const objectives = Array.isArray(raw.affected_objectives)
    ? raw.affected_objectives.map(String).filter(Boolean)
    : [];
  if (objectives[0]) return objectives[0];
  const objectiveId = stringValue(raw.objective_id).trim();
  if (objectiveId) return objectiveId;

  const condition = stringValue(raw.condition).trim();
  if (condition) {
    const firstClause = condition.split(/[.;]/)[0]?.trim() ?? condition;
    return shortenFindingTitle(firstClause);
  }

  return explicit || id;
}

export function normalizeFindings(values: unknown, packageValue: unknown, run: AssessmentRun, risks: Risk[]): Finding[] {
  const assessmentPackage = object(packageValue);
  const remediations = records(assessmentPackage.remediations);
  const retests = records(assessmentPackage.retests);
  const exceptions = records(assessmentPackage.exceptions);
  return records(values).map((raw) => {
    const id = stringValue(firstValue(raw, 'id', 'finding_id'));
    const remediation = remediations.filter((item) => stringValue(firstValue(item, 'finding_id', 'finding_ref')) === id).at(-1);
    const risk = risks.find((item) => item.findingId === id);
    const exception = exceptions.find((item) => stringValue(item.finding_id) === id);
    const statusValue = stringValue(raw.status, 'OPEN').toUpperCase();
    const status: Finding['status'] = statusValue === 'CLOSED' ? 'CLOSED' : statusValue === 'READY_FOR_RETEST' ? 'READY_FOR_RETEST' : statusValue === 'REOPENED' ? 'REOPENED' : statusValue === 'RISK_ACCEPTED' ? 'RISK_ACCEPTED' : 'OPEN';
    const matchingRetests = retests.filter((item) => stringValue(firstValue(item, 'finding_id', 'finding_ref')) === id);
    const targetDate = stringValue(remediation?.target_date, run.completedAt?.slice(0, 10) ?? run.startedAt.slice(0, 10));
    return {
      id,
      objectiveId: stringValue(raw.objective_id) || undefined,
      title: deriveFindingTitle(raw, id),
      status,
      severity: stringValue(raw.severity, 'LOW') as Finding['severity'],
      criteria: stringValue(raw.criteria, 'Criteria unavailable.'),
      condition: stringValue(raw.condition, 'Condition unavailable.'),
      cause: stringValue(raw.cause, 'Cause unavailable.'),
      consequence: stringValue(raw.consequence, 'Consequence unavailable.'),
      severityRationale: stringValue(raw.severity_rationale, 'Severity rationale unavailable.'),
      controlIds: Array.isArray(raw.affected_controls) ? raw.affected_controls.map(String) : [],
      asset: Array.isArray(raw.affected_assets) ? raw.affected_assets.map(String).join(', ') : 'Assessed system',
      owner: stringValue(remediation?.owner, risk?.owner ?? 'Unassigned'),
      openedAt: run.startedAt.slice(0, 10),
      targetDate: targetDate.slice(0, 10),
      treatment: (risk?.treatment.split(' ')[0] ?? 'MITIGATE') as Finding['treatment'],
      exception: exception ? {
        expiresAt: stringValue(exception.expires_at).slice(0, 10),
        approver: stringValue(exception.approver, 'Pending'),
        rationale: stringValue(exception.rationale, 'No rationale recorded.'),
        compensatingControl: Array.isArray(exception.compensating_controls) ? exception.compensating_controls.map(String).join('; ') : 'Not recorded',
      } : undefined,
      remediation: stringValue(remediation?.action, 'No remediation action recorded.'),
      remediationReference: stringValue(firstValue(remediation ?? {}, 'commit_or_pr', 'commit_ref', 'pull_request_ref')) || undefined,
      remediationEvidenceIds: Array.isArray(remediation?.evidence_refs) ? remediation.evidence_refs.map(String) : [],
      remediationRecordedBy: stringValue(remediation?.recorded_by) || undefined,
      reviewVersion: typeof raw.review_version === 'number' ? raw.review_version : undefined,
      retests: matchingRetests.map((item) => ({
        runId: stringValue(firstValue(item, 'after_run_id'), run.id),
        date: stringValue(firstValue(item, 'tested_at'), run.completedAt ?? run.startedAt).slice(0, 10),
        result: stringValue(item.result, 'NOT_RUN') as Finding['retests'][number]['result'],
        evidenceIds: Array.isArray(firstValue(item, 'evidence_refs', 'new_evidence_refs')) ? (firstValue(item, 'evidence_refs', 'new_evidence_refs') as unknown[]).map(String) : [],
        decision: stringValue(item.decision, 'REOPEN').toUpperCase() === 'CLOSE' ? 'CLOSE' : 'REOPEN',
        rationale: stringValue(item.rationale, 'No retest rationale recorded.'),
        evidenceFreshness: normalizeFreshness(item.evidence_freshness),
        reviewState: ['ACCEPTED', 'REJECTED'].includes(stringValue(item.review_state).toUpperCase())
          ? stringValue(item.review_state).toUpperCase() as 'ACCEPTED' | 'REJECTED'
          : 'SUGGESTED',
      })),
    };
  });
}

export function normalizeDiff(value: unknown, fromRunId: string, toRunId: string): RunDiff {
  const raw = object(value);
  const grouped: RunDiff = {
    fromRunId: stringValue(firstValue(raw, 'fromRunId', 'from_run_id'), fromRunId),
    toRunId: stringValue(firstValue(raw, 'toRunId', 'to_run_id'), toRunId),
    new: [], resolved: [], regressed: [], stale: [], errored: [], unchanged: [],
  };
  const directCategories = ['new', 'resolved', 'regressed', 'stale', 'errored', 'unchanged'] as const;
  let foundDirectCategory = false;
  for (const category of directCategories) {
    if (!Array.isArray(raw[category])) continue;
    foundDirectCategory = true;
    grouped[category] = (raw[category] as unknown[])
      .map((item) => typeof item === 'string' ? item : stringValue(object(item).objective_id))
      .filter(Boolean);
  }
  if (foundDirectCategory) return grouped;
  for (const change of records(raw.changes)) {
    const id = stringValue(change.objective_id);
    const category = stringValue(change.category);
    if (category === 'new') grouped.new.push(id);
    else if (category === 'resolved') grouped.resolved.push(id);
    else if (category === 'regressed') grouped.regressed.push(id);
    else if (category === 'stale_or_not_run') grouped.stale.push(id);
    else if (category === 'errored') grouped.errored.push(id);
    else grouped.unchanged.push(id);
  }
  return grouped;
}

export function unavailableEvaluation(id: string): EvaluationSummary {
  return {
    id,
    model: 'Evaluation artifact unavailable',
    promptVersion: 'Unavailable',
    datasetVersion: 'Unavailable',
    createdAt: new Date(0).toISOString(),
    total: 0,
    passed: 0,
    precision: 0,
    recall: 0,
    f1: 0,
    citationValidity: 0,
    abstentionQuality: 0,
    reviewerRejectionRate: 0,
    cases: [],
  };
}

function normalizeEvaluation(value: unknown, id: string): EvaluationSummary {
  const raw = object(value);
  return typeof raw.total === 'number' && Array.isArray(raw.cases)
    ? raw as unknown as EvaluationSummary
    : unavailableEvaluation(id);
}

export function normalizeSystem(value: unknown): SystemRecord | undefined {
  const raw = object(value);
  const dataFlows = records(firstValue(raw, 'data_flows', 'dataFlows')).map((flow) => ({
    id: stringValue(flow.id),
    source: stringValue(flow.source),
    destination: stringValue(flow.destination),
    data: stringValue(flow.data),
    classification: stringValue(flow.classification),
    protection: stringValue(flow.protection),
    retention: stringValue(flow.retention),
  }));
  const inventory = records(raw.inventory).map((item) => ({
    name: stringValue(item.name),
    type: stringValue(item.type),
    plane: stringValue(item.plane),
    region: stringValue(item.region),
    lifecycle: stringValue(item.lifecycle),
  }));
  const identities = records(raw.identities).map((identity) => ({
    name: stringValue(identity.name),
    purpose: stringValue(identity.purpose),
    privilege: stringValue(identity.privilege),
    authentication: stringValue(identity.authentication),
    assignedScope: stringValue(firstValue(identity, 'assigned_scope', 'assignedScope')),
  }));
  const classifications = records(raw.classifications).map((classification) => ({
    classification: stringValue(classification.classification),
    description: stringValue(classification.description),
    handling: stringValue(classification.handling),
  }));
  const trustBoundaries = firstValue(raw, 'trust_boundaries', 'trustBoundaries');
  const exclusions = raw.exclusions;
  if (
    !stringValue(raw.boundary)
    || !dataFlows.length
    || !inventory.length
    || !identities.length
    || !classifications.length
    || !Array.isArray(trustBoundaries)
    || !Array.isArray(exclusions)
  ) return undefined;
  return {
    id: stringValue(firstValue(raw, 'system_id', 'id')),
    name: stringValue(raw.name),
    schemaVersion: stringValue(firstValue(raw, 'schema_version', 'schemaVersion')),
    boundary: stringValue(raw.boundary),
    dataClassification: stringValue(firstValue(raw, 'data_classification', 'dataClassification')),
    dataFlows,
    inventory,
    identities,
    classifications,
    trustBoundaries: trustBoundaries.map(String),
    sharedResponsibility: stringValue(firstValue(raw, 'shared_responsibility', 'sharedResponsibility')),
    exclusions: exclusions.map(String),
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 15_000);

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'same-origin',
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...(DEV_REVIEWER ? { 'X-AICA-Reviewer': DEV_REVIEWER } : {}),
        ...(DEV_ROLES ? { 'X-AICA-Roles': DEV_ROLES } : {}),
        ...init?.headers,
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      const body = await response.text();
      throw new Error(`Assurance API ${response.status}: ${body || response.statusText}`);
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('The assurance API did not respond within 15 seconds.');
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function loadFromApi(): Promise<ConsoleSnapshot | null> {
  const runsPayload = await request<unknown[]>('/runs');
  const rawRuns = Array.isArray(runsPayload) ? runsPayload.map(object) : [];
  const runs = rawRuns.map(normalizeRun);
  if (!runs.length) return null;
  const selectedRun = runs[0];
  const selectedRaw = rawRuns.find((run) => stringValue(firstValue(run, 'id', 'run_id')) === selectedRun.id) ?? {};
  const priorId = stringValue(selectedRaw.prior_run_id);
  const distinctPrior = runs.find((run) => run.id === priorId) ?? runs.find((run) => run.id !== selectedRun.id);
  const priorRun = distinctPrior ?? selectedRun;
  const comparisonAvailable = priorRun.id !== selectedRun.id;

  const [selectedPackage, findingsPayload, risksPayload, evaluationPayload, diffPayload] = await Promise.all([
    request<unknown>(`/runs/${selectedRun.id}`),
    request<unknown>('/findings'),
    request<unknown>('/risks'),
    request<EvaluationSummary>(`/evaluations/${selectedRun.id}`).catch(() => undefined),
    comparisonAvailable
      ? request<unknown>(`/diffs?from=${encodeURIComponent(priorRun.id)}&to=${encodeURIComponent(selectedRun.id)}`)
      : Promise.resolve(undefined),
  ]);
  const risks = normalizeRisks(risksPayload);
  const diff = normalizeDiff(diffPayload, priorRun.id, selectedRun.id);
  const controls = normalizeControls(selectedPackage).map((control) => ({
    ...control,
    changed: diff.resolved.includes(control.id) ? 'resolved' as const
      : diff.regressed.includes(control.id) ? 'regressed' as const
        : diff.new.includes(control.id) ? 'new' as const
          : diff.stale.includes(control.id) ? 'stale' as const
            : diff.errored.includes(control.id) ? 'errored' as const : 'unchanged' as const,
  }));

  return {
    selectedRun,
    priorRun,
    comparisonAvailable,
    runs,
    controls,
    evidence: normalizeEvidence(selectedPackage),
    findings: normalizeFindings(findingsPayload, selectedPackage, selectedRun, risks),
    risks,
    evaluation: normalizeEvaluation(evaluationPayload, `run:${selectedRun.id}`),
    diff,
    system: normalizeSystem(firstValue(object(selectedPackage), 'system', 'system_record')),
    generatedAt: selectedRun.completedAt ?? selectedRun.startedAt,
    sanitized: false,
  };
}

function applyDemoState(snapshot: ConsoleSnapshot, state: DemoDataState): ConsoleSnapshot {
  if (state === 'empty') {
    return { ...snapshot, controls: [], evidence: [], findings: [], risks: [], runs: [], evaluation: { ...snapshot.evaluation, cases: [], total: 0, passed: 0 } };
  }
  if (state === 'stale') {
    return {
      ...snapshot,
      generatedAt: '2026-05-01T09:00:00Z',
      controls: snapshot.controls.map((control) => ({ ...control, freshness: control.freshness === 'UNAVAILABLE' ? 'UNAVAILABLE' : 'STALE' })),
      evidence: snapshot.evidence.map((item) => ({ ...item, freshness: 'STALE' })),
    };
  }
  return snapshot;
}

export async function loadConsoleSnapshot(state: DemoDataState = 'ready'): Promise<ConsoleSnapshot | null> {
  if (state === 'loading') return new Promise(() => undefined);
  await new Promise((resolve) => window.setTimeout(resolve, import.meta.env.MODE === 'test' ? 0 : 280));
  if (state === 'error') throw new Error('Evidence snapshot unavailable. The last signed artifact was not replaced.');
  const snapshot = LIVE_API
    ? await loadFromApi()
    : (await import('../mockData')).cloneSnapshot();
  return snapshot ? applyDemoState(snapshot, state) : null;
}

async function postCommand<T extends object>(path: string, body: T, recorded: boolean): Promise<CommandReceipt> {
  if (LIVE_API) {
    const command = await request<ApiCommand>(path, { method: 'POST', body: JSON.stringify(body) });
    return {
      request_id: command.id,
      status: command.status === 'QUEUED' ? 'QUEUED' : recorded ? 'RECORDED' : 'QUEUED',
      version: (command.expected_version ?? 0) + 1,
      received_at: command.created_at,
    };
  }
  await new Promise((resolve) => window.setTimeout(resolve, 420));
  return {
    request_id: crypto.randomUUID(),
    status: recorded ? 'RECORDED' : 'QUEUED',
    version: Number('expected_version' in body ? body.expected_version : 1) + 1,
    received_at: new Date().toISOString(),
  };
}

export const assuranceApi = {
  queueRun: (scope: string) => postCommand('/run-requests', {
    profile: scope === 'full-approved-scope' ? 'azure-dev' : scope,
    reason: `Manual assessment requested for ${scope.replaceAll('-', ' ')}.`,
  }, false),
  queueRetest: (findingId: string, priorRunId: string) => postCommand('/retest-requests', {
    prior_run_id: priorRunId,
    finding_ids: [findingId],
    reason: `Collect new evidence and retest ${findingId}.`,
  }, false),
  recordDecision: (command: DecisionCommand) => postCommand('/review-decisions', {
    subject_type: command.subject_type === 'suggestion' ? 'AI_SUGGESTION' : command.subject_type.toUpperCase(),
    subject_id: command.subject_id,
    artifact_run_id: command.artifact_run_id,
    prior_state: command.prior_state ?? 'CURRENT',
    decision: command.decision,
    rationale: command.rationale,
    expected_version: command.expected_version,
  }, true),
  createException: (body: { finding_id: string; artifact_run_id: string; rationale: string; compensating_control: string; expires_at: string; expected_version: number }) => postCommand('/exceptions', {
    finding_id: body.finding_id,
    artifact_run_id: body.artifact_run_id,
    rationale: body.rationale,
    compensating_controls: [body.compensating_control],
    expires_at: body.expires_at,
    review_cadence: 'monthly',
    expected_version: body.expected_version,
  }, true),
  createRemediation: (body: RemediationCommand) => postCommand('/remediations', body, true),
};
