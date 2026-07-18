import { useEffect, useMemo, useState } from 'react';
import { Button, Field, Input, Select, Text, Textarea } from '@fluentui/react-components';
import { CalendarClock20Regular, CheckmarkCircle20Regular, History20Regular, Search20Regular } from '@fluentui/react-icons';
import { assuranceApi } from '../api/client';
import { formatDate, scoreBand } from '../format';
import type { AppView, CommandFeedbackInput, ConsoleSnapshot, Finding } from '../types';
import { ActionDialog } from '../components/ActionDialog';
import { DetailPanel } from '../components/DetailPanel';
import { PageHeader } from '../components/PageHeader';
import { StatusBadge } from '../components/StatusBadge';

interface FindingsScreenProps {
  data: ConsoleSnapshot;
  publicMode: boolean;
  focusId?: string;
  onNavigate: (view: AppView, id?: string) => void;
  onCommand: (feedback: CommandFeedbackInput) => void;
}

type DialogMode = 'none' | 'retest' | 'exception' | 'ready' | 'disposition';

function utcDateOffset(days: number): string {
  const value = new Date();
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

export function FindingsScreen({ data, publicMode, focusId, onNavigate, onCommand }: FindingsScreenProps) {
  const [tab, setTab] = useState<'findings' | 'risks'>('findings');
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('ALL');
  const [selected, setSelected] = useState<Finding>();
  const [dialog, setDialog] = useState<DialogMode>('none');
  const [pending, setPending] = useState(false);
  const [rationale, setRationale] = useState('');
  const [compensatingControl, setCompensatingControl] = useState('');
  const [expiresAt, setExpiresAt] = useState(() => utcDateOffset(30));
  const [minimumExpiry] = useState(() => utcDateOffset(1));
  const [remediationOwner, setRemediationOwner] = useState('');
  const [remediationAction, setRemediationAction] = useState('');
  const [remediationTargetDate, setRemediationTargetDate] = useState(() => utcDateOffset(30));
  const [remediationReference, setRemediationReference] = useState('');
  const [remediationEvidence, setRemediationEvidence] = useState('');
  const latestRetest = selected?.retests.at(-1);
  const reviewableRetest = latestRetest?.reviewState === 'SUGGESTED'
    && (latestRetest.decision === 'REOPEN'
      || (latestRetest.result === 'PASS' && latestRetest.evidenceFreshness === 'CURRENT' && latestRetest.evidenceIds.length > 0));

  useEffect(() => {
    if (focusId) {
      setSelected(data.findings.find((finding) => finding.id === focusId));
      setTab('findings');
    } else setSelected(undefined);
  }, [data.findings, focusId]);

  const filtered = useMemo(() => data.findings.filter((finding) => {
    const needle = search.trim().toLowerCase();
    const matchesText = !needle || `${finding.id} ${finding.title} ${finding.owner} ${finding.controlIds.join(' ')}`.toLowerCase().includes(needle);
    return matchesText && (status === 'ALL' || finding.status === status);
  }), [data.findings, search, status]);

  const remediationEvidenceIds = remediationEvidence.split(',').map((value) => value.trim()).filter(Boolean);
  const knownEvidenceIds = new Set(data.evidence.map((item) => item.id));
  const remediationEvidenceValid = remediationEvidenceIds.length > 0
    && new Set(remediationEvidenceIds).size === remediationEvidenceIds.length
    && remediationEvidenceIds.every((id) => knownEvidenceIds.has(id));

  const openReadyDialog = () => {
    if (!selected) return;
    setRemediationOwner(selected.owner);
    setRemediationAction(selected.remediation === 'No remediation action recorded.' ? '' : selected.remediation);
    setRemediationTargetDate(selected.targetDate || utcDateOffset(30));
    setRemediationReference(selected.remediationReference ?? '');
    setRemediationEvidence('');
    setDialog('ready');
  };

  const runCommand = async () => {
    if (!selected) return;
    setPending(true);
    try {
      if (dialog === 'retest') {
        const receipt = await assuranceApi.queueRetest(selected.id, data.selectedRun.id);
        onCommand({ intent: 'success', message: `Retest ${receipt.request_id.slice(0, 8)} queued. Closure still requires new evidence and a reviewer decision.` });
      } else if (dialog === 'ready') {
        const receipt = await assuranceApi.createRemediation({
          finding_id: selected.id,
          artifact_run_id: data.selectedRun.id,
          owner: remediationOwner.trim(),
          action: remediationAction.trim(),
          target_date: new Date(`${remediationTargetDate}T00:00:00Z`).toISOString(),
          commit_or_pr: remediationReference.trim(),
          evidence_refs: remediationEvidenceIds,
          expected_version: selected.reviewVersion ?? 1,
        });
        onCommand({ intent: 'success', message: `Remediation readiness recorded as command ${receipt.request_id.slice(0, 8)}. No finding was closed.` });
      } else if (dialog === 'disposition' && latestRetest) {
        const receipt = await assuranceApi.recordDecision({ subject_type: 'finding', subject_id: selected.id, artifact_run_id: data.selectedRun.id, prior_state: selected.status, decision: latestRetest.decision, rationale: rationale.trim(), expected_version: selected.reviewVersion ?? 1 });
        onCommand({ intent: 'success', message: `Retest recommendation ${receipt.request_id.slice(0, 8)} recorded for reviewer disposition. The signed retest remains immutable.` });
      } else if (dialog === 'exception') {
        const receipt = await assuranceApi.createException({ finding_id: selected.id, artifact_run_id: data.selectedRun.id, rationale: rationale.trim(), compensating_control: compensatingControl.trim(), expires_at: expiresAt, expected_version: selected.reviewVersion ?? 1 });
        onCommand({ intent: 'success', message: `Time-bounded exception ${receipt.request_id.slice(0, 8)} recorded. The failed test and observation remain unchanged.` });
      }
      setDialog('none');
      setRationale('');
      setCompensatingControl('');
    } catch (error) {
      onCommand({ intent: 'error', message: error instanceof Error ? error.message : 'The assurance command could not be recorded.' });
    } finally {
      setPending(false);
    }
  };

  const canSubmit = dialog === 'retest'
    || (dialog === 'ready'
      && remediationOwner.trim().length >= 2
      && remediationAction.trim().length >= 12
      && remediationTargetDate.length > 0
      && remediationReference.trim().length > 0
      && remediationEvidenceValid)
    || (dialog === 'disposition' && rationale.trim().length >= 12)
    || (dialog === 'exception' && rationale.trim().length >= 12 && compensatingControl.trim().length >= 12 && expiresAt >= minimumExpiry);

  return (
    <div className="screen-stack">
      <PageHeader eyebrow="Risk lifecycle" title="Findings & risks" description="Criteria-to-condition workpapers, treatment decisions, immutable remediation history, and evidence-backed retests." />

      <div className="segmented-control" role="tablist" aria-label="Findings and risks">
        <button type="button" role="tab" aria-selected={tab === 'findings'} className={tab === 'findings' ? 'active' : ''} onClick={() => setTab('findings')}>Findings <span>{data.findings.length}</span></button>
        <button type="button" role="tab" aria-selected={tab === 'risks'} className={tab === 'risks' ? 'active' : ''} onClick={() => setTab('risks')}>Risk register <span>{data.risks.length}</span></button>
      </div>

      {tab === 'findings' ? (
        <>
          <div className="filter-bar" role="search">
            <Field label="Search findings" className="search-field"><Input value={search} onChange={(_, value) => setSearch(value.value)} contentBefore={<Search20Regular />} placeholder="ID, title, owner, or control" /></Field>
            <Field label="Status"><Select value={status} onChange={(_, value) => setStatus(value.value)}><option value="ALL">All statuses</option><option>OPEN</option><option>READY_FOR_RETEST</option><option>REOPENED</option><option>CLOSED</option><option>RISK_ACCEPTED</option></Select></Field>
            <Text size={200} className="filter-count">{filtered.length} workpapers</Text>
          </div>

          <div className={`master-detail ${selected ? 'detail-open' : ''}`}>
            <section className="table-card" aria-label="Findings">
              <div className="table-scroll" tabIndex={0} aria-label="Scrollable findings table">
                <table className="data-table responsive-record-table">
                  <thead><tr><th>Finding</th><th>Status</th><th>Severity</th><th>Affected control</th><th>Treatment</th><th>Owner</th><th>Target date</th><th>Retest</th></tr></thead>
                  <tbody>
                    {filtered.map((finding) => (
                      <tr key={finding.id} className={selected?.id === finding.id ? 'selected-row' : undefined}>
                        <td data-label="Finding"><button type="button" className="table-primary-link" onClick={() => { setSelected(finding); onNavigate('findings', finding.id); }}><strong>{finding.id}</strong><span>{finding.title}</span></button></td>
                        <td data-label="Status"><StatusBadge value={finding.status} subtle /></td>
                        <td data-label="Severity"><StatusBadge value={finding.severity} /></td>
                        <td data-label="Affected control">{finding.controlIds.map((id) => <button type="button" className="inline-link" key={id} onClick={() => onNavigate('controls', id)}>{id}</button>)}</td>
                        <td data-label="Treatment">{finding.treatment}</td><td data-label="Owner">{finding.owner}</td><td data-label="Target date">{formatDate(finding.targetDate)}</td>
                        <td data-label="Retest">{finding.retests.length ? <span className="evidence-count"><CheckmarkCircle20Regular /> {finding.retests.at(-1)?.result}</span> : 'Pending'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>

            {selected ? (
              <DetailPanel title={`${selected.id} · ${selected.title}`} subtitle={`${selected.asset} · opened ${formatDate(selected.openedAt)}`} onClose={() => { setSelected(undefined); onNavigate('findings'); }} actions={!publicMode ? (
                <div className="panel-button-row">
                  {selected.status === 'OPEN' || selected.status === 'REOPENED' ? <Button appearance="secondary" icon={<CalendarClock20Regular />} onClick={() => setDialog('exception')}>Create exception</Button> : null}
                  {selected.status === 'OPEN' || selected.status === 'REOPENED' ? <Button appearance="primary" onClick={openReadyDialog}>Mark ready for retest</Button> : null}
                  {selected.status === 'READY_FOR_RETEST' || selected.status === 'CLOSED' ? <Button appearance="primary" icon={<History20Regular />} onClick={() => setDialog('retest')}>Queue retest</Button> : null}
                  {reviewableRetest ? <Button appearance="primary" icon={<CheckmarkCircle20Regular />} onClick={() => setDialog('disposition')}>{latestRetest?.decision === 'CLOSE' ? 'Accept closure recommendation' : 'Accept reopen recommendation'}</Button> : null}
                </div>
              ) : <Text size={200} className="muted">Decision and run actions are unavailable in public mode.</Text>}>
                <div className="detail-status-row"><StatusBadge value={selected.status} /><StatusBadge value={selected.severity} /></div>
                <div className="finding-workpaper">
                  <section><Text weight="semibold">Criteria</Text><p>{selected.criteria}</p></section>
                  <section><Text weight="semibold">Condition</Text><p>{selected.condition}</p></section>
                  <section><Text weight="semibold">Cause</Text><p>{selected.cause}</p></section>
                  <section><Text weight="semibold">Consequence</Text><p>{selected.consequence}</p></section>
                </div>
                <section className="workpaper-section"><Text weight="semibold">Severity rationale</Text><p>{selected.severityRationale}</p></section>
                <div className="definition-grid"><div><Text size={200}>Treatment</Text><strong>{selected.treatment}</strong></div><div><Text size={200}>Owner</Text><strong>{selected.owner}</strong></div><div><Text size={200}>Target</Text><strong>{formatDate(selected.targetDate)}</strong></div><div><Text size={200}>Affected controls</Text><strong>{selected.controlIds.join(', ')}</strong></div></div>
                {selected.exception ? <section className="exception-card"><div><CalendarClock20Regular /><Text weight="semibold">Time-bounded exception</Text><StatusBadge value="RISK_ACCEPTED" subtle /></div><p>{selected.exception.rationale}</p><dl><dt>Compensating control</dt><dd>{selected.exception.compensatingControl}</dd><dt>Approver</dt><dd>{selected.exception.approver}</dd><dt>Expires</dt><dd>{formatDate(selected.exception.expiresAt)}</dd></dl></section> : null}
                <section className="workpaper-section"><Text weight="semibold">Remediation</Text><p>{selected.remediation}</p>{selected.remediationReference ? <span className="plain-chip">{selected.remediationReference}</span> : null}{selected.remediationRecordedBy ? <Text size={200}>Recorded by {selected.remediationRecordedBy}</Text> : null}<div className="chip-list">{selected.remediationEvidenceIds.map((id) => <Button key={id} appearance="outline" size="small" onClick={() => onNavigate('evidence', id)}>{id}</Button>)}</div></section>
                <section className="workpaper-section"><Text weight="semibold">Retest history</Text>{selected.retests.length ? <ol className="timeline-list">{selected.retests.map((retest) => <li key={`${retest.runId}-${retest.date}`}><span className="timeline-marker"><CheckmarkCircle20Regular /></span><div><div><StatusBadge value={retest.result} /><StatusBadge value={retest.reviewState} subtle /><strong>{formatDate(retest.date)}</strong></div><p><strong>{retest.decision} recommendation.</strong> {retest.rationale}</p><div className="chip-list">{retest.evidenceIds.map((id) => <Button key={id} appearance="outline" size="small" onClick={() => onNavigate('evidence', id)}>{id}</Button>)}</div></div></li>)}</ol> : <Text className="muted">No retest has been executed. The finding cannot be closed.</Text>}</section>
              </DetailPanel>
            ) : null}
          </div>
        </>
      ) : (
        <div className="risk-layout">
          <section className="table-card" aria-label="Risk register">
            <div className="table-scroll"><table className="data-table"><thead><tr><th>Risk</th><th>Cause-event-impact statement</th><th>Inherent</th><th>Residual</th><th>Confidence</th><th>Treatment</th><th>Owner</th></tr></thead><tbody>{data.risks.map((risk) => <tr key={risk.id}><td><strong>{risk.id}</strong><button type="button" className="inline-link block-link" onClick={() => { const finding = data.findings.find((item) => item.id === risk.findingId); setTab('findings'); setSelected(finding); onNavigate('findings', risk.findingId); }}>{risk.findingId}</button></td><td>{risk.statement}</td><td><StatusBadge value={scoreBand(risk.inherentScore)} /> <strong>{risk.inherentScore}/25</strong></td><td><StatusBadge value={scoreBand(risk.residualScore)} /> <strong>{risk.residualScore}/25</strong></td><td>{risk.confidence}</td><td>{risk.treatment}</td><td>{risk.owner}</td></tr>)}</tbody></table></div>
          </section>
          <aside className="risk-rubric" aria-label="Risk scoring rubric"><Text weight="semibold">5×5 scoring rubric</Text><div><span className="risk-low">1–4 Low</span><span className="risk-moderate">5–9 Moderate</span><span className="risk-high">10–16 High</span><span className="risk-critical">17–25 Critical</span></div><Text size={200}>Residual rating reflects treatment; it never changes the original observation.</Text></aside>
        </div>
      )}

      <ActionDialog open={dialog !== 'none'} title={dialog === 'retest' ? `Queue retest for ${selected?.id ?? ''}` : dialog === 'ready' ? 'Mark remediation ready for retest' : dialog === 'disposition' ? `Accept ${latestRetest?.decision.toLowerCase() ?? ''} recommendation` : 'Create time-bounded exception'} description={dialog === 'retest' ? 'A headless job will collect new evidence. This request cannot close the finding by itself.' : dialog === 'ready' ? 'Record ownership, the implemented action, commit or pull request, and proof from this signed run. A later retest and reviewer decision determine closure.' : dialog === 'disposition' ? 'Record the reviewer disposition of the latest signed retest recommendation. The underlying result and evidence remain immutable.' : 'An exception changes treatment only. It does not convert the failed test to a pass or erase the observation.'} confirmLabel={dialog === 'retest' ? 'Queue retest' : dialog === 'ready' ? 'Record readiness' : dialog === 'disposition' ? 'Record disposition' : 'Create exception'} pending={pending} confirmDisabled={!canSubmit} onClose={() => setDialog('none')} onConfirm={() => { if (canSubmit) void runCommand(); }}>
        {dialog !== 'retest' && dialog !== 'ready' ? <Field label="Rationale" required validationMessage={rationale.length > 0 && rationale.trim().length < 12 ? 'Provide at least 12 characters.' : undefined}><Textarea value={rationale} onChange={(_, value) => setRationale(value.value)} resize="vertical" /></Field> : null}
        {dialog === 'ready' ? <>
          <Field label="Remediation owner" required><Input value={remediationOwner} onChange={(_, value) => setRemediationOwner(value.value)} /></Field>
          <Field label="Remediation action" required validationMessage={remediationAction.length > 0 && remediationAction.trim().length < 12 ? 'Describe the implemented change in at least 12 characters.' : undefined}><Textarea value={remediationAction} onChange={(_, value) => setRemediationAction(value.value)} resize="vertical" /></Field>
          <Field label="Target date" required><Input type="date" value={remediationTargetDate} onChange={(_, value) => setRemediationTargetDate(value.value)} /></Field>
          <Field label="Commit or pull request" required><Input value={remediationReference} onChange={(_, value) => setRemediationReference(value.value)} /></Field>
          <Field label="Evidence IDs" required validationMessage={remediationEvidence.length > 0 && !remediationEvidenceValid ? 'Enter unique evidence IDs from this signed run, separated by commas.' : undefined}><Input list="remediation-evidence-ids" value={remediationEvidence} onChange={(_, value) => setRemediationEvidence(value.value)} placeholder="EVD-001, EVD-002" /></Field>
          <datalist id="remediation-evidence-ids">{data.evidence.map((item) => <option key={item.id} value={item.id} />)}</datalist>
        </> : null}
        {dialog === 'exception' ? <><Field label="Compensating control" required validationMessage={compensatingControl.length > 0 && compensatingControl.trim().length < 12 ? 'Describe a meaningful control in at least 12 characters.' : undefined}><Textarea value={compensatingControl} onChange={(_, value) => setCompensatingControl(value.value)} resize="vertical" /></Field><Field label="Expiry date" required><Input type="date" min={minimumExpiry} value={expiresAt} onChange={(_, value) => setExpiresAt(value.value)} /></Field></> : null}
        {!canSubmit ? <Text size={200} className="muted">Complete the required fields to enable a valid append-only lifecycle record.</Text> : null}
      </ActionDialog>
    </div>
  );
}
