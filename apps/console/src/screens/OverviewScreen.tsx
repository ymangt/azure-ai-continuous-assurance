import { Button, ProgressBar, Text } from '@fluentui/react-components';
import { ArrowRight20Regular, CheckmarkCircle24Regular, Clock24Regular, DocumentData24Regular, ShieldError24Regular } from '@fluentui/react-icons';
import { formatDateTime, scoreBand } from '../format';
import type { AppView, ConsoleSnapshot } from '../types';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';
import { ResultDistribution } from '../components/ResultDistribution';
import { SectionCard } from '../components/SectionCard';
import { StatusBadge } from '../components/StatusBadge';
import { TraceChain } from '../components/TraceChain';

interface OverviewScreenProps {
  data: ConsoleSnapshot;
  onNavigate: (view: AppView, id?: string) => void;
}

export function OverviewScreen({ data, onNavigate }: OverviewScreenProps) {
  const counts = {
    PASS: data.controls.filter((control) => control.result === 'PASS').length,
    FAIL: data.controls.filter((control) => control.result === 'FAIL').length,
    ERROR: data.controls.filter((control) => control.result === 'ERROR').length,
    NOT_RUN: data.controls.filter((control) => control.result === 'NOT_RUN').length,
    NOT_APPLICABLE: data.controls.filter((control) => control.result === 'NOT_APPLICABLE').length,
  };
  const currentEvidence = data.evidence.filter((item) => item.freshness === 'CURRENT').length;
  const coverage = data.controls.length ? data.controls.filter((control) => control.result !== 'NOT_RUN').length / data.controls.length : 0;
  const materialRisks = data.risks.filter((risk) => risk.residualScore >= 10).length;
  const openFindings = data.findings.filter((finding) => finding.status === 'OPEN' || finding.status === 'REOPENED' || finding.status === 'READY_FOR_RETEST');
  const runDuration = data.selectedRun.completedAt
    ? Math.max(0, new Date(data.selectedRun.completedAt).getTime() - new Date(data.selectedRun.startedAt).getTime())
    : undefined;
  const durationLabel = runDuration === undefined
    ? 'Not recorded'
    : `${Math.floor(runDuration / 60_000)}m ${Math.floor((runDuration % 60_000) / 1_000)}s`;

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
        <MetricCard label="Test coverage" value={`${Math.round(coverage * 100)}%`} detail={`${data.controls.length} tailored objectives in the current snapshot`} tone="good" icon={<CheckmarkCircle24Regular />} onClick={() => onNavigate('controls')} />
        <MetricCard label="Current evidence" value={`${currentEvidence}/${data.evidence.length}`} detail="Freshness is evaluated independently from result" tone={currentEvidence === data.evidence.length ? 'good' : 'warning'} icon={<DocumentData24Regular />} onClick={() => onNavigate('evidence')} />
        <MetricCard label="Material residual risks" value={materialRisks} detail={`${openFindings.length} finding${openFindings.length === 1 ? '' : 's'} requiring action`} tone={materialRisks ? 'danger' : 'good'} icon={<ShieldError24Regular />} onClick={() => onNavigate('findings')} />
        <MetricCard label="Last signed run" value={durationLabel} detail={`${data.selectedRun.trigger} · CAD $${data.selectedRun.estimatedCostCad.toFixed(2)} estimated`} icon={<Clock24Regular />} onClick={() => onNavigate('runs')} />
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
                    <td><button className="table-link" type="button" onClick={() => onNavigate('findings', finding.id)}>{finding.id} · {finding.title}</button></td>
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
            {[...new Set(data.evidence.map((item) => item.source))].slice(0, 4).map((source) => <span key={source}><CheckmarkCircle24Regular /><Text size={200}>{source}</Text></span>)}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Criteria-to-retest trace" description="The portfolio’s canonical assurance chain remains navigable in three interactions or fewer.">
        <TraceChain data={data} onNavigate={onNavigate} />
      </SectionCard>
    </div>
  );
}
