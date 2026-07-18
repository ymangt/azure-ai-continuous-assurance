import { Button, Card, Skeleton, SkeletonItem, Text, Title2 } from '@fluentui/react-components';
import { ArrowClockwise24Regular, CloudDismiss24Regular, FolderOpen24Regular, Play24Regular } from '@fluentui/react-icons';
import type { AppView } from '../types';

interface DataStatePanelProps {
  state: 'loading' | 'empty' | 'error';
  message?: string;
  onRetry?: () => void;
  onQueueAssessment?: () => void;
  view?: AppView;
}

export function DataStatePanel({ state, message, onRetry, onQueueAssessment, view = 'overview' }: DataStatePanelProps) {
  if (state === 'loading') {
    if (view !== 'overview') {
      return (
        <div className="table-loading-state" aria-label={`Loading ${view} data`} aria-busy="true">
          <Skeleton><SkeletonItem className="loading-heading" /><SkeletonItem className="loading-copy" /></Skeleton>
          <Card className="loading-table-card">
            <Skeleton>
              <SkeletonItem className="loading-filter" />
              {[1, 2, 3, 4, 5].map((item) => <SkeletonItem key={item} className="loading-row" />)}
            </Skeleton>
          </Card>
        </div>
      );
    }
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
      {!isError && onQueueAssessment ? <Button appearance="primary" icon={<Play24Regular />} onClick={onQueueAssessment}>Queue assessment</Button> : null}
    </Card>
  );
}
