import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { assuranceApi } from '../api/client';
import { cloneSnapshot } from '../mockData';
import { ControlsScreen } from './ControlsScreen';
import { FindingsScreen } from './FindingsScreen';

const receipt = {
  request_id: 'cmd-version-test',
  status: 'QUEUED' as const,
  version: 1,
  received_at: '2026-06-08T12:30:00Z',
};

describe('projected review versions', () => {
  afterEach(() => vi.restoreAllMocks());

  it('uses the control review version for a reviewer conclusion', async () => {
    const user = userEvent.setup();
    const snapshot = cloneSnapshot();
    const control = snapshot.controls.find((item) => item.id === 'SC-7.1');
    if (!control) throw new Error('SC-7.1 is missing from the checked-in sample');
    control.reviewVersion = 7;
    const recordDecision = vi.spyOn(assuranceApi, 'recordDecision').mockResolvedValue(receipt);

    render(<ControlsScreen data={snapshot} publicMode={false} onNavigate={() => undefined} onCommand={() => undefined} />);
    await user.click(screen.getByRole('button', { name: /SC-7.1/ }));
    await user.click(screen.getByRole('button', { name: 'Record reviewer conclusion' }));
    const dialog = screen.getByRole('dialog');
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Reviewer rationale' }), {
      target: { value: 'Fresh evidence supports this recorded conclusion.' },
    });
    const submit = within(dialog).getByRole('button', { name: 'Record decision', hidden: true });
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);

    await waitFor(() => expect(recordDecision).toHaveBeenCalledWith(expect.objectContaining({ expected_version: 7, artifact_run_id: snapshot.selectedRun.id })));
  });

  it('uses the finding review version for a new exception command', async () => {
    const user = userEvent.setup();
    const snapshot = cloneSnapshot();
    const finding = snapshot.findings.find((item) => item.id === 'FND-005');
    if (!finding) throw new Error('FND-005 is missing from the checked-in sample');
    finding.reviewVersion = 9;
    const createException = vi.spyOn(assuranceApi, 'createException').mockResolvedValue(receipt);

    render(<FindingsScreen data={snapshot} publicMode={false} onNavigate={() => undefined} onCommand={() => undefined} />);
    await user.click(screen.getByRole('button', { name: /FND-005/ }));
    await user.click(screen.getByRole('button', { name: 'Create exception' }));
    const dialog = screen.getByRole('dialog');
    const expiry = within(dialog).getByLabelText(/Expiry date/) as HTMLInputElement;
    const today = new Date().toISOString().slice(0, 10);
    expect(expiry.value > today).toBe(true);
    expect(expiry.min > today).toBe(true);
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Rationale' }), {
      target: { value: 'A bounded synthetic exception remains necessary.' },
    });
    fireEvent.change(within(dialog).getByRole('textbox', { name: 'Compensating control' }), {
      target: { value: 'Daily review of content-minimized security events.' },
    });
    const submit = within(dialog).getByRole('button', { name: 'Create exception', hidden: true });
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);

    await waitFor(() => expect(createException).toHaveBeenCalledWith(expect.objectContaining({ expected_version: 9, artifact_run_id: snapshot.selectedRun.id })));
  });
});
