import { render, screen } from '@testing-library/react';
import { cloneSnapshot } from '../mockData';
import { OverviewScreen } from './OverviewScreen';

describe('Overview evidence metric', () => {
  it('does not treat zero evidence as all current', () => {
    const snapshot = cloneSnapshot();
    snapshot.evidence = [];

    render(<OverviewScreen data={snapshot} onNavigate={() => undefined} />);

    expect(screen.getByRole('button', { name: /Current evidence/i })).toHaveTextContent('0/0');
    expect(screen.getByText('No evidence available')).toBeInTheDocument();
    expect(screen.queryByText(/All current/)).not.toBeInTheDocument();
    expect(document.querySelector('.metric-warning')).toBeInTheDocument();
  });
});
