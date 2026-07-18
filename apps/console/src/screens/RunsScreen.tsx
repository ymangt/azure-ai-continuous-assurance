import { useState } from 'react';
import { Button, Text, Title2 } from '@fluentui/react-components';
import { ArrowRight20Regular, CheckmarkCircle20Regular, Clock20Regular, DocumentSignature20Regular, History20Regular } from '@fluentui/react-icons';
import { assuranceApi } from '../api/client';
import { formatDateTime, shortHash } from '../format';
import type { AppView, CommandFeedbackInput, ConsoleSnapshot } from '../types';
import { ActionDialog } from '../components/ActionDialog';
import { PageHeader } from '../components/PageHeader';
import { SectionCard } from '../components/SectionCard';
import { StatusBadge } from '../components/StatusBadge';

interface RunsScreenProps {
  data: ConsoleSnapshot;
  publicMode: boolean;
  onNavigate: (view: AppView, id?: string) => void;
  onCommand: (feedback: CommandFeedbackInput) => void;
}

const categories = [
  { key: 'resolved', label: 'Resolved', description: 'Failed before; passing with new evidence', tone: 'success' },
  { key: 'new', label: 'New', description: 'First observed in the selected run', tone: 'info' },
  { key: 'regressed', label: 'Regressed', description: 'Previously passing; now failed', tone: 'danger' },
  { key: 'stale', label: 'Stale', description: 'Required evidence exceeded freshness window', tone: 'warning' },
  { key: 'errored', label: 'Errored', description: 'Collection or evaluation could not conclude', tone: 'danger' },
  { key: 'unchanged', label: 'Unchanged', description: 'No material result change', tone: 'neutral' },
] as const;

export function RunsScreen({ data, publicMode, onNavigate, onCommand }: RunsScreenProps) {
  const retestTarget = data.findings.find((finding) => finding.status === 'OPEN' || finding.status === 'REOPENED' || finding.status === 'READY_FOR_RETEST');
  const [retestOpen, setRetestOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const fromRun = data.priorRun;
  const toRun = data.selectedRun;

  const queueRetest = async () => {
    if (!retestTarget) return;
    setPending(true);
    try {
      const receipt = await assuranceApi.queueRetest(retestTarget.id, data.selectedRun.id);
      onCommand({ intent: 'success', message: `Retest request ${receipt.request_id.slice(0, 8)} queued for ${retestTarget.id}.` });
      setRetestOpen(false);
    } catch (error) {
      onCommand({ intent: 'error', message: error instanceof Error ? error.message : 'The retest request could not be queued.' });
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="screen-stack">
      <PageHeader eyebrow="Immutable history" title="Assessment runs" description="Run provenance, signed artifacts, and a deterministic baseline-to-retest comparison." actions={!publicMode && retestTarget ? <Button appearance="primary" icon={<History20Regular />} onClick={() => setRetestOpen(true)}>Queue targeted retest</Button> : undefined} />

      <SectionCard title="Run timeline" description="Historical failures remain visible after remediation; each retest creates a new record.">
        <ol className="run-timeline">
          {data.runs.map((run) => (
            <li key={run.id} className={`run-event run-${run.status.toLowerCase()}`}>
              <span className="run-marker">{run.status === 'COMPLETED' || run.status === 'REVIEW_REQUIRED' ? <CheckmarkCircle20Regular /> : <Clock20Regular />}</span>
              <div className="run-event-main"><div><strong>{run.label}</strong><StatusBadge value={run.status} subtle /></div><Text size={200}>{formatDateTime(run.startedAt)} · {run.trigger}</Text></div>
              <div className="run-event-meta"><code>{run.shortId}</code><Text size={200}>{run.scope}</Text></div>
              <div className="run-event-integrity">{run.signed ? <><DocumentSignature20Regular /><Text size={200}>Signed · {run.signingKeyId?.startsWith('local://') ? 'local sample key' : 'declared key'}</Text></> : <Text size={200}>Signature unavailable</Text>}</div>
            </li>
          ))}
        </ol>
      </SectionCard>

      {data.comparisonAvailable ? <section className="comparison-section" aria-labelledby="comparison-title">
        <div className="comparison-header">
          <div><Title2 id="comparison-title" as="h2">Package-provided comparison</Title2><Text className="muted">This signed package fixes the baseline and selected run; change categories come from its deterministic result and evidence diff.</Text></div>
          <div className="comparison-fixed-pair" aria-label={`Baseline ${fromRun.label} to selected run ${toRun.label}`}><span>{fromRun.label}</span><ArrowRight20Regular aria-hidden="true" /><span>{toRun.label}</span></div>
        </div>

        <div className="run-pair">
          {[fromRun, toRun].map((run, index) => (
            <article className="run-card" key={run.id}>
              <Text size={200}>{index === 0 ? 'BASELINE' : 'RETEST'}</Text>
              <h3>{run.label}</h3>
              <StatusBadge value={run.status} />
              <dl>
                <div><dt>Observation window</dt><dd>{run.observationWindow}</dd></div>
                <div><dt>Git commit</dt><dd><code>{run.gitCommit}</code></dd></div>
                <div><dt>Collector / evaluator</dt><dd>{run.collectorVersion} / {run.evaluatorVersion}</dd></div>
                <div><dt>Estimated cost</dt><dd>CAD ${run.estimatedCostCad.toFixed(2)}</dd></div>
                <div><dt>Manifest</dt><dd><code>{shortHash(run.manifestDigest ?? 'Pending')}</code></dd></div>
                <div><dt>Signing key</dt><dd><code>{run.signingKeyId ?? 'Not provided'}</code></dd></div>
              </dl>
            </article>
          ))}
        </div>

        <div className="diff-grid">
          {categories.map(({ key, label, description, tone }) => {
            const ids = data.diff[key];
            return (
              <article className={`diff-card diff-${tone}`} key={key}>
                <div><strong>{ids.length}</strong><span>{label}</span></div>
                <Text size={200}>{description}</Text>
                <div className="chip-list">{ids.length ? ids.map((id) => <Button key={id} size="small" appearance="subtle" onClick={() => onNavigate('controls', id)}>{id}</Button>) : <Text size={200} className="muted">None</Text>}</div>
              </article>
            );
          })}
        </div>
      </section> : <SectionCard title="Comparison unavailable" description="A second signed assessment run is required before the console can calculate change categories."><Text>The current run is displayed without an invented baseline. Queue another assessment or a targeted retest to enable comparison.</Text></SectionCard>}

      <div className="integrity-footer"><DocumentSignature20Regular /><div><Text weight="semibold">Offline verification</Text><code>assure verify --manifest run-manifest.json</code><Text size={200}>Declared key: {toRun.signingKeyId ?? 'not provided'} · fingerprint {toRun.keyFingerprint ? shortHash(toRun.keyFingerprint) : 'not provided'}</Text></div></div>

      <ActionDialog open={retestOpen && Boolean(retestTarget)} title="Queue targeted retest" description={`The headless job will collect new evidence for ${retestTarget?.id ?? 'the selected finding'} and related objectives. This action cannot close the finding.`} confirmLabel="Queue retest" pending={pending} onClose={() => setRetestOpen(false)} onConfirm={() => void queueRetest()}>
        <div className="dialog-summary"><Text size={200}>Scope</Text><strong>{retestTarget ? `${retestTarget.id} · ${retestTarget.controlIds.join(', ')}` : 'No open finding available'}</strong><Text size={200}>Expected behavior</Text><strong>Fresh scoped evidence + deterministic reevaluation</strong></div>
      </ActionDialog>
    </div>
  );
}
