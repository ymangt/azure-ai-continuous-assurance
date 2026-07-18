import type { ReactNode } from 'react';
import { Card, Text, Title2 } from '@fluentui/react-components';

interface MetricCardProps {
  label: string;
  value: string | number;
  detail: string;
  tone?: 'default' | 'good' | 'warning' | 'danger';
  icon?: ReactNode;
  onClick?: () => void;
}

export function MetricCard({ label, value, detail, tone = 'default', icon, onClick }: MetricCardProps) {
  const content = (
    <>
      <div className="metric-label-row">
        <Text weight="semibold">{label}</Text>
        {icon}
      </div>
      <Title2 as="p" className="metric-value">{value}</Title2>
      <Text size={200} className="muted">{detail}</Text>
    </>
  );
  return onClick ? (
    <button type="button" className="metric-button" onClick={onClick}><Card className={`metric-card metric-${tone}`}>{content}</Card></button>
  ) : (
    <Card className={`metric-card metric-${tone}`}>{content}</Card>
  );
}
