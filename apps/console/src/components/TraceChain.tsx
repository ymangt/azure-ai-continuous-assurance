import { Button, Text } from '@fluentui/react-components';
import { ArrowRight20Regular, CheckmarkCircle20Regular } from '@fluentui/react-icons';
import { shortHash } from '../format';
import type { AppView, ConsoleSnapshot } from '../types';

interface TraceChainProps {
  data: ConsoleSnapshot;
  onNavigate: (view: AppView, id?: string) => void;
}

export function TraceChain({ data, onNavigate }: TraceChainProps) {
  const finding = data.findings.find((item) => item.objectiveId && item.retests.some((retest) => retest.evidenceIds.length > 0));
  const objectiveId = finding?.objectiveId;
  const retest = finding?.retests.at(-1);
  const evidenceId = retest?.evidenceIds[0];
  const evidence = data.evidence.find((item) => item.id === evidenceId);
  const risk = data.risks.find((item) => item.findingId === finding?.id);
  if (!objectiveId || !finding || !retest || !evidenceId || !evidence || !risk) {
    return <Text className="muted">No complete criteria-to-retest chain is included in this snapshot.</Text>;
  }

  const traceSteps = [
    { label: objectiveId, detail: 'Control criteria', view: 'controls', id: objectiveId },
    { label: data.diff.resolved.includes(objectiveId) ? 'FAIL → PASS' : 'Recorded', detail: 'Deterministic test', view: 'runs' },
    { label: shortHash(evidence.hash), detail: 'Evidence SHA-256', view: 'evidence', id: evidenceId },
    { label: finding.id, detail: `${finding.severity} finding`, view: 'findings', id: finding.id },
    { label: risk.id, detail: `Residual ${risk.residualScore}/25 risk`, view: 'findings', id: finding.id },
    { label: finding.remediationReference ? shortHash(finding.remediationReference) : 'Recorded', detail: 'Remediation', view: 'findings', id: finding.id },
    { label: retest.result, detail: `${retest.decision} retest`, view: 'runs' },
  ] as const;

  return (
    <div className="trace-chain" aria-label="End-to-end assurance trace">
      {traceSteps.map((step, index) => (
        <div className="trace-segment" key={`${step.label}-${index}`}>
          <Button appearance="subtle" className="trace-step" onClick={() => onNavigate(step.view as AppView, 'id' in step ? step.id : undefined)}>
            <span className="trace-icon"><CheckmarkCircle20Regular /></span>
            <span><strong>{step.label}</strong><Text size={100}>{step.detail}</Text></span>
          </Button>
          {index < traceSteps.length - 1 ? <ArrowRight20Regular className="trace-arrow" aria-hidden="true" /> : null}
        </div>
      ))}
    </div>
  );
}
