import { Badge } from '@fluentui/react-components';
import type { BadgeProps } from '@fluentui/react-components';

interface StatusBadgeProps {
  value: string;
  subtle?: boolean;
}

const colors: Record<string, BadgeProps['color']> = {
  PASS: 'success', EFFECTIVE: 'success', CURRENT: 'success', COMPLETED: 'success', CLOSED: 'success', ACCEPTED: 'success', RESOLVED: 'success',
  FAIL: 'danger', INEFFECTIVE: 'danger', CRITICAL: 'danger', HIGH: 'danger', ERROR: 'danger', FAILED: 'danger', REGRESSED: 'danger', REJECTED: 'danger',
  MODERATE: 'warning', PARTIALLY_EFFECTIVE: 'warning', STALE: 'warning', RUNNING: 'warning', READY_FOR_RETEST: 'warning', SUGGESTED: 'warning',
  LOW: 'informative', QUEUED: 'informative', NOT_RUN: 'informative', NOT_CONCLUDED: 'informative', UNAVAILABLE: 'informative', RISK_ACCEPTED: 'informative', NEW: 'informative',
  NOT_APPLICABLE: 'subtle', SANITIZED: 'success', PRIVATE_ONLY: 'important', INTERNAL: 'informative', CONFIDENTIAL: 'warning', PUBLIC: 'success',
};

export function StatusBadge({ value, subtle = false }: StatusBadgeProps) {
  const label = value.replaceAll('_', ' ').toLowerCase().replace(/^\w/, (letter) => letter.toUpperCase());
  return (
    <Badge appearance={subtle ? 'tint' : 'filled'} color={colors[value] ?? 'informative'} size="small">
      {label}
    </Badge>
  );
}
