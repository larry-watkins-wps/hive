/**
 * POST /sensory/text/in wrapper.
 * Returns the envelope id + timestamp (spec §4.4) so the caller can
 * rekey its optimistic local turn from the temporary client id to the
 * server-assigned envelope id. Spec §6.5.
 */
export type PostChatTextResponse = {
  id: string;
  timestamp: string;
};

export class ChatPostError extends Error {
  constructor(public readonly kind: string, public readonly detail: string) {
    super(`${kind}: ${detail}`);
    this.name = 'ChatPostError';
  }
}

export async function postChatText(
  text: string,
  speaker?: string,
): Promise<PostChatTextResponse> {
  const body = speaker !== undefined ? { text, speaker } : { text };
  let resp: Response;
  try {
    resp = await fetch('/sensory/text/in', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new ChatPostError('network', (e as Error).message);
  }
  if (!resp.ok) {
    let errKind = `http_${resp.status}`;
    let errMsg = resp.statusText;
    try {
      const parsed = await resp.json();
      // Match server bodies: 502 has flat {error, message}; 422 has FastAPI
      // detail array. Surface whichever shape is present.
      if (typeof parsed?.error === 'string') {
        errKind = parsed.error;
        errMsg = parsed.message ?? errMsg;
      } else if (Array.isArray(parsed?.detail) && parsed.detail.length > 0) {
        errKind = 'validation';
        errMsg = parsed.detail[0].msg ?? errMsg;
      }
    } catch { /* response wasn't JSON — keep status defaults */ }
    throw new ChatPostError(errKind, errMsg);
  }
  let data: PostChatTextResponse;
  try {
    data = (await resp.json()) as PostChatTextResponse;
  } catch (e) {
    throw new ChatPostError('parse', (e as Error).message);
  }
  if (typeof data?.id !== 'string' || typeof data?.timestamp !== 'string') {
    throw new ChatPostError('parse', 'response missing id or timestamp');
  }
  return data;
}
