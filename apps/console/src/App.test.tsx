import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App } from './App';

describe('Assurance Console', () => {
  beforeEach(() => {
    window.history.replaceState(null, '', '/');
  });

  it('renders an evidence-backed overview and the non-certification boundary', async () => {
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Assurance overview' })).toBeInTheDocument();
    expect(screen.getByText('Internal readiness assessment — not certification')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Queue assessment/i })).toBeInTheDocument();
    expect(screen.getByText('Criteria-to-retest trace')).toBeInTheDocument();
    expect(document.querySelector('.provider-root')).not.toHaveClass('fui-FluentProvider');
  });

  it('navigates from controls to linked evidence in two interactions', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: 'Assurance overview' });

    await user.click(screen.getByRole('button', { name: 'Controls' }));
    expect(await screen.findByRole('heading', { name: 'Controls' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /SC-7.1/ }));
    await user.click(screen.getByRole('button', { name: 'EVD-R-008' }));

    expect(await screen.findByRole('heading', { name: 'Evidence' })).toBeInTheDocument();
    expect(await screen.findByRole('complementary', { name: /EVD-R-008 details/ })).toBeInTheDocument();
  });

  it('opens a control criteria preview from the overview trace before navigating', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: 'Assurance overview' });

    await user.click(screen.getByRole('button', { name: /Control criteria/i }));
    expect(await screen.findByRole('heading', { name: 'Control criteria preview' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Assurance overview' })).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Open full control' }));
    expect(await screen.findByRole('heading', { name: 'Controls' })).toBeInTheDocument();
    expect(await screen.findByRole('complementary', { name: /SC-7\.1 details/ })).toBeInTheDocument();
  });

  it('opens metric and finding previews from the overview before navigating', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: 'Assurance overview' });

    await user.click(screen.getByRole('button', { name: /Test coverage/i }));
    expect(await screen.findByRole('heading', { name: 'Test coverage preview' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Stay on overview' }));
    expect(screen.queryByRole('heading', { name: 'Test coverage preview' })).not.toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /FND-001 · FND-001/i }));
    expect(await screen.findByRole('heading', { name: 'Finding preview' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open finding' }));
    expect(await screen.findByRole('heading', { name: 'Findings & risks' })).toBeInTheDocument();
  });

  it('opens an evidence preview from the criteria-to-retest chain', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: 'Assurance overview' });

    await user.click(screen.getByRole('button', { name: /Evidence SHA-256/i }));
    expect(await screen.findByRole('heading', { name: 'Evidence preview' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Open evidence' }));
    expect(await screen.findByRole('heading', { name: 'Evidence' })).toBeInTheDocument();
  });

  it('removes all mutating actions from public mode', async () => {
    window.history.replaceState(null, '', '/?mode=public');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Assurance overview' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Queue assessment/i })).not.toBeInTheDocument();
    expect(screen.getByText('Actions unavailable in public mode')).toBeInTheDocument();
  });

  it('does not infer a current conclusion from a stale snapshot', async () => {
    window.history.replaceState(null, '', '/?state=stale');
    render(<App />);
    expect(await screen.findByText(/This snapshot is stale/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getAllByText('Stale').length).toBeGreaterThan(0));
  });

  it('renders a recoverable unavailable state', async () => {
    window.history.replaceState(null, '', '/?state=error');
    render(<App />);
    expect(await screen.findByRole('heading', { name: 'Assurance data is unavailable' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument();
  });

  it('renders the system record carried by the selected signed package', async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole('heading', { name: 'Assurance overview' });
    await user.click(screen.getByRole('button', { name: 'System' }));
    expect(await screen.findByRole('heading', { name: 'Azure AI Continuous Assurance' })).toBeInTheDocument();
    expect(screen.getByText('Assessed boundary architecture')).toBeInTheDocument();
    expect(screen.getByText('Declared system inventory')).toBeInTheDocument();
    expect(screen.getByText(/not an assertion that every component is currently deployed/i)).toBeInTheDocument();
    expect(screen.getByText('Data flows')).toBeInTheDocument();
    expect(screen.getByText('Explicit exclusions')).toBeInTheDocument();
    expect(screen.getByText('F-07')).toBeInTheDocument();
  });
});
