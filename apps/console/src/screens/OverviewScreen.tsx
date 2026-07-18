import { useState } from 'react';
import { Button, ProgressBar, Text } from '@fluentui/react-components';
import { ArrowRight20Regular, CheckmarkCircle24Regular, Clock24Regular, DocumentData24Regular, ShieldError24Regular } from '@fluentui/react-icons';
import { formatDateTime, scoreBand, shortHash } from '../format';
import type { AppView, ConsoleSnapshot, Finding } from '../types';
import { MetricCard } from '../components/MetricCard';
import { OverviewPreviewDialog } from '../components/OverviewPreviewDialog';
import { PageHeader } from '../components/PageHeader';
import { ResultDistribution } from '../components/ResultDistribution';
import { SectionCard } from '../components/SectionCard';
import { StatusBadge } from '../components/StatusBadge';
import { TraceChain } from '../components/TraceChain';

interface OverviewScreenProps {
  data: ConsoleSnapshot;
  onNavigate: (view: AppView, id?: string) => void;
}

type OverviewPreview =
  | { kind: 'coverage' }
  | { kind: 'evidence' }
  | { kind: 'risks' }
  | { kind: 'run' }
  | { kind: 'finding'; finding: Finding };

export function OverviewScreen({ data, onNavigate }: OverviewScreenProps) {
  const [preview, setPreview] = useState<OverviewPreview>();
  const [previewOpen, setPreviewOpen] = useState(false);

  const counts = {
    PASS: data.controls.filter((control) => control.result === 'PASS').length,
    FAIL: data.controls.filter((control) => control.result === 'FAIL').length,
    ERROR: data.controls.filter((control) => control.result === 'ERROR').length,
    NOT_RUN: data.controls.filter((control) => control.result === 'NOT_RUN').length,
    NOT_APPLICABLE: data.controls.filter((control) => control.result === 'NOT_APPLICABLE').length,
  };
  const currentEvidence = data.evidence.filter((item) => item.freshness === 'CURRENT').length;
  const staleEvidence = data.evidence.filter((item) => item.freshness === 'STALE').length;
  const unavailableEvidence = data.evidence.filter((item) => item.freshness === 'UNAVAILABLE').length;
  const coverage = data.controls.length ? data.controls.filter((control) => control.result !== 'NOT_RUN').length / data.controls.length : 0;
  const materialRisks = data.risks.filter((risk) => risk.residualScore >= 10).length;
  const openFindings = data.findings.filter((finding) => finding.status === 'OPEN' || finding.status === 'REOPENED' || finding.status === 'READY_FOR_RETEST');
  const runDuration = data.selectedRun.completedAt
    ? Math.max(0, new Date(data.selectedRun.completedAt).getTime() - new Date(data.selectedRun.startedAt).getTime())
    : undefined;
  const durationLabel = runDuration === undefined
    ? 'Not recorded'
    : `${Math.floor(runDuration / 60_000)}m ${Math.floor((runDuration % 60_000) / 1_000)}s`;
  const evidenceSources = [...new Set(data.evidence.map((item) => item.source))].slice(0, 4);
  const previewFindingRisk = preview?.kind === 'finding'
    ? data.risks.find((item) => item.findingId === preview.finding.id)
    : undefined;

  const showPreview = (next: OverviewPreview) => {
    setPreview(next);
    setPreviewOpen(true);
  };

  const closePreview = () => setPreviewOpen(false);

  const openPrimary = () => {
    if (!preview) return;
    const next = preview;
    closePreview();
    if (next.kind === 'coverage') onNavigate('controls');
    else if (next.kind === 'evidence') onNavigate('evidence');
    else if (next.kind === 'risks') onNavigate('findings');
    else if (next.kind === 'run') onNavigate('runs');
    else onNavigate('findings', next.finding.id);
  };

  const previewTitle = preview?.kind === 'coverage'
    ? 'Test coverage preview'
    : preview?.kind === 'evidence'
      ? 'Evidence freshness preview'
      : preview?.kind === 'risks'
        ? 'Material residual risks preview'
        : preview?.kind === 'run'
          ? 'Last signed run preview'
          : preview?.kind === 'finding'
            ? 'Finding preview'
            : '';

  const primaryLabel = preview?.kind === 'coverage'
    ? 'Open controls'
    : preview?.kind === 'evidence'
      ? 'Open evidence'
      : preview?.kind === 'risks'
        ? 'Open risk register'
        : preview?.kind === 'run'
          ? 'Open assessment runs'
          : 'Open finding';

  return (
    <div className="screen-stack">
      <PageHeader
        eyebrow="Executive posture"
        title="Assurance overview"
        description="Current control conclusions, material risks, and evidence health for the selected signed assessment."
        actions={<Button appearance="secondary" onClick={() => onNavigate('runs')}>Compare runs <ArrowRight20Regular /></Button>}
      />

      <div className="readiness-label" role="note">
        <ShieldError24Regular />
        <div><strong>Internal readiness assessment — not certification</strong><Text size={200}>Simulated owner, assessor, and approver roles do not constitute independent assurance.</Text></div>
      </div>

      <section className="metric-grid" aria-label="Assessment metrics">
        <MetricCard label="Test coverage" value={`${Math.round(coverage * 100)}%`} detail={`${data.controls.length} tailored objectives in the current snapshot`} tone="good" icon={<CheckmarkCircle24Regular />} onClick={() => showPreview({ kind: 'coverage' })} />
        <MetricCard label="Current evidence" value={`${currentEvidence}/${data.evidence.length}`} detail="Freshness is evaluated independently from result" tone={currentEvidence === data.evidence.length ? 'good' : 'warning'} icon={<DocumentData24Regular />} onClick={() => showPreview({ kind: 'evidence' })} />
        <MetricCard label="Material residual risks" value={materialRisks} detail={`${openFindings.length} finding${openFindings.length === 1 ? '' : 's'} requiring action`} tone={materialRisks ? 'danger' : 'good'} icon={<ShieldError24Regular />} onClick={() => showPreview({ kind: 'risks' })} />
        <MetricCard label="Last signed run" value={durationLabel} detail={`${data.selectedRun.trigger} · CAD $${data.selectedRun.estimatedCostCad.toFixed(2)} estimated`} icon={<Clock24Regular />} onClick={() => showPreview({ kind: 'run' })} />
      </section>

      <div className="two-column-grid overview-grid">
        <SectionCard title="Control test distribution" description="A passed test supports an objective; it does not alone prove the full control effective.">
          <ResultDistribution values={[
            { status: 'PASS', count: counts.PASS },
            { status: 'FAIL', count: counts.FAIL },
            { status: 'ERROR', count: counts.ERROR },
            { status: 'NOT_RUN', count: counts.NOT_RUN },
            { status: 'NOT_APPLICABLE', count: counts.NOT_APPLICABLE },
          ]} />
          <div className="mini-stat-grid">
            <div><Text size={200}>Design effective</Text><strong>{data.controls.filter((control) => control.designEffectiveness === 'EFFECTIVE').length}</strong></div>
            <div><Text size={200}>Operating effective</Text><strong>{data.controls.filter((control) => control.operatingEffectiveness === 'EFFECTIVE').length}</strong></div>
            <div><Text size={200}>Not concluded</Text><strong>{data.controls.filter((control) => control.operatingEffectiveness === 'NOT_CONCLUDED').length}</strong></div>
          </div>
        </SectionCard>

        {data.comparisonAvailable ? <SectionCard title="Change since baseline" description={`${data.priorRun.label} → ${data.selectedRun.label}`} action={<Button appearance="subtle" onClick={() => onNavigate('runs')}>View diff</Button>}>
          <div className="change-grid">
            <div className="change-stat resolved"><strong>{data.diff.resolved.length}</strong><span>Resolved</span></div>
            <div className="change-stat new"><strong>{data.diff.new.length}</strong><span>New</span></div>
            <div className="change-stat regressed"><strong>{data.diff.regressed.length}</strong><span>Regressed</span></div>
            <div className="change-stat error"><strong>{data.diff.errored.length}</strong><span>Errored</span></div>
          </div>
          <div className="run-integrity-row">
            <div><Text size={200}>Manifest signature</Text><StatusBadge value={data.selectedRun.signed ? 'PASS' : 'ERROR'} /></div>
            <div><Text size={200}>Generated</Text><strong>{formatDateTime(data.generatedAt)}</strong></div>
          </div>
        </SectionCard> : <SectionCard title="Comparison unavailable" description="A second signed run is required for baseline-to-current change analysis." action={<Button appearance="subtle" onClick={() => onNavigate('runs')}>View run</Button>}><Text>No baseline, zero-change result, or trend has been inferred from this single run.</Text><div className="run-integrity-row"><div><Text size={200}>Manifest signature</Text><StatusBadge value={data.selectedRun.signed ? 'PASS' : 'ERROR'} /></div><div><Text size={200}>Generated</Text><strong>{formatDateTime(data.generatedAt)}</strong></div></div></SectionCard>}
      </div>

      <SectionCard title="Material findings and risks" description="Risk uses the documented 5×5 likelihood × impact rubric." action={<Button appearance="subtle" onClick={() => onNavigate('findings')}>Open risk register <ArrowRight20Regular /></Button>}>
        <div className="table-scroll">
          <table className="data-table compact-table">
            <thead><tr><th>Finding</th><th>Status</th><th>Residual risk</th><th>Owner</th><th>Target</th></tr></thead>
            <tbody>
              {data.findings.slice(0, 3).map((finding) => {
                const risk = data.risks.find((item) => item.findingId === finding.id);
                return (
                  <tr key={finding.id}>
                    <td><button className="table-link" type="button" onClick={() => showPreview({ kind: 'finding', finding })}>{finding.id} · {finding.title}</button></td>
                    <td><StatusBadge value={finding.status} subtle /></td>
                    <td>{risk ? <><StatusBadge value={scoreBand(risk.residualScore)} /> <span className="score-number">{risk.residualScore}/25</span></> : '—'}</td>
                    <td>{finding.owner}</td>
                    <td>{finding.targetDate}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </SectionCard>

      <SectionCard title="Evidence freshness" description="Required stale or unavailable evidence forces NOT CONCLUDED, regardless of the prior test result.">
        <div className="freshness-row">
          <div className="freshness-progress">
            <div><Text weight="semibold">Current, sanitized evidence</Text><Text>{currentEvidence} of {data.evidence.length} artifacts</Text></div>
            <ProgressBar value={data.evidence.length ? currentEvidence / data.evidence.length : 0} thickness="large" />
          </div>
          <div className="freshness-source-list">
            {evidenceSources.map((source) => <span key={source}><CheckmarkCircle24Regular /><Text size={200}>{source}</Text></span>)}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Criteria-to-retest trace" description="The portfolio’s canonical assurance chain remains navigable in three interactions or fewer.">
        <TraceChain data={data} onNavigate={onNavigate} />
      </SectionCard>

      <OverviewPreviewDialog
        open={previewOpen}
        title={previewTitle}
        bodyId="overview-metric-preview-body"
        primaryLabel={primaryLabel}
        onClose={closePreview}
        onPrimary={openPrimary}
      >
        {preview?.kind === 'coverage' ? (
          <>
            <div className="overview-preview-header">
              <div>
                <Text weight="semibold">{Math.round(coverage * 100)}% of tailored objectives exercised</Text>
                <Text size={200} className="muted">{data.controls.length} control objectives in the selected signed snapshot</Text>
              </div>
            </div>
            <div className="dialog-summary overview-preview-summary">
              <Text size={200}>Pass</Text><strong>{counts.PASS}</strong>
              <Text size={200}>Fail</Text><strong>{counts.FAIL}</strong>
              <Text size={200}>Error / not run</Text><strong>{counts.ERROR + counts.NOT_RUN}</strong>
              <Text size={200}>Not applicable</Text><strong>{counts.NOT_APPLICABLE}</strong>
            </div>
            <Text size={200} className="muted">Coverage measures whether a procedure ran. It does not by itself prove design or operating effectiveness.</Text>
          </>
        ) : null}

        {preview?.kind === 'evidence' ? (
          <>
            <div className="overview-preview-header">
              <div>
                <Text weight="semibold">{currentEvidence} of {data.evidence.length} artifacts are current</Text>
                <Text size={200} className="muted">Freshness is evaluated independently from PASS/FAIL results</Text>
              </div>
            </div>
            <div className="dialog-summary overview-preview-summary">
              <Text size={200}>Current</Text><strong>{currentEvidence}</strong>
              <Text size={200}>Stale</Text><strong>{staleEvidence}</strong>
              <Text size={200}>Unavailable</Text><strong>{unavailableEvidence}</strong>
              <Text size={200}>Sources shown</Text><strong>{evidenceSources.length ? evidenceSources.join(' · ') : '—'}</strong>
            </div>
            <Text size={200} className="muted">Stale or unavailable required evidence forces NOT CONCLUDED regardless of the prior test result.</Text>
          </>
        ) : null}

        {preview?.kind === 'risks' ? (
          <>
            <div className="overview-preview-header">
              <div>
                <Text weight="semibold">{materialRisks} material residual risk{materialRisks === 1 ? '' : 's'}</Text>
                <Text size={200} className="muted">{openFindings.length} finding{openFindings.length === 1 ? '' : 's'} requiring action · residual ≥ 10/25</Text>
              </div>
            </div>
            <ul className="overview-preview-list">
              {data.findings.slice(0, 3).map((finding) => {
                const risk = data.risks.find((item) => item.findingId === finding.id);
                return (
                  <li key={finding.id}>
                    <strong>{finding.id} · {finding.title}</strong>
                    <span className="detail-status-row">
                      <StatusBadge value={finding.status} subtle />
                      {risk ? <StatusBadge value={scoreBand(risk.residualScore)} /> : null}
                    </span>
                  </li>
                );
              })}
            </ul>
            <Text size={200} className="muted">Open the risk register for residual scoring, treatment, and retest disposition.</Text>
          </>
        ) : null}

        {preview?.kind === 'run' ? (
          <>
            <div className="overview-preview-header">
              <div>
                <Text weight="semibold">{data.selectedRun.label}</Text>
                <Text size={200} className="muted">{data.selectedRun.shortId} · {data.selectedRun.trigger}</Text>
              </div>
              <div className="detail-status-row">
                <StatusBadge value={data.selectedRun.status} />
                <StatusBadge value={data.selectedRun.signed ? 'PASS' : 'ERROR'} subtle />
              </div>
            </div>
            <div className="dialog-summary overview-preview-summary">
              <Text size={200}>Duration</Text><strong>{durationLabel}</strong>
              <Text size={200}>Estimated cost</Text><strong>CAD ${data.selectedRun.estimatedCostCad.toFixed(2)}</strong>
              <Text size={200}>Started</Text><strong>{formatDateTime(data.selectedRun.startedAt)}</strong>
              <Text size={200}>Manifest</Text><strong className="break-code">{data.selectedRun.manifestDigest ? shortHash(data.selectedRun.manifestDigest) : '—'}</strong>
            </div>
            <Text size={200} className="muted">Assessment Runs holds comparison, integrity details, and targeted retest actions.</Text>
          </>
        ) : null}

        {preview?.kind === 'finding' ? (
          <>
            <div className="overview-preview-header">
              <div>
                <Text weight="semibold">{preview.finding.id} · {preview.finding.title}</Text>
                <Text size={200} className="muted">{preview.finding.asset} · owner {preview.finding.owner}</Text>
              </div>
              <div className="detail-status-row">
                <StatusBadge value={preview.finding.status} />
                <StatusBadge value={preview.finding.severity} subtle />
              </div>
            </div>
            <section className="workpaper-section overview-preview-clamp">
              <Text weight="semibold">Condition</Text>
              <p>{preview.finding.condition}</p>
            </section>
            <div className="dialog-summary overview-preview-summary">
              <Text size={200}>Criteria</Text><strong className="overview-preview-clamp">{preview.finding.criteria}</strong>
              <Text size={200}>Residual risk</Text><strong>{previewFindingRisk ? `${previewFindingRisk.residualScore}/25` : '—'}</strong>
              <Text size={200}>Treatment</Text><strong>{preview.finding.treatment}</strong>
              <Text size={200}>Target date</Text><strong>{preview.finding.targetDate}</strong>
            </div>
          </>
        ) : null}
      </OverviewPreviewDialog>
    </div>
  );
}
