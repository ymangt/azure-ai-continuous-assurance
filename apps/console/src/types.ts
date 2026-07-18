export type ResultStatus = 'PASS' | 'FAIL' | 'ERROR' | 'NOT_RUN' | 'NOT_APPLICABLE';
export type Conclusion = 'EFFECTIVE' | 'PARTIALLY_EFFECTIVE' | 'INEFFECTIVE' | 'NOT_CONCLUDED';
export type Freshness = 'CURRENT' | 'STALE' | 'UNAVAILABLE';
export type Severity = 'CRITICAL' | 'HIGH' | 'MODERATE' | 'LOW';
export type RunState = 'COMPLETED' | 'REVIEW_REQUIRED' | 'RUNNING' | 'QUEUED' | 'FAILED';

export interface AssessmentRun {
  id: string;
  label: string;
  shortId: string;
  trigger: 'Scheduled' | 'Change-triggered' | 'Retest' | 'Fixture' | 'Manual';
  scope: string;
  observationWindow: string;
  gitCommit: string;
  collectorVersion: string;
  evaluatorVersion: string;
  startedAt: string;
  completedAt?: string;
  status: RunState;
  manifestDigest?: string;
  signed: boolean;
  signingKeyId?: string;
  keyFingerprint?: string;
  estimatedCostCad: number;
}

export interface ControlObjective {
  id: string;
  family: string;
  title: string;
  objective: string;
  method: 'Automated' | 'Hybrid' | 'Manual';
  result: ResultStatus;
  designEffectiveness: Conclusion;
  operatingEffectiveness: Conclusion;
  owner: string;
  freshness: Freshness;
  cadence: string;
  evidenceIds: string[];
  limitations: string;
  frameworkMappings: string[];
  assessorNote: string;
  reviewerConclusion?: Conclusion;
  reviewerRationale?: string;
  reviewer?: string;
  reviewVersion?: number;
  changed?: 'resolved' | 'regressed' | 'new' | 'unchanged' | 'stale' | 'errored';
}

export interface EvidenceItem {
  id: string;
  source: string;
  method: string;
  queryDigest: string;
  collectorVersion: string;
  capturedAt: string;
  resourceScope: string;
  sensitivity: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL';
  redaction: 'SANITIZED' | 'PRIVATE_ONLY' | 'NOT_REQUIRED';
  hash: string;
  blobVersion: string;
  freshness: Freshness;
  controlIds: string[];
  summary: string;
  mediaType: string;
}

export interface RetestEvent {
  runId: string;
  date: string;
  result: ResultStatus;
  evidenceIds: string[];
  decision: 'CLOSE' | 'REOPEN';
  rationale: string;
  evidenceFreshness: Freshness;
  reviewState: 'SUGGESTED' | 'ACCEPTED' | 'REJECTED';
}

export interface Finding {
  id: string;
  objectiveId?: string;
  title: string;
  status: 'OPEN' | 'READY_FOR_RETEST' | 'CLOSED' | 'REOPENED' | 'RISK_ACCEPTED';
  severity: Severity;
  criteria: string;
  condition: string;
  cause: string;
  consequence: string;
  severityRationale: string;
  controlIds: string[];
  asset: string;
  owner: string;
  openedAt: string;
  targetDate: string;
  treatment: 'MITIGATE' | 'ACCEPT' | 'AVOID' | 'TRANSFER';
  exception?: {
    expiresAt: string;
    approver: string;
    rationale: string;
    compensatingControl: string;
  };
  remediation: string;
  remediationReference?: string;
  remediationEvidenceIds: string[];
  remediationRecordedBy?: string;
  reviewVersion?: number;
  retests: RetestEvent[];
}

export interface Risk {
  id: string;
  statement: string;
  likelihood: number;
  impact: number;
  inherentScore: number;
  residualScore: number;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW';
  treatment: string;
  owner: string;
  findingId: string;
}

export interface EvaluationCase {
  id: string;
  category: 'Grounding' | 'Prompt injection' | 'Tool authorization' | 'Data handling' | 'Abstention';
  inputSha256: string;
  result: ResultStatus;
  baselineResult: ResultStatus;
  guardrail: 'ALLOWED' | 'BLOCKED' | 'ABSTAINED';
  response?: string;
  responseSha256?: string;
  retrievedDocuments: string[];
  toolCalls: string[];
  controlIds: string[];
  findingId?: string;
  correlationId?: string;
  latencyMs?: number;
}

export interface EvaluationSummary {
  id: string;
  model: string;
  executionMode?: 'LIVE' | 'REPLAY';
  promptVersion: string;
  datasetVersion: string;
  createdAt: string;
  total: number;
  passed: number;
  precision: number;
  recall: number;
  f1: number;
  citationValidity: number;
  abstentionQuality: number;
  reviewerRejectionRate: number;
  suggestedMapping?: {
    id: string;
    text: string;
    state: 'SUGGESTED' | 'ACCEPTED' | 'REJECTED';
    reviewVersion?: number;
  };
  cases: EvaluationCase[];
}

export interface RunDiff {
  fromRunId: string;
  toRunId: string;
  new: string[];
  resolved: string[];
  regressed: string[];
  stale: string[];
  errored: string[];
  unchanged: string[];
}

export interface SystemRecord {
  id: string;
  name: string;
  schemaVersion: string;
  boundary: string;
  dataClassification: string;
  dataFlows: Array<{ id: string; source: string; destination: string; data: string; classification: string; protection: string; retention: string }>;
  inventory: Array<{ name: string; type: string; plane: string; region: string; lifecycle: string }>;
  identities: Array<{ name: string; purpose: string; privilege: string; authentication: string; assignedScope: string }>;
  classifications: Array<{ classification: string; description: string; handling: string }>;
  trustBoundaries: string[];
  sharedResponsibility: string;
  exclusions: string[];
}

export interface ConsoleSnapshot {
  selectedRun: AssessmentRun;
  priorRun: AssessmentRun;
  comparisonAvailable: boolean;
  runs: AssessmentRun[];
  controls: ControlObjective[];
  evidence: EvidenceItem[];
  findings: Finding[];
  risks: Risk[];
  evaluation: EvaluationSummary;
  diff: RunDiff;
  system?: SystemRecord;
  generatedAt: string;
  sanitized: boolean;
}

export type AppView = 'overview' | 'controls' | 'evidence' | 'findings' | 'runs' | 'evaluations' | 'system';
export type DemoDataState = 'ready' | 'loading' | 'empty' | 'error' | 'stale';
