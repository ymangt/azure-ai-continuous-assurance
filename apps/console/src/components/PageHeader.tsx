import type { ReactNode } from 'react';
import { Text, Title1 } from '@fluentui/react-components';

interface PageHeaderProps {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div>
        <Text className="eyebrow">{eyebrow}</Text>
        <Title1 as="h1">{title}</Title1>
        <Text className="page-description">{description}</Text>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}
