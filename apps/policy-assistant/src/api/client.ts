import { inferReplayScenario, lookupFixture, replayResponse } from '../fixtures';
import type { ChatResponse, ExceptionReceipt, PendingException, PolicyLookupResult, ReplayScenario } from '../types';

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? '/api/v1';
const LIVE_API = import.meta.env.VITE_DATA_SOURCE === 'api';
const DEV_REVIEWER = import.meta.env.DEV ? import.meta.env.VITE_DEV_REVIEWER_ID as string | undefined : undefined;
const DEV_ROLES = import.meta.env.DEV ? (import.meta.env.VITE_DEV_ROLES as string | undefined) : undefined;

interface ApiCitation {
  document_id: string;
  section_id: string;
  title: string;
  excerpt: string;
  classification: string;
}

interface ApiToolExecution {
  name: 'policy_lookup' | 'create_access_exception';
  authorization: 'ALLOWED' | 'DENIED' | 'NOT_REQUIRED';
  confirmation: 'CONFIRMED' | 'MISSING' | 'NOT_REQUIRED';
  status: 'EXECUTED' | 'REJECTED' | 'NOT_REQUESTED';
  result: Record<string, string> | null;
}

interface ApiChatResponse {
  correlation_id: string;
  evaluation_id: string;
  answer: string;
  citations: ApiCitation[];
  tool: ApiToolExecution | null;
  guardrail_outcomes: string[];
  model: string;
  model_version: string;
  latency_ms: number;
  generated_at: string;
}

interface ApiToolRequest {
  name: 'policy_lookup' | 'create_access_exception';
  arguments: Record<string, string>;
  consequential: boolean;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 20_000);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...(DEV_REVIEWER ? { 'X-AICA-Reviewer': DEV_REVIEWER } : {}), ...(DEV_ROLES ? { 'X-AICA-Roles': DEV_ROLES } : {}), ...init?.headers },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`Policy Assistant API ${response.status}: ${await response.text() || response.statusText}`);
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw new Error('The policy service did not respond within 20 seconds.');
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function exceptionProposal(prompt: string): PendingException {
  return {
    proposalId: `proposal-${crypto.randomUUID()}`,
    system: 'Synthetic Finance Reporting',
    access: 'Temporary report administrator',
    justification: prompt,
    durationDays: 7,
    policyReference: 'POL-017 §1',
  };
}

function chatBody(message: string, sessionId: string, requestedTool?: ApiToolRequest, confirmationToken?: string) {
  return {
    message,
    session_id: sessionId,
    tool_confirmation_token: confirmationToken,
    evaluation_mode: false,
    requested_tool: requestedTool,
  };
}

function mapApiMessage(raw: ApiChatResponse, pendingException?: PendingException): ChatResponse {
  const outcomes = raw.guardrail_outcomes.join(' ').toLowerCase();
  const guardrail = /injection|block|deny|unsafe/.test(outcomes) ? 'BLOCKED' : raw.citations.length ? 'ALLOWED' : 'ABSTAINED';
  const toolEvent = raw.tool ? {
    name: raw.tool.name,
    kind: raw.tool.name === 'policy_lookup' ? 'READ_ONLY' as const : 'CONSEQUENTIAL' as const,
    status: raw.tool.name === 'policy_lookup'
      ? raw.tool.status === 'EXECUTED' ? 'SUCCEEDED' as const : 'BLOCKED' as const
      : raw.tool.confirmation === 'MISSING' ? 'CONFIRMATION_REQUIRED' as const : raw.tool.status === 'EXECUTED' ? 'CREATED' as const : 'BLOCKED' as const,
    detail: raw.tool.result?.reason ?? `${raw.tool.authorization.toLowerCase()} · ${raw.tool.confirmation.toLowerCase()} · ${raw.tool.status.toLowerCase()}`,
  } : undefined;
  const confirmationToken = raw.tool?.result?.confirmation_token;
  const prepared = raw.tool?.name === 'create_access_exception' && raw.tool.confirmation === 'MISSING' && pendingException && confirmationToken
    ? { ...pendingException, confirmationToken }
    : undefined;

  return {
    message: {
      id: `msg-${crypto.randomUUID()}`,
      role: 'assistant',
      content: prepared ? 'I prepared a synthetic access-exception request. Review the details below. Nothing has been created; explicit confirmation is required.' : raw.answer,
      timestamp: raw.generated_at,
      citations: raw.citations.map((citation) => ({
        documentId: citation.document_id,
        title: citation.title,
        section: citation.section_id,
        excerpt: citation.excerpt,
        classification: 'SYNTHETIC_INTERNAL',
      })),
      correlationId: raw.correlation_id,
      evaluationId: raw.evaluation_id,
      latencyMs: raw.latency_ms,
      guardrail,
      toolEvent,
      pendingException: prepared,
    },
  };
}

async function sendMessage(prompt: string, sessionId: string, replay: boolean, selectedScenario?: ReplayScenario): Promise<ChatResponse> {
  if (replay || !LIVE_API) {
    await new Promise((resolve) => window.setTimeout(resolve, import.meta.env.MODE === 'test' ? 0 : 520));
    const response = replayResponse(selectedScenario ?? inferReplayScenario(prompt));
    response.message.id = `msg-${crypto.randomUUID()}`;
    return response;
  }
  const prepareException = inferReplayScenario(prompt) === 'exception';
  const proposal = prepareException ? exceptionProposal(prompt) : undefined;
  const requestedTool: ApiToolRequest | undefined = proposal ? {
    name: 'create_access_exception',
    consequential: true,
    arguments: {
      policy_id: 'POL-017',
      business_justification: proposal.justification,
      requested_duration: `${proposal.durationDays} days`,
      system: proposal.system,
      access: proposal.access,
    },
  } : undefined;
  const response = await request<ApiChatResponse>('/assistant/chat', { method: 'POST', body: JSON.stringify(chatBody(prompt, sessionId, requestedTool)) });
  return mapApiMessage(response, proposal);
}

async function lookupPolicy(query: string, replay: boolean): Promise<PolicyLookupResult> {
  if (replay || !LIVE_API) {
    await new Promise((resolve) => window.setTimeout(resolve, import.meta.env.MODE === 'test' ? 0 : 300));
    return lookupFixture(query);
  }
  const exception = query.toLowerCase().includes('exception');
  const documentId = exception ? 'POL-017-exception-management' : 'POL-002-access-control';
  const response = await request<ApiChatResponse>('/assistant/chat', {
    method: 'POST',
    body: JSON.stringify(chatBody(`Look up approved policy metadata for ${query}.`, `lookup-${crypto.randomUUID()}`, {
      name: 'policy_lookup',
      consequential: false,
      arguments: { document_id: documentId },
    })),
  });
  if (response.tool?.status !== 'EXECUTED' || !response.tool.result) throw new Error(response.tool?.result?.reason ?? 'Approved policy metadata was not found.');
  return {
    query,
    documentId: response.tool.result.document_id ?? documentId,
    section: response.tool.result.section_id ?? 'Approved section',
    owner: response.tool.result.owner ?? 'Policy Governance',
    approvalRequirement: response.tool.result.approval_requirement ?? 'Policy owner approval required.',
    classification: 'SYNTHETIC_INTERNAL',
    correlationId: response.correlation_id,
  };
}

async function confirmException(proposal: PendingException, sessionId: string, replay: boolean): Promise<ExceptionReceipt> {
  if (replay || !LIVE_API) {
    await new Promise((resolve) => window.setTimeout(resolve, import.meta.env.MODE === 'test' ? 0 : 450));
    return { requestId: `SYN-${crypto.randomUUID().slice(0, 8).toUpperCase()}`, status: 'CREATED', createdAt: new Date().toISOString(), synthetic: true, correlationId: `corr-${crypto.randomUUID().slice(0, 8)}` };
  }
  if (!proposal.confirmationToken) throw new Error('The server-issued confirmation token is missing; prepare the request again.');
  const response = await request<ApiChatResponse>('/assistant/chat', {
    method: 'POST',
    body: JSON.stringify(chatBody(proposal.justification, sessionId, {
      name: 'create_access_exception',
      consequential: true,
      arguments: {
        policy_id: 'POL-017',
        business_justification: proposal.justification,
        requested_duration: `${proposal.durationDays} days`,
        system: proposal.system,
        access: proposal.access,
      },
    }, proposal.confirmationToken)),
  });
  if (response.tool?.status !== 'EXECUTED' || !response.tool.result?.request_id) throw new Error(response.tool?.result?.reason ?? 'The confirmed synthetic request was rejected.');
  return { requestId: response.tool.result.request_id, status: 'CREATED', createdAt: response.generated_at, synthetic: true, correlationId: response.correlation_id };
}

export const assistantApi = { sendMessage, lookupPolicy, confirmException };
