import { afterEach, describe, expect, it, vi } from 'vitest';

import { postChatText } from './api';

describe('postChatText', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('POSTs to /sensory/text/in with the given text and returns id+timestamp', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ id: 'abc-123', timestamp: '2026-04-29T14:32:08.417Z' }),
        { status: 202, headers: { 'content-type': 'application/json' } },
      ),
    );

    const result = await postChatText('hello');

    expect(fetchMock).toHaveBeenCalledWith(
      '/sensory/text/in',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ text: 'hello' }),
      }),
    );
    expect(result).toEqual({ id: 'abc-123', timestamp: '2026-04-29T14:32:08.417Z' });
  });

  it('passes through speaker when provided', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 'x', timestamp: 't' }), { status: 202 }),
    );
    await postChatText('hi', 'Operator');
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toEqual({ text: 'hi', speaker: 'Operator' });
  });

  it('throws with the parsed error body on non-2xx', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: 'publish_failed', message: 'broker down' }),
        { status: 502 }),
    );
    await expect(postChatText('hi')).rejects.toThrow(/publish_failed.*broker down/);
  });

  it('throws on network failure with a generic message', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new TypeError('Network error'));
    await expect(postChatText('hi')).rejects.toThrow(/network/i);
  });

  it('throws ChatPostError(parse) when 2xx response is not valid JSON', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response('', { status: 202 }),
    );
    await expect(postChatText('hi')).rejects.toMatchObject({
      name: 'ChatPostError',
      kind: 'parse',
    });
  });
});
