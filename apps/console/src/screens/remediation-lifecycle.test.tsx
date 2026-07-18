import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { assuranceApi } from '../api/client';
import { cloneSnapshot } from '../mockData';
import { FindingsScreen } from './FindingsScreen';

describe('remediation lifecycle command', () => {
  afterEach(() => vi.restoreAllMocks());

  it('captures implementation proof and binds it to the selected signed run', async () => {
    const user = userEvent.setup();
    const snapshot = cloneSnapshot();
    const finding = snapshot.findings.find((item) => item.id === 'FND-005');
    if (!finding) throw new Error('FND-005 is missing from the checked-in sample');
    finding.reviewVersion = 5;
    const evidenceId = snapshot.evidence[0].id;
    const createRemediation = vi.spyOn(assuranceApi, 'createRemediation').mockResolvedValue({
      request_id: 'cmd-remediation', status: 'QUEUED', version: 6, received_at: '2026-07-17T12:00:00Z',
    });

    render(<FindingsScreen data={snapshot} publicMode={false} onNavigate={() => undefined} onCommand={() => undefined} />);
    await user.click(screen.getByRole('button', { name: /FND-005/ }));
    await user.click(screen.getByRole('button', { name: 'Mark ready for retest' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/Remediation owner/), { target: { value: 'Cloud Owner' } });
    fireEvent.change(within(dialog).getByLabelText(/Remediation action/), { target: { value: 'Remove the broad ingress rule through reviewed infrastructure code.' } });
    fireEvent.change(within(dialog).getByLabelText(/Commit or pull request/), { target: { value: 'PR-101' } });
    fireEvent.change(within(dialog).getByLabelText(/Evidence IDs/), { target: { value: evidenceId } });
    await user.click(within(dialog).getByRole('button', { name: 'Record readiness', hidden: true }));

    await waitFor(() => expect(createRemediation).toHaveBeenCalledWith(expect.objectContaining({
      finding_id: 'FND-005',
      artifact_run_id: snapshot.selectedRun.id,
      owner: 'Cloud Owner',
      commit_or_pr: 'PR-101',
      evidence_refs: [evidenceId],
      expected_version: 5,
    })));
  });
});
