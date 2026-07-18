import { useEffect, useMemo, useState } from 'react';
import { Button, Field, Input, Select, Text, Textarea } from '@fluentui/react-components';
import { CheckmarkCircle20Regular, DocumentData20Regular, Search20Regular } from '@fluentui/react-icons';
import { assuranceApi } from '../api/client';
import type { AppView, ConsoleSnapshot, ControlObjective } from '../types';
import { ActionDialog } from '../components/ActionDialog';
import { DetailPanel } from '../components/DetailPanel';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';

interface ControlsScreenProps {
  data: ConsoleSnapshot;
  publicMode: boolean;
  focusId?: string;
  onNavigate: (view: AppView, id?: string) => void;
  onCommand: (message: string) => void;
}

export function ControlsScreen({ data, publicMode, focusId, onNavigate, onCommand }: ControlsScreenProps) {
  const [search, setSearch] = useState('');
  const [result, setResult] = useState('ALL');
  const [method, setMethod] = useState('ALL');
  const [selected, setSelected] = useState<ControlObjective>();
  const [reviewOpen, setReviewOpen] = useState(false);
  const [reviewConclusion, setReviewConclusion] = useState('EFFECTIVE');
  const [rationale, setRationale] = useState('');
  const [pending, setPending] = useState(false);

  useEffect(() => {
    if (focusId) setSelected(data.controls.find((control) => control.id === focusId));
  }, [data.controls, focusId]);

  const filtered = useMemo(() => data.controls.filter((control) => {
    const needle = search.trim().toLowerCase();
    const matchesText = !needle || `${control.id} ${control.title} ${control.family} ${control.owner}`.toLowerCase().includes(needle);
    return matchesText && (result === 'ALL' || control.result === result) && (method === 'ALL' || control.method === method);
  }), [data.controls, method, result, search]);

  const submitReview = async () => {
    if (!selected || rationale.trim().length < 12) return;
    setPending(true);
    try {
      const receipt = await assuranceApi.recordDecision({ subject_type: 'control', subject_id: selected.id, artifact_run_id: data.selectedRun.id, decision: reviewConclusion, rationale: rationale.trim(), expected_version: selected.reviewVersion ?? 1 });
      onCommand(`Reviewer conclusion accepted as command ${receipt.request_id.slice(0, 8)}. The signed assessment artifact was not overwritten.`);
      setReviewOpen(false);
      setRationale('');
    } catch (error) {
      onCommand(error instanceof Error ? `Decision failed: ${error.message}` : 'The reviewer decision could not be recorded.');
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="screen-stack">
      <PageHeader eyebrow="Audit workpapers" title="Controls" description="Tailored objectives connect assessment methods, evidence, assessor conclusions, and known limitations." />

      <div className="filter-bar" role="search">
        <Field label="Search controls" className="search-field"><Input value={search} onChange={(_, value) => setSearch(value.value)} contentBefore={<Search20Regular />} placeholder="ID, title, family, or owner" /></Field>
        <Field label="Test result"><Select value={result} onChange={(_, value) => setResult(value.value)}><option value="ALL">All results</option><option>PASS</option><option>FAIL</option><option>ERROR</option><option>NOT_RUN</option></Select></Field>
        <Field label="Method"><Select value={method} onChange={(_, value) => setMethod(value.value)}><option value="ALL">All methods</option><option>Automated</option><option>Hybrid</option><option>Manual</option></Select></Field>
        <Text size={200} className="filter-count">{filtered.length} of {data.controls.length} objectives</Text>
      </div>

      <div className={`master-detail ${selected ? 'detail-open' : ''}`}>
        <section className="table-card" aria-label="Control objectives">
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Control objective</th><th>Family</th><th>Method</th><th>Result</th><th>Design</th><th>Operating</th><th>Owner</th><th>Evidence</th></tr></thead>
              <tbody>
                {filtered.map((control) => (
                  <tr key={control.id} className={selected?.id === control.id ? 'selected-row' : undefined}>
                    <td><button type="button" className="table-primary-link" onClick={() => setSelected(control)}><strong>{control.id}</strong><span>{control.title}</span></button></td>
                    <td>{control.family}</td>
                    <td>{control.method}</td>
                    <td><StatusBadge value={control.result} /></td>
                    <td><StatusBadge value={control.designEffectiveness} subtle /></td>
                    <td><StatusBadge value={control.operatingEffectiveness} subtle /></td>
                    <td>{control.owner}</td>
                    <td><span className="evidence-count"><DocumentData20Regular /> {control.evidenceIds.length}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!filtered.length ? <div className="inline-empty"><Search20Regular /><Text>No controls match these filters.</Text><Button appearance="subtle" onClick={() => { setSearch(''); setResult('ALL'); setMethod('ALL'); }}>Clear filters</Button></div> : null}
        </section>

        {selected ? (
          <DetailPanel
            title={`${selected.id} · ${selected.title}`}
            subtitle={`${selected.family} · ${selected.method}`}
            onClose={() => setSelected(undefined)}
            actions={!publicMode ? <Button appearance="primary" icon={<CheckmarkCircle20Regular />} onClick={() => setReviewOpen(true)}>Record reviewer conclusion</Button> : <Text size={200} className="muted">Reviewer actions are unavailable in the public snapshot.</Text>}
          >
            <div className="detail-status-row"><StatusBadge value={selected.result} /><StatusBadge value={selected.freshness} subtle />{selected.changed ? <StatusBadge value={selected.changed.toUpperCase()} subtle /> : null}</div>
            <section className="workpaper-section"><Text weight="semibold">Assessment objective</Text><p>{selected.objective}</p></section>
            <div className="definition-grid">
              <div><Text size={200}>Design effectiveness</Text><StatusBadge value={selected.designEffectiveness} /></div>
              <div><Text size={200}>Operating effectiveness</Text><StatusBadge value={selected.operatingEffectiveness} /></div>
              <div><Text size={200}>Owner</Text><strong>{selected.owner}</strong></div>
              <div><Text size={200}>Cadence</Text><strong>{selected.cadence}</strong></div>
            </div>
            <section className="workpaper-section assessor-note"><Text weight="semibold">Assessor conclusion</Text><p>{selected.assessorNote}</p><Text size={100}>Human-authored conclusion · immutable run record</Text></section>
            {selected.reviewerConclusion ? <section className="workpaper-section"><Text weight="semibold">Reviewer conclusion</Text><div className="detail-status-row"><StatusBadge value={selected.reviewerConclusion} /><Text size={200}>{selected.reviewer ?? 'Recorded reviewer'}</Text></div><p>{selected.reviewerRationale ?? 'No reviewer rationale was projected.'}</p><Text size={100}>Append-only review overlay · signed assessor record unchanged</Text></section> : null}
            <section className="workpaper-section"><Text weight="semibold">Evidence references</Text><div className="chip-list">{selected.evidenceIds.length ? selected.evidenceIds.map((id) => <Button key={id} size="small" appearance="outline" icon={<DocumentData20Regular />} onClick={() => onNavigate('evidence', id)}>{id}</Button>) : <Text className="danger-text">No evidence available — conclusion is NOT CONCLUDED.</Text>}</div></section>
            <section className="workpaper-section"><Text weight="semibold">Known limitations</Text><p>{selected.limitations}</p></section>
            <section className="workpaper-section"><Text weight="semibold">Informative mappings</Text><div className="chip-list">{selected.frameworkMappings.map((mapping) => <span className="plain-chip" key={mapping}>{mapping}</span>)}</div></section>
          </DetailPanel>
        ) : null}
      </div>

      <ActionDialog open={reviewOpen} title={`Record conclusion for ${selected?.id ?? ''}`} description="This appends a reviewer decision with optimistic concurrency. It does not change the test result or overwrite the signed artifact." confirmLabel="Record decision" pending={pending} confirmDisabled={rationale.trim().length < 12} onClose={() => setReviewOpen(false)} onConfirm={submitReview}>
        <Field label="Conclusion" required><Select value={reviewConclusion} onChange={(_, value) => setReviewConclusion(value.value)}><option>EFFECTIVE</option><option>PARTIALLY_EFFECTIVE</option><option>INEFFECTIVE</option><option>NOT_CONCLUDED</option></Select></Field>
        <Field label="Reviewer rationale" required validationMessage={rationale.length > 0 && rationale.trim().length < 12 ? 'Provide at least 12 characters.' : undefined}><Textarea value={rationale} onChange={(_, value) => setRationale(value.value)} placeholder="Explain how the evidence supports this conclusion…" resize="vertical" /></Field>
      </ActionDialog>
    </div>
  );
}
