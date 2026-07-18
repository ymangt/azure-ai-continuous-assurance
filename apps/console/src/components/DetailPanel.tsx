import type { ReactNode } from 'react';
import { Button, Text, Title2 } from '@fluentui/react-components';
import { Dismiss24Regular } from '@fluentui/react-icons';

interface DetailPanelProps {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: ReactNode;
  actions?: ReactNode;
}

export function DetailPanel({ title, subtitle, onClose, children, actions }: DetailPanelProps) {
  return (
    <aside className="detail-panel" aria-label={`${title} details`}>
      <div className="detail-panel-header">
        <div>
          <Title2 as="h2">{title}</Title2>
          {subtitle ? <Text className="muted">{subtitle}</Text> : null}
        </div>
        <Button appearance="subtle" icon={<Dismiss24Regular />} aria-label="Close details" onClick={onClose} />
      </div>
      <div className="detail-panel-body">{children}</div>
      {actions ? <div className="detail-panel-actions">{actions}</div> : null}
    </aside>
  );
}
