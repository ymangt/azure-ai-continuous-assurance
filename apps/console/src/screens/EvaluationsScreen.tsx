import { useMemo, useState } from 'react';
import { Button, Field, Select, Text, Textarea } from '@fluentui/react-components';
import { BrainCircuit20Regular, Checkmark20Regular, Dismiss20Regular, DocumentData20Regular } from '@fluentui/react-icons';
import { assuranceApi } from '../api/client';
import { formatDateTime, percent } from '../format';
import type { AppView, ConsoleSnapshot, EvaluationCase } from '../types';
import { ActionDialog } from '../components/ActionDialog';
import { DetailPanel } from '../components/DetailPanel';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';
import { SectionCard } from '../components/SectionCard';
import { StatusBadge } from '../components/StatusBadge';

interface EvaluationsScreenProps {
  data: ConsoleSnapshot;
  publicMode: boolean;
  onNavigate: (view: AppView, id?: string) => void;
  onCommand: (message: string) => void;
}

export function EvaluationsScreen({ data, publicMode, onNavigate, onCommand }: EvaluationsScreenProps) {
  const evaluation = data.evaluation;
  const [category, setCategory] = useState('ALL');
  const [result, setResult] = useState('ALL');
  const [selected, setSelected] = useState<EvaluationCase>();
  const [decision, setDecision] = useState<'ACCEPTED' | 'REJECTED'>();
  const [rationale, setRationale] = useState('');
  const [pending, setPending] = useState(false);

  const categories = [...new Set(evaluation.cases.map((testCase) => testCase.category))];
  const filtered = useMemo(() => evaluation.cases.filter((testCase) => (category === 'ALL' || testCase.category === category) && (result === 'ALL' || testCase.result === result)), [category, evaluation.cases, result]);

  const recordSuggestionDecision = async () => {
    if (!decision || !evaluation.suggestedMapping || rationale.trim().length < 12) return;
    setPending(true);
    try {
      const receipt = await assuranceApi.recordDecision({ subject_type: 'suggestion', subject_id: evaluation.suggestedMapping.id, artifact_run_id: data.selectedRun.id, decision, rationale: rationale.trim(), expected_version: evaluation.suggestedMapping.reviewVersion ?? 0 });
      onCommand(`AI suggestion decision accepted as command ${receipt.request_id.slice(0, 8)} (${decision.toLowerCase()}). The model did not make the control decision.`);
      setDecision(undefined);
      setRationale('');
    } catch (error) {
      onCommand(error instanceof Error ? `Reviewer decision failed: ${error.message}` : 'The AI suggestion decision could not be recorded.');
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="screen-stack">
      <PageHeader eyebrow="Behavioral assurance" title="AI evaluations" description="Controlled evaluation evidence bound to the selected signed assessment package." />

      <div className="evaluation-meta">
        <div><Text size={200}>Evaluation</Text><strong>{evaluation.id}</strong></div><div><Text size={200}>Model</Text><strong>{evaluation.model}</strong></div><div><Text size={200}>Prompt</Text><strong>{evaluation.promptVersion}</strong></div><div><Text size={200}>Dataset</Text><strong>{evaluation.datasetVersion}</strong></div><div><Text size={200}>Completed</Text><strong>{formatDateTime(evaluation.createdAt)}</strong></div>
      </div>

      <section className="metric-grid evaluation-metrics" aria-label="Evaluation metrics">
        <MetricCard label="Behavioral pass rate" value={`${evaluation.passed}/${evaluation.total}`} detail={`${percent(evaluation.passed / Math.max(evaluation.total, 1), 1)} ${evaluation.executionMode === 'LIVE' ? 'live selected-model run' : 'deterministic replay'}`} tone={evaluation.passed === evaluation.total ? 'good' : 'warning'} />
        <MetricCard label="Mapping precision" value={percent(evaluation.precision, 1)} detail="Release target ≥ 90%" tone={evaluation.precision >= 0.9 ? 'good' : 'danger'} />
        <MetricCard label="Citation validity" value={percent(evaluation.citationValidity, 1)} detail="Target 100% mechanically valid" tone={evaluation.citationValidity === 1 ? 'good' : 'warning'} />
        <MetricCard label="Abstention quality" value={percent(evaluation.abstentionQuality, 1)} detail={`${percent(evaluation.reviewerRejectionRate, 1)} reviewer rejection`} tone="good" />
      </section>

      <SectionCard title="Artifact scope" description={evaluation.executionMode === 'LIVE' ? 'Metrics come from the live evaluation evidence carried by this signed run.' : 'Metrics come from the signed deterministic replay and mapping benchmark; they are not live-model measurements.'}>
        <div className="evidence-boundary" role="note">
          <DocumentData20Regular />
          <Text>The selected package records <strong>{evaluation.passed}/{evaluation.total} passing cases</strong>. Raw controlled prompts and response prose remain outside the Console; hashes bind that separately protected evidence.</Text>
        </div>
      </SectionCard>

      {evaluation.suggestedMapping ? (
        <section className="suggestion-card" aria-label="AI suggested control mapping">
          <div className="suggestion-icon"><BrainCircuit20Regular /></div>
          <div className="suggestion-content"><div><StatusBadge value={evaluation.suggestedMapping.state} /><Text size={200}>AI-assisted mapping candidate · no authority to conclude</Text></div><strong>{evaluation.suggestedMapping.text}</strong><Text size={200}>{evaluation.suggestedMapping.state === 'SUGGESTED' ? 'A reviewer must accept or reject this append-only suggestion.' : 'The append-only reviewer disposition is shown from this run’s decision history.'} AI cannot declare compliance, accept risk, approve an exception, or close a finding.</Text></div>
          {!publicMode && evaluation.suggestedMapping.state === 'SUGGESTED' ? <div className="suggestion-actions"><Button appearance="secondary" icon={<Dismiss20Regular />} onClick={() => setDecision('REJECTED')}>Reject</Button><Button appearance="primary" icon={<Checkmark20Regular />} onClick={() => setDecision('ACCEPTED')}>Accept mapping</Button></div> : publicMode ? <Text size={200} className="muted">Decision actions unavailable in public mode.</Text> : <Text size={200} className="muted">This suggestion already has a reviewer disposition.</Text>}
        </section>
      ) : evaluation.total > 0 ? (
        <div className="evidence-boundary" role="status">
          <BrainCircuit20Regular />
          <Text><strong>No AI mapping suggestion is included in this evaluation artifact.</strong> The replay results remain available, and no reviewer action is implied.</Text>
        </div>
      ) : (
        <div className="evidence-boundary" role="status">
          <BrainCircuit20Regular />
          <Text><strong>No AI evaluation artifact is available for this assessment package.</strong> Reviewer decision controls remain disabled until a signed evaluation artifact is returned by the API.</Text>
        </div>
      )}

      <div className="filter-bar evaluation-filter">
        <Field label="Category"><Select value={category} onChange={(_, value) => setCategory(value.value)}><option value="ALL">All categories</option>{categories.map((item) => <option key={item}>{item}</option>)}</Select></Field>
        <Field label="Result"><Select value={result} onChange={(_, value) => setResult(value.value)}><option value="ALL">All results</option><option>PASS</option><option>FAIL</option><option>ERROR</option></Select></Field>
        <Text size={200} className="filter-count">{filtered.length} of {evaluation.cases.length} representative cases</Text>
      </div>

      <div className={`master-detail ${selected ? 'detail-open' : ''}`}>
        <section className="table-card" aria-label="Evaluation cases">
          <div className="table-scroll"><table className="data-table"><thead><tr><th>Case</th><th>Category</th><th>Input binding</th><th>Prior artifact</th><th>Replay result</th><th>Disposition</th><th>Latency</th><th>Trace</th></tr></thead><tbody>{filtered.map((testCase) => <tr key={testCase.id} className={selected?.id === testCase.id ? 'selected-row' : undefined}><td><button type="button" className="table-primary-link" onClick={() => setSelected(testCase)}><strong>{testCase.id}</strong><span>{testCase.correlationId ?? 'No correlation ID assigned'}</span></button></td><td>{testCase.category}</td><td><code>sha256:{testCase.inputSha256.slice(0, 12)}…</code></td><td><StatusBadge value={testCase.baselineResult} subtle /></td><td><StatusBadge value={testCase.result} /></td><td><StatusBadge value={testCase.guardrail} subtle /></td><td>{testCase.latencyMs === undefined ? 'Not recorded' : `${testCase.latencyMs} ms`}</td><td>{testCase.controlIds.map((id) => <button type="button" className="inline-link" key={id} onClick={() => onNavigate('controls', id)}>{id}</button>)}</td></tr>)}</tbody></table></div>
          {filtered.length === 0 ? <div className="inline-empty">No evaluation cases match the selected filters.</div> : null}
        </section>
        {selected ? (
          <DetailPanel title={`${selected.id} · ${selected.category}`} subtitle={selected.correlationId ? `Correlation ${selected.correlationId}` : 'No correlation ID was assigned before rejection'} onClose={() => setSelected(undefined)}>
            <div className="detail-status-row"><StatusBadge value={selected.result} /><StatusBadge value={selected.guardrail} subtle /><Text size={200}>{selected.latencyMs === undefined ? 'Latency not recorded' : `${selected.latencyMs} ms`}</Text></div>
            <section className="workpaper-section"><Text weight="semibold">Controlled test input</Text><p className="muted">Raw input withheld from the Console.</p><Text size={100}>SHA-256 {selected.inputSha256} binds the separately controlled test input.</Text></section>
            <section className="response-evidence"><Text weight="semibold">Controlled response evidence</Text>{selected.response ? <blockquote>{selected.response}</blockquote> : <Text className="muted">Response prose was not retained in this result artifact{selected.responseSha256 ? `; SHA-256 ${selected.responseSha256}` : '.'}</Text>}</section>
            <section className="workpaper-section"><Text weight="semibold">Retrieved documents</Text><div className="chip-list">{selected.retrievedDocuments.length ? selected.retrievedDocuments.map((document) => <span className="plain-chip" key={document}><DocumentData20Regular /> {document}</span>) : <Text className="muted">No documents retrieved</Text>}</div></section>
            <section className="workpaper-section"><Text weight="semibold">Tool calls</Text>{selected.toolCalls.length ? <ul className="code-list">{selected.toolCalls.map((tool) => <li key={tool}><code>{tool}</code></li>)}</ul> : <Text className="muted">No tool calls</Text>}</section>
            <div className="definition-grid"><div><Text size={200}>Recorded disposition</Text><StatusBadge value={selected.guardrail} /></div><div><Text size={200}>Prior per-case result</Text><StatusBadge value={selected.baselineResult} /></div></div>
            {selected.findingId ? <Button appearance="outline" onClick={() => onNavigate('findings', selected.findingId)}>Open linked finding {selected.findingId}</Button> : null}
          </DetailPanel>
        ) : null}
      </div>

      <ActionDialog open={Boolean(decision)} title={`${decision === 'ACCEPTED' ? 'Accept' : 'Reject'} AI-suggested mapping`} description="Your rationale creates the authoritative reviewer event. The suggestion remains labeled AI-generated in history." confirmLabel={decision === 'ACCEPTED' ? 'Accept mapping' : 'Reject mapping'} pending={pending} confirmDisabled={rationale.trim().length < 12} onClose={() => setDecision(undefined)} onConfirm={() => void recordSuggestionDecision()}>
        <Field label="Reviewer rationale" required validationMessage={rationale.length > 0 && rationale.trim().length < 12 ? 'Provide at least 12 characters.' : undefined}><Textarea value={rationale} onChange={(_, value) => setRationale(value.value)} resize="vertical" placeholder="Explain why this mapping is or is not appropriate…" /></Field>
      </ActionDialog>
    </div>
  );
}
