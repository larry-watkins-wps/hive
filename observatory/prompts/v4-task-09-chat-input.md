# v4 Task 9 — ChatInput

You are an implementer subagent for observatory v4 Task 9. Implement it in `C:/repos/hive`. Self-contained — do not read the plan/spec/HANDOFF beyond what's quoted here.

## Context

Tasks 6/7/8 already landed:
- Store has `pendingChatTurns: Record<string, PendingChatTurn>` plus the lifecycle setters `addPendingChatTurn`, `resolvePendingChatTurn`, `failPendingChatTurn`, `dropPendingChatTurn`.
- `chat/api.ts` exports `postChatText(text, speaker?)` and `ChatPostError`.
- `chat/Transcript.tsx` reads the store and renders user/hive/audio/error variants.

This task adds the ChatInput component that drives the optimistic-turn lifecycle.

## Files

- **Create:** `observatory/web-src/src/chat/ChatInput.tsx`
- **Create:** `observatory/web-src/src/chat/ChatInput.test.tsx`
- **Modify (devDep):** `observatory/web-src/package.json` — add `@testing-library/user-event` (currently absent; tests rely on it)
- **Possibly modify:** `observatory/web-src/package-lock.json` (npm install side effect)

## Spec excerpts

**§6.7 ChatInput:**
> - `<textarea>` with `rows={2}`, auto-grow up to 6 rows.
> - `Enter` (no shift) → submit. `Shift+Enter` → newline.
> - Submit is disabled when `text.trim() === ""`.
> - On submit: render optimistic local turn; clear textarea; `POST /sensory/text/in {text, speaker: undefined}` (server fills speaker default).
> - Below the textarea, a single hint line: `enter to send · esc to dismiss · c to toggle`. 9 px mono `rgba(120,124,135,.55)`. Hidden when `h < 200`. *(Note: the `h < 200` rule is the overlay's job in Task 10 — this task always renders the hint.)*

**§6.5 Optimistic lifecycle:**
1. User hits Enter → add pending turn `status='sending'`, keyed by temp client id; clear textarea.
2. POST. On 202: rekey from temp id → envelope id, status=`sent`. Transcript dedupes once firehose echo arrives.
3. On POST failure: flip pending turn to `status='failed'` with the `ChatPostError` detail.

**Pure-B convention (§7):** No spinner, no delivery receipt. The optimistic turn rendering immediately is the only feedback.

## Existing types

```ts
// from store.ts
export type PendingChatTurn = {
  id: string;
  text: string;
  speaker: string;
  timestamp: string;
  status: 'sending' | 'sent' | 'failed';
  errorReason?: string;
};

// from chat/api.ts
export class ChatPostError extends Error {
  constructor(public readonly kind: string, public readonly detail: string)
  // .name === 'ChatPostError', .kind, .detail
}
export async function postChatText(text: string, speaker?: string): Promise<{id: string; timestamp: string}>;
```

## Implementation

### Step 1 — Install user-event devDep

Tests use `@testing-library/user-event` for keyboard simulation (`u.keyboard('{Enter}')`, `'{Shift>}{Enter}{/Shift}'`). It's not installed.

```bash
cd observatory/web-src
npm install --save-dev @testing-library/user-event@^14
```

This will modify `package.json` and `package-lock.json`. Don't pin to an exact version — `^14` matches `@testing-library/react@^16` (16 supports user-event 14.x).

After install, verify it imports cleanly with a tiny check:
```bash
node -e "require.resolve('@testing-library/user-event')"
```

### Step 2 — Test (TDD red)

Create `observatory/web-src/src/chat/ChatInput.test.tsx`. Note: vitest doesn't load `@testing-library/jest-dom` — use the same scan-based assertion pattern Task 8 used (or `expect(...).toBeTruthy()` with direct DOM queries):

```tsx
import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useStore } from '../store';
import { ChatInput } from './ChatInput';
import * as api from './api';

describe('ChatInput', () => {
  beforeEach(() => {
    useStore.setState({ pendingChatTurns: {} });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    cleanup();
    useStore.setState({ pendingChatTurns: {} });
  });

  it('disables submit when text is empty after trim', async () => {
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox');
    const u = userEvent.setup();
    await u.type(textarea, '   ');
    await u.keyboard('{Enter}');
    expect(useStore.getState().pendingChatTurns).toEqual({});
  });

  it('submit on Enter: adds optimistic pending turn and POSTs', async () => {
    const post = vi.spyOn(api, 'postChatText').mockResolvedValue({
      id: 'env-1', timestamp: '2026-04-29T14:00:00.000Z',
    });
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox');
    const u = userEvent.setup();
    await u.type(textarea, 'hello');
    await u.keyboard('{Enter}');

    // Optimistic turn appears immediately (keyed by client id, status sending or already-sent
    // if microtasks resolved before this assertion).
    const pending = Object.values(useStore.getState().pendingChatTurns);
    expect(pending.length).toBe(1);
    expect(pending[0].text).toBe('hello');
    expect(['sending', 'sent']).toContain(pending[0].status);
    expect(post).toHaveBeenCalledWith('hello', undefined);

    // Wait microtasks: pending turn rekeyed to envelope id.
    await Promise.resolve();
    await Promise.resolve();
    const after = useStore.getState().pendingChatTurns;
    expect(after['env-1']).toBeTruthy();
    expect(after['env-1'].status).toBe('sent');
  });

  it('Shift+Enter inserts a newline and does not submit', async () => {
    const post = vi.spyOn(api, 'postChatText');
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    const u = userEvent.setup();
    await u.type(textarea, 'line one');
    await u.keyboard('{Shift>}{Enter}{/Shift}');
    await u.type(textarea, 'line two');
    expect(textarea.value).toBe('line one\nline two');
    expect(post).not.toHaveBeenCalled();
  });

  it('clears textarea after successful submit', async () => {
    vi.spyOn(api, 'postChatText').mockResolvedValue({
      id: 'env-1', timestamp: 't',
    });
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    const u = userEvent.setup();
    await u.type(textarea, 'hi');
    await u.keyboard('{Enter}');
    expect(textarea.value).toBe('');
  });

  it('flips pending turn to failed on POST error', async () => {
    vi.spyOn(api, 'postChatText').mockRejectedValue(
      new api.ChatPostError('publish_failed', 'broker down'),
    );
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox');
    const u = userEvent.setup();
    await u.type(textarea, 'hi');
    await u.keyboard('{Enter}');
    await Promise.resolve();
    await Promise.resolve();
    const pending = Object.values(useStore.getState().pendingChatTurns);
    expect(pending.length).toBe(1);
    expect(pending[0].status).toBe('failed');
    expect(pending[0].errorReason).toMatch(/broker down/);
  });
});
```

### Step 3 — Implement ChatInput

Create `observatory/web-src/src/chat/ChatInput.tsx`:

```tsx
/**
 * Chat input: auto-grow textarea + Enter-to-submit + optimistic lifecycle.
 *
 * Lifecycle (spec §6.5):
 *   1. User hits Enter. Add pending turn with status='sending', keyed by
 *      a temp client id. Clear the textarea.
 *   2. POST /sensory/text/in. On 202 success, rekey the pending turn
 *      from temp id to the server's envelope id and set status='sent'.
 *      The Transcript dedupes by id once the firehose echo arrives.
 *   3. On POST failure, flip the pending turn to status='failed' with the
 *      ChatPostError detail in errorReason. The Transcript renders it as
 *      an error placeholder. The temp id stays — the user can re-type a
 *      fresh message; the failed turn lingers until cleared.
 */
import { useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';

import { useStore, type PendingChatTurn } from '../store';
import { ChatPostError, postChatText } from './api';

let _clientIdCounter = 0;
function nextClientId(): string {
  _clientIdCounter += 1;
  return `chat-client-${Date.now()}-${_clientIdCounter}`;
}

const inputContainerStyle: CSSProperties = {
  borderTop: '1px solid rgba(80,84,96,.25)',
  padding: '10px 14px',
  display: 'flex', flexDirection: 'column', gap: 4,
};
const textareaStyle: CSSProperties = {
  width: '100%', resize: 'none',
  background: 'transparent', border: 'none', outline: 'none',
  color: 'rgba(230,232,238,.9)',
  fontFamily: 'Inter, ui-sans-serif, sans-serif',
  fontWeight: 200, fontSize: 11, lineHeight: 1.5,
};
const hintStyle: CSSProperties = {
  fontFamily: 'ui-monospace, Consolas, monospace',
  fontSize: 9, color: 'rgba(120,124,135,.55)',
  letterSpacing: '.3px',
};

const MAX_ROWS = 6;
const ROW_PX = 16;  // line-height 1.5 × 11px ≈ 16

export function ChatInput() {
  const [text, setText] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);
  const addPending = useStore((s) => s.addPendingChatTurn);
  const resolvePending = useStore((s) => s.resolvePendingChatTurn);
  const failPending = useStore((s) => s.failPendingChatTurn);

  function autoGrow(el: HTMLTextAreaElement) {
    el.style.height = 'auto';
    const next = Math.min(el.scrollHeight, ROW_PX * (MAX_ROWS + 1));
    el.style.height = `${next}px`;
  }

  async function submit() {
    const trimmed = text.trim();
    if (!trimmed) return;
    const clientId = nextClientId();
    const optimistic: PendingChatTurn = {
      id: clientId,
      text: trimmed,
      speaker: 'Larry',  // server's default; we display the same locally
      timestamp: new Date().toISOString(),
      status: 'sending',
    };
    addPending(optimistic);
    setText('');
    if (ref.current) {
      ref.current.style.height = 'auto';
    }

    try {
      const { id, timestamp } = await postChatText(trimmed);
      resolvePending(clientId, id, timestamp);
    } catch (e) {
      const reason = e instanceof ChatPostError ? `${e.kind}: ${e.detail}` : String(e);
      failPending(clientId, reason);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  return (
    <div style={inputContainerStyle}>
      <textarea
        ref={ref}
        rows={2}
        placeholder="say something to hive…"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          autoGrow(e.currentTarget);
        }}
        onKeyDown={onKeyDown}
        style={textareaStyle}
      />
      <div style={hintStyle}>enter to send · esc to dismiss · c to toggle</div>
    </div>
  );
}
```

## Gotchas

- The hardcoded `'Larry'` speaker is intentional — backend's default is `chat_default_speaker = 'Larry'` (Settings), so the local optimistic turn matches what the firehose echo will carry. If the spec ever changes this, adjust both sides.
- `_clientIdCounter` is a module-level mutable. Tests don't reset it, so test ids will accumulate across the suite — that's harmless because the dedupe works on envelope ids, not on client ids.
- The `cleanup` import in the test is critical: without it, the textareas from earlier tests linger and `screen.getByRole('textbox')` matches multiple elements. Task 6's review-fix established this pattern.
- Don't import jest-dom — use `expect(...).toBe(...)`/`.toBeTruthy()`/`.toEqual()` style.
- `vitest.config.ts` has `globals: false` — explicit imports.
- The "submit when empty" test relies on Enter being pressed in an EMPTY (or whitespace-only) textarea. After trim, `submit()` returns early, so no pending turn is added.
- userEvent v14 is async — every interaction returns a Promise. Always `await u.type(...)` and `await u.keyboard(...)`.

## Verification

From `observatory/web-src/`:
```bash
npx vitest run src/chat/ChatInput.test.tsx       # 5 passed
npx tsc -b                                         # clean
npx vitest run                                     # full suite, 192 passed (was 187, +5)
```

If the install increased install size enough to flag npm warnings, that's fine — only fail on test/typecheck.

## Commit

```bash
cd C:/repos/hive
git add observatory/web-src/package.json observatory/web-src/package-lock.json observatory/web-src/src/chat/ChatInput.tsx observatory/web-src/src/chat/ChatInput.test.tsx
git commit -m "$(cat <<'EOF'
observatory(v4): ChatInput — auto-grow textarea + optimistic lifecycle

Enter submits, Shift+Enter newlines. On submit:
  - adds an optimistic pending turn keyed by a temp client id
  - clears the textarea
  - POSTs /sensory/text/in
  - on 202: rekeys pending turn from temp id -> envelope id, status=sent
    (Transcript dedupes by id once the firehose echoes the envelope back)
  - on failure: flips pending turn to status=failed with the ChatPostError
    detail; Transcript renders the error placeholder

Visual style matches the v3 dock input: borderless transparent textarea,
Inter 200 11px, mono hint line below. Spec §6.5, §6.7.

Adds @testing-library/user-event@^14 as a devDep — keyboard simulation
in the new tests requires it (no prior consumer in the project).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Status report

Report DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED with: SHA, 1–3 sentence summary, deviations, last lines of full `npx vitest run`.
