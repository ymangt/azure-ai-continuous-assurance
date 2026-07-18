import { Text } from '@fluentui/react-components';
import { CheckmarkCircle16Regular, DismissCircle16Regular, ErrorCircle16Regular, Prohibited16Regular, SubtractCircle16Regular } from '@fluentui/react-icons';
import type { ResultStatus } from '../types';

interface ResultDistributionProps {
  values: Array<{ status: ResultStatus; count: number }>;
}

const statusIcons = {
  PASS: CheckmarkCircle16Regular,
  FAIL: DismissCircle16Regular,
  ERROR: ErrorCircle16Regular,
  NOT_RUN: SubtractCircle16Regular,
  NOT_APPLICABLE: Prohibited16Regular,
};

export function ResultDistribution({ values }: ResultDistributionProps) {
  const total = Math.max(values.reduce((sum, value) => sum + value.count, 0), 1);
  return (
    <div>
      <div className="distribution-bar" role="img" aria-label={values.map(({ status, count }) => `${status.replaceAll('_', ' ')}: ${count}`).join(', ')}>
        {values.map(({ status, count }) => count > 0 ? (
          <span key={status} className={`distribution-segment distribution-${status.toLowerCase().replaceAll('_', '-')}`} style={{ width: `${(count / total) * 100}%` }} />
        ) : null)}
      </div>
      <div className="distribution-legend">
        {values.map(({ status, count }) => {
          const Icon = statusIcons[status];
          return <div key={status} className={`distribution-legend-item distribution-${status.toLowerCase().replaceAll('_', '-')}`}><Icon aria-hidden="true" /><Text size={200}>{status.replaceAll('_', ' ')} <strong>{count}</strong></Text></div>;
        })}
      </div>
    </div>
  );
}
