# v4 Task 7 — Frontend api.ts: POST /sensory/text/in wrapper

You are an implementer subagent for observatory v4 Task 7. Implement it in `C:/repos/hive`. Self-contained — do not read the plan, spec, or HANDOFF beyond what's quoted here.

## Context

Task 6 just landed (SHA `2758a0a`): the zustand store now has chat fields and a `pendingChatTurns` map; `useChatPersistence` handles localStorage. This task creates the small fetch wrapper that ChatInput (Task 9) will call to POST a typed message to the backend's already-existing `/sensory/text/in` route.

The backend route returns 202 with body `{id: "<uuid>", timestamp: "<iso>"}` on success, 502 with body `{error: "publish_failed", message: "..."}` on broker failure, and 422 with FastAPI's standard `{detail: [...]}` validation body on bad input.

## Files

- **Create:** `observatory/web-src/src/chat/api.ts`
- **Create:** `observatory/web-src/src/chat/api.test.ts`

## Spec excerpts

**§4.4 Routes (response):**
> On success: `202 Accepted`, body `{id: "<uuid>", timestamp: "<iso>"}` — the envelope identifiers the frontend uses to dedupe its locally-rendered turn against the firehose echo (§6.5).
> On `PublishFailedError`: 502 with body `{error: "publish_failed", message: "<aiomqtt error>"}`.
> On Pydantic validation failure: 422 with FastAPI's standard validation body.

**§6.5 (consumer expectations):**
> Dedupe key: envelope `id` (UUID v4). The translator's `POST /sensory/text/in` returns `{id, timestamp}` synchronously — the frontend stores the optimistic turn keyed by `id`, and when an envelope with the same `id` lands in the firehose ring, the optimistic turn is dropped.

## Implementation

### Step 1 — Test (TDD red)

Create `observatory/web-src/src/chat/api.test.ts`:

```ts
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
});
```

### Step 2 — Implement

Create `observatory/web-src/src/chat/api.ts`:

```ts
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
  return (await resp.json()) as PostChatTextResponse;
}
```

## Gotchas

- `vitest.config.ts` has `globals: false` — always import test globals explicitly.
- Tests run under jsdom, so `global.fetch` and `Response` are available; `vi.spyOn(global, 'fetch')` works as shown.
- Don't add a `RestError` import or anything from `src/api/rest.ts` — chat's `ChatPostError` is intentionally distinct (different error body shape and different consumer needs).
- The `ChatPostError` constructor's `kind`/`detail` fields are public-readonly — ChatInput (Task 9) reads them directly.

## Verification

From `observatory/web-src/`:
```bash
npx vitest run src/chat/api.test.ts
npx tsc -b
npx vitest run                         # full suite — should be 176 + 4 = 180 passed
```

## Commit

ONE commit:

```bash
cd C:/repos/hive
git add observatory/web-src/src/chat/api.ts observatory/web-src/src/chat/api.test.ts
git commit -m "$(cat <<'EOF'
observatory(v4): chat/api.ts — POST /sensory/text/in wrapper

postChatText(text, speaker?) returns {id, timestamp} from the server's
202 response (spec §4.4). Errors are normalised into a ChatPostError
carrying {kind, detail} so the ChatInput component (Task 9) can render
the failure reason in its error placeholder.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Status report

Report DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED with: SHA, 1–3 sentence summary, deviations, last lines of `npx vitest run`.
