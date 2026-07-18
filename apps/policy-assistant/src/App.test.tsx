import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import { App } from './App';
import { assistantApi } from './api/client';

describe('Policy Assistant', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/');
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows grounded sources and audit identifiers on the representative answer', () => {
    render(<App />);
    expect(screen.getByText('2 grounded sources')).toBeInTheDocument();
    expect(screen.getByText('POL-002')).toBeInTheDocument();
    expect(screen.getByText('corr-814f93e1')).toBeInTheDocument();
    expect(screen.getByText('eval-GRD-003')).toBeInTheDocument();
    expect(screen.getByText(/read-only trusted metadata/i)).toBeInTheDocument();
    expect(document.querySelector('.assistant-provider')).not.toHaveClass('fui-FluentProvider');
  });

  it('does not execute the consequential tool before proposal-specific confirmation', async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(assistantApi, 'confirmException');
    render(<App />);

    await user.selectOptions(screen.getByLabelText('Replay scenario'), 'exception');
    await user.click(screen.getByRole('button', { name: 'Run replay' }));
    expect(await screen.findByText('Explicit confirmation required')).toBeInTheDocument();

    const confirmButton = screen.getByRole('button', { name: 'Confirm and create replay request' });
    expect(confirmButton).toBeDisabled();
    expect(confirmSpy).not.toHaveBeenCalled();

    await user.click(screen.getByRole('checkbox', { name: /I confirm this replay-only synthetic access-exception request/ }));
    expect(confirmButton).toBeEnabled();
    expect(confirmSpy).not.toHaveBeenCalled();

    await user.click(confirmButton);
    expect(await screen.findByText(/was created after explicit confirmation/)).toBeInTheDocument();
    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/grants no access/)).toBeInTheDocument();
  });

  it('performs a read-only policy metadata lookup', async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole('button', { name: 'Look up policy' }));
    expect(await screen.findByText('Identity Governance Owner')).toBeInTheDocument();
    expect(screen.getByText(/cannot create or approve anything/i)).toBeInTheDocument();
  });

  it('shows an unavailable state without fabricating a fallback answer', () => {
    window.history.replaceState(null, '', '/?state=error');
    render(<App />);
    expect(screen.getByRole('alert')).toHaveTextContent('No fallback answer was generated');
  });
});
