import { assistantApi } from './client';

describe('Policy Assistant replay adapter', () => {
  it('prepares an exception without an execution receipt', async () => {
    const response = await assistantApi.sendMessage('Create a synthetic temporary access exception', 'session-test', true, 'exception');
    expect(response.message.toolEvent?.status).toBe('CONFIRMATION_REQUIRED');
    expect(response.message.pendingException).toBeDefined();
    expect(response.message.content).toContain('Nothing has been created');
  });

  it('returns citations with every grounded replay answer', async () => {
    const response = await assistantApi.sendMessage('Who approves access?', 'session-test', true, 'grounded');
    expect(response.message.citations?.length).toBeGreaterThan(0);
    expect(response.message.correlationId).toBeTruthy();
    expect(response.message.evaluationId).toBeTruthy();
  });
});
