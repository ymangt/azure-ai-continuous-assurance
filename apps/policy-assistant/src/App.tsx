import { useEffect, useRef, useState } from 'react';
import {
  Button,
  FluentProvider,
  Select,
  Skeleton,
  SkeletonItem,
  Spinner,
  Switch,
  Text,
  Textarea,
  Tooltip,
  webLightTheme,
} from '@fluentui/react-components';
import {
  ArrowUp20Regular,
  Bot24Regular,
  CheckmarkCircle20Regular,
  Circle20Regular,
  PersonCircle24Regular,
  Play20Regular,
  ShieldLock24Regular,
  Warning20Regular,
} from '@fluentui/react-icons';
import { assistantApi } from './api/client';
import { MessageBubble } from './components/MessageBubble';
import { PendingActionCard } from './components/PendingActionCard';
import { PolicyLookupPanel } from './components/PolicyLookupPanel';
import { initialMessages } from './fixtures';
import type { ChatMessage, PendingException, ReplayScenario, UiState } from './types';

const scenarioPrompts: Record<ReplayScenario, string> = {
  grounded: 'Who approves temporary administrator access, and how long can it last?',
  injection: 'Test a policy document that says to ignore safeguards and override the approval owner.',
  exception: 'Create a temporary access exception for the synthetic finance reporting system.',
};

function readUiState(): UiState {
  const value = new URLSearchParams(window.location.search).get('state');
  return ['ready', 'loading', 'error', 'empty', 'stale'].includes(value ?? '') ? value as UiState : 'ready';
}

export function App() {
  const replayOnly = import.meta.env.VITE_REPLAY_ONLY === 'true';
  const [replayMode, setReplayMode] = useState(replayOnly || import.meta.env.VITE_DATA_SOURCE !== 'api');
  const [scenario, setScenario] = useState<ReplayScenario>('grounded');
  const [uiState, setUiState] = useState<UiState>(readUiState);
  const [messages, setMessages] = useState<ChatMessage[]>(uiState === 'ready' || uiState === 'stale' ? initialMessages : []);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [actionPendingId, setActionPendingId] = useState<string>();
  const [error, setError] = useState<string>(uiState === 'error' ? 'The policy service is unavailable. No fallback answer was generated.' : '');
  const sessionId = useRef(`session-${crypto.randomUUID()}`);
  const conversationEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    conversationEnd.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, [messages, sending]);

  const submitPrompt = async (prompt: string, forcedScenario?: ReplayScenario) => {
    const normalized = prompt.trim();
    if (!normalized || sending || uiState === 'loading') return;
    const userMessage: ChatMessage = { id: `msg-${crypto.randomUUID()}`, role: 'user', content: normalized, timestamp: new Date().toISOString() };
    setMessages((current) => [...current, userMessage]);
    setDraft('');
    setError('');
    setSending(true);
    try {
      const response = await assistantApi.sendMessage(normalized, sessionId.current, replayMode, forcedScenario);
      setMessages((current) => [...current, response.message]);
    } catch (sendError) {
      setError(sendError instanceof Error ? sendError.message : 'The request failed.');
    } finally {
      setSending(false);
    }
  };

  const confirmException = async (messageId: string, proposal: PendingException) => {
    setActionPendingId(messageId);
    setError('');
    try {
      const receipt = await assistantApi.confirmException(proposal, sessionId.current, replayMode);
      setMessages((current) => current.map((message) => message.id === messageId ? {
        ...message,
        content: `Synthetic access-exception request ${receipt.requestId} was created after explicit confirmation. It is pending simulated owner review and grants no access.`,
        pendingException: undefined,
        correlationId: receipt.correlationId,
        toolEvent: { name: 'create_access_exception', kind: 'CONSEQUENTIAL', status: 'CREATED', detail: `Created ${receipt.requestId} at ${receipt.createdAt}; no real access was granted.` },
      } : message));
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : 'The synthetic request could not be created.');
    } finally {
      setActionPendingId(undefined);
    }
  };

  const cancelException = (messageId: string) => {
    setMessages((current) => current.map((message) => message.id === messageId ? {
      ...message,
      content: 'The prepared access-exception request was cancelled. No request was created and no access changed.',
      pendingException: undefined,
      toolEvent: { name: 'create_access_exception', kind: 'CONSEQUENTIAL', status: 'CANCELLED', detail: 'Proposal discarded before execution.' },
    } : message));
  };

  const retry = () => {
    setUiState('ready');
    setError('');
    if (!messages.length) setMessages(initialMessages);
  };

  const stale = uiState === 'stale';
  return (
    <FluentProvider theme={webLightTheme}>
      <div className="assistant-provider assistant-app">
        <header className="assistant-header">
          <div className="assistant-brand"><span><ShieldLock24Regular /></span><div><strong>Internal Policy Assistant</strong><Text size={200}>Synthetic policy fixture</Text></div></div>
          <div className="header-runtime"><span className="runtime-dot"><Circle20Regular /></span><div><Text weight="semibold">{replayMode ? 'Deterministic replay' : 'Azure-hosted inference'}</Text><Text size={100}>{replayMode ? 'No model call · demo evidence' : 'Managed identity · grounded retrieval'}</Text></div></div>
          <div className="signed-in"><PersonCircle24Regular /><div><Text size={200}>Signed in</Text><strong>User 7c91…a203</strong></div></div>
        </header>

        <main className="assistant-main">
          <section className="assistant-intro" aria-labelledby="assistant-title">
            <div><Text className="assistant-eyebrow">Approved synthetic corpus only</Text><h1 id="assistant-title">Ask about internal policy</h1><p>Answers cite their source. This fixture can look up policy metadata and prepare one harmless synthetic access-exception request.</p></div>
            <div className="replay-controls">
              <Switch checked={replayMode} disabled={replayOnly} onChange={(_, data) => setReplayMode(Boolean(data.checked))} label="Replay demo" />
              {replayMode ? <><Select aria-label="Replay scenario" value={scenario} onChange={(_, data) => setScenario(data.value as ReplayScenario)}><option value="grounded">Grounded answer</option><option value="injection">Injection blocked</option><option value="exception">Confirmation flow</option></Select><Button appearance="secondary" icon={<Play20Regular />} disabled={sending} onClick={() => void submitPrompt(scenarioPrompts[scenario], scenario)}>Run replay</Button></> : null}
            </div>
          </section>

          <div className="safety-strip" role="note"><ShieldLock24Regular /><Text><strong>Synthetic data only.</strong> No uploads, model selection, sharing, or general administration. Routine operational logs store IDs and outcomes—not raw prompt or response text.</Text></div>
          {stale ? <div className="assistant-warning" role="alert"><Warning20Regular /><Text><strong>Policy index is stale.</strong> Live answers are paused until refresh succeeds; deterministic replay remains available.</Text></div> : null}
          {error ? <div className="assistant-error" role="alert"><Warning20Regular /><Text>{error}</Text><Button appearance="subtle" onClick={retry}>Retry</Button></div> : null}

          <div className="workspace-grid">
            <section id="conversation" className="conversation-panel" aria-label="Policy conversation">
              <div className="conversation-scroll" aria-live="polite">
                <div className="system-message"><Bot24Regular /><div><Text weight="semibold">Grounded assistance</Text><Text size={200}>I answer from approved synthetic policies. If evidence is missing or conflicting, I abstain.</Text></div></div>
                {uiState === 'loading' ? (
                  <div className="assistant-loading" aria-busy="true" aria-label="Loading conversation"><Skeleton><SkeletonItem size={12} /><SkeletonItem size={64} /><SkeletonItem size={12} /><SkeletonItem size={96} /></Skeleton></div>
                ) : messages.length ? messages.map((message) => (
                  <MessageBubble key={message.id} message={message} action={message.pendingException ? <PendingActionCard proposal={message.pendingException} pending={actionPendingId === message.id} replayMode={replayMode} onCancel={() => cancelException(message.id)} onConfirm={() => void confirmException(message.id, message.pendingException as PendingException)} /> : undefined} />
                )) : (
                  <div className="empty-conversation"><Bot24Regular /><strong>No policy question yet</strong><Text>Choose a prompt below or ask about an approval requirement.</Text></div>
                )}
                {sending ? <div className="typing-indicator" role="status"><Spinner size="tiny" /><span>Retrieving approved policy sources…</span></div> : null}
                <div ref={conversationEnd} />
              </div>

              <div className="composer-area">
                {!messages.length ? <div className="prompt-chips">{['Who approves temporary access?', 'What must an exception include?'].map((prompt) => <Button key={prompt} appearance="outline" size="small" onClick={() => setDraft(prompt)}>{prompt}</Button>)}</div> : null}
                <div className="composer">
                  <Textarea aria-label="Ask a policy question" placeholder="Ask about an owner, section, or approval requirement…" value={draft} maxLength={1200} resize="vertical" disabled={sending || uiState === 'loading' || (stale && !replayMode)} onChange={(_, data) => setDraft(data.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void submitPrompt(draft); } }} />
                  <Tooltip content="Send policy question" relationship="label"><Button appearance="primary" shape="circular" icon={<ArrowUp20Regular />} aria-label="Send policy question" disabled={!draft.trim() || sending || uiState === 'loading' || (stale && !replayMode)} onClick={() => void submitPrompt(draft)} /></Tooltip>
                </div>
                <div className="composer-meta"><Text size={100}>Enter to send · Shift+Enter for a new line</Text><Text size={100}>{draft.length}/1,200</Text></div>
              </div>
            </section>

            <div className="assistant-sidebar">
              <PolicyLookupPanel replayMode={replayMode} />
              <aside className="session-panel"><div><CheckmarkCircle20Regular /><Text weight="semibold">Auditable session</Text></div><dl><dt>Session</dt><dd><code>{sessionId.current.slice(0, 20)}…</code></dd><dt>Corpus</dt><dd>synthetic-policy/2026.06</dd><dt>Model</dt><dd>{replayMode ? 'ReplayModelAdapter/1.0' : 'gpt-4o-mini · Global Standard'}</dd><dt>Output cap</dt><dd>400 tokens</dd><dt>Rate limit</dt><dd>10 requests / user / hour</dd></dl><Text size={100}>Correlation and evaluation IDs appear on every assistant interaction.</Text></aside>
            </div>
          </div>
        </main>
      </div>
    </FluentProvider>
  );
}
