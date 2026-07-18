import type { ReactNode } from 'react';
import { Card, Text, Title3 } from '@fluentui/react-components';

interface SectionCardProps {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function SectionCard({ title, description, action, children, className = '' }: SectionCardProps) {
  return (
    <Card className={`section-card ${className}`}>
      <div className="section-card-header">
        <div>
          <Title3 as="h2">{title}</Title3>
          {description ? <Text size={200} className="muted">{description}</Text> : null}
        </div>
        {action}
      </div>
      {children}
    </Card>
  );
}
