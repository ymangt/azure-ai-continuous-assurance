import { useState, type ReactNode } from 'react';
import { Button, Text, Title3, Tooltip } from '@fluentui/react-components';
import {
  BrainCircuit24Regular,
  CheckmarkCircle24Regular,
  DataUsage24Regular,
  DocumentData24Regular,
  History24Regular,
  Home24Regular,
  LockClosed20Regular,
  Navigation24Regular,
  Organization24Regular,
  Play24Regular,
  ShieldLock24Regular,
  Warning24Regular,
} from '@fluentui/react-icons';
import { formatDateTime } from '../format';
import type { AppView, AssessmentRun } from '../types';
import { StatusBadge } from './StatusBadge';

interface AppShellProps {
  view: AppView;
  publicMode: boolean;
  activeRun?: AssessmentRun;
  stale: boolean;
  commandMessage?: string;
  onNavigate: (view: AppView) => void;
  onQueueAssessment: () => void;
  children: ReactNode;
}

const navigation = [
  { id: 'overview', label: 'Overview', icon: Home24Regular },
  { id: 'controls', label: 'Controls', icon: CheckmarkCircle24Regular },
  { id: 'evidence', label: 'Evidence', icon: DocumentData24Regular },
  { id: 'findings', label: 'Findings & Risks', icon: Warning24Regular },
  { id: 'runs', label: 'Assessment Runs', icon: History24Regular },
  { id: 'evaluations', label: 'AI Evaluations', icon: BrainCircuit24Regular },
  { id: 'system', label: 'System', icon: Organization24Regular },
] as const;

export function AppShell({ view, publicMode, activeRun, stale, commandMessage, onNavigate, onQueueAssessment, children }: AppShellProps) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const commandError = Boolean(commandMessage && /failed|could not|denied|unavailable/i.test(commandMessage));

  const navigate = (nextView: AppView) => {
    onNavigate(nextView);
    setMobileOpen(false);
  };

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
        <div className="brand">
          <span className="brand-mark" aria-hidden="true"><ShieldLock24Regular /></span>
          <div>
            <Title3 as="p">Continuous Assurance</Title3>
            <Text size={200}>Azure AI</Text>
          </div>
        </div>
        <nav aria-label="Primary navigation" className="side-nav">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button key={id} type="button" className={`nav-item ${view === id ? 'nav-item-active' : ''}`} aria-current={view === id ? 'page' : undefined} onClick={() => navigate(id)}>
              <Icon aria-hidden="true" />
              <span>{label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className="mode-card">
            {publicMode ? <DataUsage24Regular /> : <LockClosed20Regular />}
            <div>
              <Text weight="semibold">{publicMode ? 'Public snapshot' : 'Private workspace'}</Text>
              <Text size={200}>{publicMode ? 'Sanitized · read-only' : 'Entra authenticated'}</Text>
            </div>
          </div>
          <Text size={100}>Internal readiness assessment<br />Not a certification</Text>
        </div>
      </aside>

      {mobileOpen ? <button type="button" className="sidebar-scrim" aria-label="Close navigation" onClick={() => setMobileOpen(false)} /> : null}

      <div className="app-frame">
        <header className="topbar">
          <Button className="mobile-menu" appearance="subtle" icon={<Navigation24Regular />} aria-label="Open navigation" onClick={() => setMobileOpen(true)} />
          <div className="run-context">
            <Text size={200}>Assessment context</Text>
            <div className="run-title-row">
              <Text weight="semibold">{activeRun?.label ?? 'Loading signed snapshot'}</Text>
              {activeRun ? <StatusBadge value={activeRun.status} subtle /> : null}
              {stale ? <StatusBadge value="STALE" /> : null}
            </div>
            {activeRun ? <Text size={100} className="muted">Completed {formatDateTime(activeRun.completedAt)} · {activeRun.shortId}</Text> : null}
          </div>
          <div className="topbar-actions">
            {!publicMode ? (
              <Tooltip content="Queues a headless assessment; the browser does not evaluate controls." relationship="description">
                <Button appearance="primary" icon={<Play24Regular />} onClick={onQueueAssessment}>Queue assessment</Button>
              </Tooltip>
            ) : (
              <div className="public-pill"><LockClosed20Regular /><span>Actions unavailable in public mode</span></div>
            )}
          </div>
        </header>

        {commandMessage ? <div className={commandError ? 'command-error-banner' : 'command-banner'} role={commandError ? 'alert' : 'status'}>{commandError ? <Warning24Regular /> : <CheckmarkCircle24Regular />}<span>{commandMessage}</span></div> : null}
        {stale ? <div className="stale-banner" role="alert"><Warning24Regular /><span>This snapshot is stale. No current control conclusion should be inferred until collection succeeds.</span></div> : null}
        <main id="main-content" className="main-content" tabIndex={-1}>{children}</main>
      </div>
    </div>
  );
}
