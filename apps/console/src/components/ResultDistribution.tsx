import { Text } from '@fluentui/react-components';
import type { ResultStatus } from '../types';

interface ResultDistributionProps {
  values: Array<{ status: ResultStatus; count: number }>;
}

const colors: Record<ResultStatus, string> = {
  PASS: '#0e7a5f',
  FAIL: '#c4314b',
  ERROR: '#8f2e00',
  NOT_RUN: '#60748a',
  NOT_APPLICABLE: '#b6c0cc',
};

export function ResultDistribution({ values }: ResultDistributionProps) {
  const total = Math.max(values.reduce((sum, value) => sum + value.count, 0), 1);
  return (
    <div>
      <div className="distribution-bar" role="img" aria-label={values.map(({ status, count }) => `${status.replaceAll('_', ' ')}: ${count}`).join(', ')}>
        {values.map(({ status, count }) => count > 0 ? (
          <span key={status} style={{ width: `${(count / total) * 100}%`, backgroundColor: colors[status] }} />
        ) : null)}
      </div>
      <div className="distribution-legend">
        {values.map(({ status, count }) => (
          <div key={status}><span className="legend-dot" style={{ backgroundColor: colors[status] }} /><Text size={200}>{status.replaceAll('_', ' ')} <strong>{count}</strong></Text></div>
        ))}
      </div>
    </div>
  );
}
