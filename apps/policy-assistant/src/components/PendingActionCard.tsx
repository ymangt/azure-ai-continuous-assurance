import { useState } from 'react';
import { Button, Checkbox, Spinner, Text } from '@fluentui/react-components';
import { Dismiss20Regular, LockClosed20Regular } from '@fluentui/react-icons';
import type { PendingException } from '../types';

interface PendingActionCardProps {
  proposal: PendingException;
  pending: boolean;
  replayMode: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export function PendingActionCard({ proposal, pending, replayMode, onCancel, onConfirm }: PendingActionCardProps) {
  const [confirmed, setConfirmed] = useState(false);
  return (
    <section className="pending-action" aria-labelledby={`proposal-${proposal.proposalId}`}>
      <div className="pending-action-header"><span><LockClosed20Regular /></span><div><Text id={`proposal-${proposal.proposalId}`} weight="semibold">Explicit confirmation required</Text><Text size={200}>No request has been created.</Text></div></div>
      <dl><div><dt>System</dt><dd>{proposal.system}</dd></div><div><dt>Requested access</dt><dd>{proposal.access}</dd></div><div><dt>Duration</dt><dd>{proposal.durationDays} days</dd></div><div><dt>Justification</dt><dd>{proposal.justification}</dd></div><div><dt>Policy</dt><dd>{proposal.policyReference}</dd></div></dl>
      <div className="confirmation-box">
        <Checkbox checked={confirmed} onChange={(_, data) => setConfirmed(Boolean(data.checked))} label={`I confirm this ${replayMode ? 'replay-only synthetic' : 'synthetic'} access-exception request.`} />
        <Text size={200}>Confirmation is bound to this proposal ID. Editing any field requires a new proposal.</Text>
      </div>
      <div className="pending-action-buttons"><Button appearance="secondary" icon={<Dismiss20Regular />} disabled={pending} onClick={onCancel}>Cancel</Button><Button appearance="primary" disabled={!confirmed || pending} onClick={onConfirm}>{pending ? <><Spinner size="tiny" /> Creating…</> : `Confirm and create ${replayMode ? 'replay request' : 'request'}`}</Button></div>
    </section>
  );
}
