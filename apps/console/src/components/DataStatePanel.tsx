import { Button, Card, Skeleton, SkeletonItem, Text, Title2 } from '@fluentui/react-components';
import { ArrowClockwise24Regular, CloudDismiss24Regular, FolderOpen24Regular } from '@fluentui/react-icons';

interface DataStatePanelProps {
  state: 'loading' | 'empty' | 'error';
  message?: string;
  onRetry?: () => void;
}

export function DataStatePanel({ state, message, onRetry }: DataStatePanelProps) {
  if (state === 'loading') {
    return (
      <div className="state-grid" aria-label="Loading assurance data" aria-busy="true">
        {[1, 2, 3, 4].map((item) => (
          <Card key={item} className="loading-card">
            <Skeleton><SkeletonItem size={16} /><SkeletonItem size={36} /><SkeletonItem size={12} /></Skeleton>
          </Card>
        ))}
      </div>
    );
  }

  const isError = state === 'error';
  return (
    <Card className="state-panel" role={isError ? 'alert' : 'status'}>
      {isError ? <CloudDismiss24Regular /> : <FolderOpen24Regular />}
      <Title2 as="h2">{isError ? 'Assurance data is unavailable' : 'No assessment data yet'}</Title2>
      <Text>{message ?? (isError ? 'The current snapshot could not be loaded.' : 'Queue an assessment to create the first signed evidence package.')}</Text>
      {isError && onRetry ? <Button appearance="primary" icon={<ArrowClockwise24Regular />} onClick={onRetry}>Try again</Button> : null}
    </Card>
  );
}
