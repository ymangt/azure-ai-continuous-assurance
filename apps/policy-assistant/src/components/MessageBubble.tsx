import type { ReactNode } from 'react';
import { Text } from '@fluentui/react-components';
import { Bot20Regular, CheckmarkCircle20Regular, Clock20Regular, Person20Regular, ShieldError20Regular, Wrench20Regular } from '@fluentui/react-icons';
import type { ChatMessage } from '../types';
import { Citations } from './Citations';

interface MessageBubbleProps {
  message: ChatMessage;
  action?: ReactNode;
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('en-CA', { hour: 'numeric', minute: '2-digit', timeZone: 'UTC' }).format(new Date(value));
}

export function MessageBubble({ message, action }: MessageBubbleProps) {
  const assistant = message.role === 'assistant';
  return (
    <article className={`message-row message-${message.role}`} aria-label={`${assistant ? 'Policy Assistant' : 'You'} at ${formatTime(message.timestamp)} UTC`}>
      <div className="message-avatar" aria-hidden="true">{assistant ? <Bot20Regular /> : <Person20Regular />}</div>
      <div className="message-content">
        <div className="message-heading"><Text weight="semibold">{assistant ? 'Policy Assistant' : 'You'}</Text><Text size={100}>{formatTime(message.timestamp)} UTC</Text>{message.guardrail ? <span className={`guardrail guardrail-${message.guardrail.toLowerCase()}`}>{message.guardrail === 'BLOCKED' ? <ShieldError20Regular /> : <CheckmarkCircle20Regular />}{message.guardrail.toLowerCase()}</span> : null}</div>
        <div className="message-bubble"><p>{message.content}</p></div>
        {message.toolEvent ? <div className={`tool-event tool-${message.toolEvent.kind.toLowerCase()}`}><Wrench20Regular /><div><div><code>{message.toolEvent.name}</code><span>{message.toolEvent.kind.replace('_', ' ').toLowerCase()}</span><strong>{message.toolEvent.status.replaceAll('_', ' ').toLowerCase()}</strong></div><Text size={200}>{message.toolEvent.detail}</Text></div></div> : null}
        {action}
        {message.citations?.length ? <Citations citations={message.citations} /> : null}
        {assistant && message.correlationId ? <div className="trace-meta"><span><Clock20Regular /> {message.latencyMs ?? 0} ms</span><span>Correlation <code>{message.correlationId}</code></span><span>Evaluation <code>{message.evaluationId}</code></span></div> : null}
      </div>
    </article>
  );
}
