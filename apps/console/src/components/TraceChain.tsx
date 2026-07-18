import { useState } from 'react';
import { Button, Text } from '@fluentui/react-components';
import { ArrowRight20Regular, CheckmarkCircle20Regular } from '@fluentui/react-icons';
import { formatDateTime, shortHash } from '../format';
import type { AppView, ConsoleSnapshot } from '../types';
import { OverviewPreviewDialog } from './OverviewPreviewDialog';
import { StatusBadge } from './StatusBadge';

interface TraceChainProps {
  data: ConsoleSnapshot;
  onNavigate: (view: AppView, id?: string) => void;
}

type TracePreview =
  | { kind: 'control' }
  | { kind: 'test' }
  | { kind: 'evidence' }
  | { kind: 'finding'; focus: 'finding' | 'risk' | 'remediation' }
  | { kind: 'retest' };

export function TraceChain({ data, onNavigate }: TraceChainProps) {
  const [preview, setPreview] = useState<TracePreview>();
  const [previewOpen, setPreviewOpen] = useState(false);

  const finding = data.findings.find((item) => item.objectiveId && item.retests.some((retest) => retest.evidenceIds.length > 0));
  const objectiveId = finding?.objectiveId;
  const retest = finding?.retests.at(-1);
  const evidenceId = retest?.evidenceIds[0];
  const evidence = data.evidence.find((item) => item.id === evidenceId);
  const risk = data.risks.find((item) => item.findingId === finding?.id);
  const control = objectiveId ? data.controls.find((item) => item.id === objectiveId) : undefined;

  if (!objectiveId || !finding || !retest || !evidenceId || !evidence || !risk) {
    return <Text className="muted">No complete criteria-to-retest chain is included in this snapshot.</Text>;
  }

  const testLabel = data.diff.resolved.includes(objectiveId) ? 'FAIL → PASS' : 'Recorded';

  const traceSteps = [
    { label: objectiveId, detail: 'Control criteria', preview: { kind: 'control' } as const },
    { label: testLabel, detail: 'Deterministic test', preview: { kind: 'test' } as const },
    { label: shortHash(evidence.hash), detail: 'Evidence SHA-256', preview: { kind: 'evidence' } as const },
    { label: finding.id, detail: `${finding.severity} finding`, preview: { kind: 'finding', focus: 'finding' } as const },
    { label: risk.id, detail: `Residual ${risk.residualScore}/25 risk`, preview: { kind: 'finding', focus: 'risk' } as const },
    { label: finding.remediationReference ? shortHash(finding.remediationReference) : 'Recorded', detail: 'Remediation', preview: { kind: 'finding', focus: 'remediation' } as const },
    { label: retest.result, detail: `${retest.decision} retest`, preview: { kind: 'retest' } as const },
  ];

  const showPreview = (next: TracePreview) => {
    setPreview(next);
    setPreviewOpen(true);
  };

  const closePreview = () => setPreviewOpen(false);

  const openPrimary = () => {
    if (!preview) return;
    const next = preview;
    closePreview();
    if (next.kind === 'control') onNavigate('controls', objectiveId);
    else if (next.kind === 'evidence') onNavigate('evidence', evidenceId);
    else if (next.kind === 'finding') onNavigate('findings', finding.id);
    else onNavigate('runs');
  };

  const primaryLabel = preview?.kind === 'control'
    ? 'Open full control'
    : preview?.kind === 'evidence'
      ? 'Open evidence'
      : preview?.kind === 'finding'
        ? 'Open finding'
        : preview
          ? 'Open assessment runs'
          : '';

  const previewTitle = preview?.kind === 'control'
    ? 'Control criteria preview'
    : preview?.kind === 'test'
      ? 'Deterministic test preview'
      : preview?.kind === 'evidence'
        ? 'Evidence preview'
        : preview?.kind === 'retest'
          ? 'Retest preview'
          : preview?.kind === 'finding'
            ? preview.focus === 'risk'
              ? 'Risk preview'
              : preview.focus === 'remediation'
                ? 'Remediation preview'
                : 'Finding preview'
            : '';

  return (
    <>
      <div className="trace-chain" aria-label="End-to-end assurance trace">
        {traceSteps.map((step, index) => (
          <div className="trace-segment" key={`${step.label}-${index}`}>
            <Button appearance="subtle" className="trace-step" onClick={() => showPreview(step.preview)}>
              <span className="trace-icon"><CheckmarkCircle20Regular /></span>
              <span><strong>{step.label}</strong><Text size={100}>{step.detail}</Text></span>
            </Button>
            {index < traceSteps.length - 1 ? <ArrowRight20Regular className="trace-arrow" aria-hidden="true" /> : null}
          </div>
        ))}
      </div>

      <OverviewPreviewDialog
        open={previewOpen}
        title={previewTitle}
        bodyId="trace-step-preview-body"
        primaryLabel={primaryLabel}
        onClose={closePreview}
        onPrimary={openPrimary}
      >
        {preview?.kind === 'control' ? (
          <>
            <div className="overview-preview-header">
              <div>
                <Text weight="semibold">{objectiveId}{control ? ` · ${control.title}` : ''}</Text>
                <Text size={200} className="muted">{control ? `${control.family} · ${control.method}` : 'Control objective from the criteria-to-retest chain'}</Text>
              </div>
              <div className="detail-status-row">
                {control ? <StatusBadge value={control.result} /> : null}
                {control ? <StatusBadge value={control.freshness} subtle /> : null}
                {control?.changed ? <StatusBadge value={control.changed.toUpperCase()} subtle /> : null}
              </div>
            </div>
            {control ? (
              <section className="workpaper-section assessor-note overview-preview-clamp">
                <Text weight="semibold">Assessment objective</Text>
                <p>{control.objective}</p>
              </section>
            ) : (
              <Text className="muted">Full control details are not projected in this snapshot.</Text>
            )}
            <div className="dialog-summary overview-preview-summary">
              <Text size={200}>Owner</Text><strong>{control?.owner ?? '—'}</strong>
              <Text size={200}>Finding</Text><strong>{finding.id} · {finding.severity}</strong>
              <Text size={200}>Evidence</Text><strong>{shortHash(evidence.hash)}</strong>
              <Text size={200}>Latest retest</Text><strong>{retest.result} · {retest.decision}</strong>
            </div>
          </>
        ) : null}

        {preview?.kind === 'test' ? (
          <>
            <div className="overview-preview-header">
              <div>
                <Text weight="semibold">{testLabel}</Text>
                <Text size={200} className="muted">Deterministic procedure outcome for {objectiveId}</Text>
              </div>
              <div className="detail-status-row">
                {control ? <StatusBadge value={control.result} /> : null}
                {control?.changed ? <StatusBadge value={control.changed.toUpperCase()} subtle /> : null}
              </div>
            </div>
            <div className="dialog-summary overview-preview-summary">
              <Text size={200}>Selected run</Text><strong>{data.selectedRun.label}</strong>
              <Text size={200}>Trigger</Text><strong>{data.selectedRun.trigger}</strong>
              <Text size={200}>Objective</Text><strong>{objectiveId}</strong>
              <Text size={200}>Compared to baseline</Text><strong>{data.diff.resolved.includes(objectiveId) ? 'Resolved in this run' : 'Recorded without a resolve mark'}</strong>
            </div>
            <Text size={200} className="muted">A PASS/FAIL here is the procedure result, not the full control effectiveness conclusion.</Text>
          </>
        ) : null}

        {preview?.kind === 'evidence' ? (
          <>
            <div className="overview-preview-header">
              <div>
                <Text weight="semibold">{evidence.id}</Text>
                <Text size={200} className="muted">{evidence.source} · {evidence.mediaType}</Text>
              </div>
              <div className="detail-status-row">
                <StatusBadge value={evidence.freshness} />
                <StatusBadge value={evidence.sensitivity} subtle />
              </div>
            </div>
            <section className="workpaper-section overview-preview-clamp">
              <Text weight="semibold">Summary</Text>
              <p>{evidence.summary}</p>
            </section>
            <div className="dialog-summary overview-preview-summary">
              <Text size={200}>SHA-256</Text><strong className="break-code">{shortHash(evidence.hash)}</strong>
              <Text size={200}>Captured</Text><strong>{formatDateTime(evidence.capturedAt)}</strong>
              <Text size={200}>Scope</Text><strong>{evidence.resourceScope}</strong>
              <Text size={200}>Bound control</Text><strong>{objectiveId}</strong>
            </div>
          </>
        ) : null}

        {preview?.kind === 'finding' ? (
          <>
            <div className="overview-preview-header">
              <div>
                <Text weight="semibold">{finding.id} · {finding.title}</Text>
                <Text size={200} className="muted">{finding.asset} · owner {finding.owner}</Text>
              </div>
              <div className="detail-status-row">
                <StatusBadge value={finding.status} />
                <StatusBadge value={finding.severity} subtle />
              </div>
            </div>
            {preview.focus === 'risk' ? (
              <div className="dialog-summary overview-preview-summary">
                <Text size={200}>Risk ID</Text><strong>{risk.id}</strong>
                <Text size={200}>Residual</Text><strong>{risk.residualScore}/25</strong>
                <Text size={200}>Inherent</Text><strong>{risk.inherentScore}/25</strong>
                <Text size={200}>Treatment</Text><strong>{risk.treatment}</strong>
              </div>
            ) : preview.focus === 'remediation' ? (
              <>
                <section className="workpaper-section overview-preview-clamp">
                  <Text weight="semibold">Remediation</Text>
                  <p>{finding.remediation || 'No remediation narrative is projected in this snapshot.'}</p>
                </section>
                <div className="dialog-summary overview-preview-summary">
                  <Text size={200}>Reference</Text><strong className="break-code">{finding.remediationReference ? shortHash(finding.remediationReference) : 'Recorded'}</strong>
                  <Text size={200}>Evidence proof</Text><strong>{finding.remediationEvidenceIds.length ? finding.remediationEvidenceIds.join(', ') : 'None listed'}</strong>
                  <Text size={200}>Recorded by</Text><strong>{finding.remediationRecordedBy ?? '—'}</strong>
                  <Text size={200}>Target date</Text><strong>{finding.targetDate}</strong>
                </div>
              </>
            ) : (
              <>
                <section className="workpaper-section overview-preview-clamp">
                  <Text weight="semibold">Condition</Text>
                  <p>{finding.condition}</p>
                </section>
                <div className="dialog-summary overview-preview-summary">
                  <Text size={200}>Criteria</Text><strong className="overview-preview-clamp">{finding.criteria}</strong>
                  <Text size={200}>Objective</Text><strong>{finding.objectiveId ?? '—'}</strong>
                  <Text size={200}>Residual risk</Text><strong>{risk.residualScore}/25</strong>
                  <Text size={200}>Target date</Text><strong>{finding.targetDate}</strong>
                </div>
              </>
            )}
          </>
        ) : null}

        {preview?.kind === 'retest' ? (
          <>
            <div className="overview-preview-header">
              <div>
                <Text weight="semibold">{retest.result} · {retest.decision}</Text>
                <Text size={200} className="muted">Latest retest event for {finding.id}</Text>
              </div>
              <div className="detail-status-row">
                <StatusBadge value={retest.result} />
                <StatusBadge value={retest.reviewState} subtle />
              </div>
            </div>
            <section className="workpaper-section overview-preview-clamp">
              <Text weight="semibold">Rationale</Text>
              <p>{retest.rationale}</p>
            </section>
            <div className="dialog-summary overview-preview-summary">
              <Text size={200}>Run</Text><strong>{retest.runId}</strong>
              <Text size={200}>Date</Text><strong>{formatDateTime(retest.date)}</strong>
              <Text size={200}>Evidence freshness</Text><strong>{retest.evidenceFreshness}</strong>
              <Text size={200}>Evidence IDs</Text><strong>{retest.evidenceIds.join(', ')}</strong>
            </div>
          </>
        ) : null}

        <Text size={200} className="muted">
          Stay on Overview to continue the chain, or open the linked workpaper for the full record.
        </Text>
      </OverviewPreviewDialog>
    </>
  );
}
