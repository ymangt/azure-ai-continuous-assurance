import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { Field, FluentProvider, Select, Text } from '@fluentui/react-components';
import { webLightTheme } from '@fluentui/react-components';
import { assuranceApi } from './api/client';
import { useConsoleSnapshot } from './api/useConsoleSnapshot';
import { ActionDialog } from './components/ActionDialog';
import { AppShell } from './components/AppShell';
import { DataStatePanel } from './components/DataStatePanel';
import type { AppView, CommandFeedback, CommandFeedbackInput, DemoDataState } from './types';

const ControlsScreen = lazy(() => import('./screens/ControlsScreen').then((module) => ({ default: module.ControlsScreen })));
const EvaluationsScreen = lazy(() => import('./screens/EvaluationsScreen').then((module) => ({ default: module.EvaluationsScreen })));
const EvidenceScreen = lazy(() => import('./screens/EvidenceScreen').then((module) => ({ default: module.EvidenceScreen })));
const FindingsScreen = lazy(() => import('./screens/FindingsScreen').then((module) => ({ default: module.FindingsScreen })));
const OverviewScreen = lazy(() => import('./screens/OverviewScreen').then((module) => ({ default: module.OverviewScreen })));
const RunsScreen = lazy(() => import('./screens/RunsScreen').then((module) => ({ default: module.RunsScreen })));
const SystemScreen = lazy(() => import('./screens/SystemScreen').then((module) => ({ default: module.SystemScreen })));

const validViews: AppView[] = ['overview', 'controls', 'evidence', 'findings', 'runs', 'evaluations', 'system'];
const validDemoStates: DemoDataState[] = ['ready', 'loading', 'empty', 'error', 'stale'];

interface AppRoute {
  view: AppView;
  focusId?: string;
}

function readRoute(): AppRoute {
  const [rawView, rawFocusId] = window.location.hash.replace('#', '').split('/');
  const view = validViews.includes(rawView as AppView) ? rawView as AppView : 'overview';
  const supportsFocus = view === 'controls' || view === 'evidence' || view === 'findings';
  if (!supportsFocus || !rawFocusId) return { view };
  try {
    return { view, focusId: decodeURIComponent(rawFocusId) };
  } catch {
    return { view };
  }
}

function readDemoState(): DemoDataState {
  const value = new URLSearchParams(window.location.search).get('state') as DemoDataState | null;
  return value && validDemoStates.includes(value) ? value : 'ready';
}

export function App() {
  const [route, setRoute] = useState<AppRoute>(readRoute);
  const [queueOpen, setQueueOpen] = useState(false);
  const [scope, setScope] = useState('full-approved-scope');
  const [pending, setPending] = useState(false);
  const [commandFeedback, setCommandFeedback] = useState<CommandFeedback>();
  const feedbackId = useRef(0);
  const { view, focusId } = route;
  const demoState = readDemoState();
  const publicMode = import.meta.env.VITE_PUBLIC_MODE === 'true' || new URLSearchParams(window.location.search).get('mode') === 'public';
  const snapshot = useConsoleSnapshot(demoState);

  useEffect(() => {
    const onHashChange = () => {
      setRoute(readRoute());
    };
    window.addEventListener('hashchange', onHashChange);
    window.addEventListener('popstate', onHashChange);
    return () => {
      window.removeEventListener('hashchange', onHashChange);
      window.removeEventListener('popstate', onHashChange);
    };
  }, []);

  const reportCommand = (feedback: CommandFeedbackInput) => {
    feedbackId.current += 1;
    setCommandFeedback({ ...feedback, id: feedbackId.current });
  };

  const navigate = (nextView: AppView, id?: string) => {
    const viewChanged = nextView !== view;
    const nextHash = `#${nextView}${id ? `/${encodeURIComponent(id)}` : ''}`;
    setRoute({ view: nextView, focusId: id });
    if (window.location.hash !== nextHash) window.history.pushState(null, '', nextHash);
    if (viewChanged) {
      window.scrollTo(0, 0);
      window.requestAnimationFrame(() => document.querySelector<HTMLElement>('#main-content')?.focus({ preventScroll: true }));
    }
  };

  const queueAssessment = async () => {
    setPending(true);
    try {
      const receipt = await assuranceApi.queueRun(scope);
      reportCommand({ intent: 'success', message: `Assessment ${receipt.request_id.slice(0, 8)} queued. Collection and evaluation will run headlessly.` });
      setQueueOpen(false);
    } catch (error) {
      reportCommand({ intent: 'error', message: error instanceof Error ? error.message : 'The assessment request could not be queued.' });
    } finally {
      setPending(false);
    }
  };

  const renderScreen = () => {
    if (snapshot.loading) return <DataStatePanel state="loading" view={view} />;
    if (snapshot.error) return <DataStatePanel state="error" message={snapshot.error.message} onRetry={snapshot.reload} />;
    if (!snapshot.data) return <DataStatePanel state="empty" onQueueAssessment={!publicMode ? () => setQueueOpen(true) : undefined} />;
    if (!snapshot.data.runs.length) return <DataStatePanel state="empty" onQueueAssessment={!publicMode ? () => setQueueOpen(true) : undefined} />;

    const common = { data: snapshot.data };
    switch (view) {
      case 'controls': return <ControlsScreen {...common} publicMode={publicMode} focusId={focusId} onNavigate={navigate} onCommand={reportCommand} />;
      case 'evidence': return <EvidenceScreen {...common} publicMode={publicMode} focusId={focusId} onNavigate={navigate} onCommand={reportCommand} />;
      case 'findings': return <FindingsScreen {...common} publicMode={publicMode} focusId={focusId} onNavigate={navigate} onCommand={reportCommand} />;
      case 'runs': return <RunsScreen {...common} publicMode={publicMode} onNavigate={navigate} onCommand={reportCommand} />;
      case 'evaluations': return <EvaluationsScreen {...common} publicMode={publicMode} onNavigate={navigate} onCommand={reportCommand} />;
      case 'system': return <SystemScreen {...common} />;
      default: return <OverviewScreen {...common} onNavigate={navigate} />;
    }
  };

  return (
    <FluentProvider theme={webLightTheme}>
      <div className="provider-root">
        <AppShell
          view={view}
          publicMode={publicMode}
          activeRun={snapshot.data?.selectedRun}
          stale={demoState === 'stale'}
          commandFeedback={commandFeedback}
          onDismissCommand={() => setCommandFeedback(undefined)}
          onNavigate={navigate}
          onQueueAssessment={() => setQueueOpen(true)}
        >
          <Suspense fallback={<DataStatePanel state="loading" view={view} />}>{renderScreen()}</Suspense>
        </AppShell>

        {!publicMode ? (
          <ActionDialog open={queueOpen} title="Queue an assessment" description="This records a request for the independent collector/evaluator job. The browser does not collect evidence or determine a verdict." confirmLabel="Queue assessment" pending={pending} onClose={() => setQueueOpen(false)} onConfirm={() => void queueAssessment()}>
            <Field label="Approved scope"><Select value={scope} onChange={(_, value) => setScope(value.value)}><option value="full-approved-scope">Full approved scope</option><option value="policy-assistant">Policy Assistant only</option><option value="assurance-plane">Assurance plane only</option></Select></Field>
            <div className="dialog-summary"><Text size={200}>Trigger</Text><strong>Manual</strong><Text size={200}>Expected behavior</Text><strong>Collect → normalize → evaluate → assess → sign</strong><Text size={200}>Estimated ceiling</Text><strong>CAD $0.50</strong></div>
          </ActionDialog>
        ) : null}
      </div>
    </FluentProvider>
  );
}
