# v4 Task 6 — Frontend store extension + chat persistence

You are an implementer subagent. Implement **observatory v4 Task 6** in this repository at `C:/repos/hive`. This is a self-contained task; do not read the plan or HANDOFF — everything you need is in this prompt.

## Context

The observatory frontend (`observatory/web-src/`) is a React 18 + TypeScript + zustand + Tailwind app that visualises Hive (an MQTT-based brain simulation). v4 is adding a floating chat overlay so the operator can talk to Hive. The backend POST `/sensory/text/in` route already exists (Tasks 1–5 landed in session 1) — it accepts `{text, speaker?}`, builds an `Envelope`, publishes to `hive/external/perception` over MQTT, and returns `{id, timestamp}` with status 202.

This task adds **only** the zustand store fields + setters and a localStorage persistence hook for the overlay's position/size. No UI rendering yet (Tasks 7–9 build the rest).

## Files

- **Modify:** `observatory/web-src/src/store.ts`
- **Create:** `observatory/web-src/src/chat/useChatPersistence.ts`
- **Create:** `observatory/web-src/src/chat/useChatPersistence.test.ts`

## Spec (authoritative — verbatim relevant excerpts)

**§6.2 Store extension:**
> `observatory/web-src/src/store.ts` gains a chat slice:
>
> ```ts
> type ChatSlice = {
>   chatVisible: boolean;
>   chatPosition: { x: number; y: number };  // top-left in viewport px
>   chatSize: { w: number; h: number };
>   setChatVisible: (v: boolean) => void;
>   setChatPosition: (p: { x: number; y: number }) => void;
>   setChatSize: (s: { w: number; h: number }) => void;
> };
> ```
>
> Defaults: `chatVisible: false`, `chatSize: { w: 320, h: 260 }`. `chatPosition` is computed lazily on first overlay open: `{ x: window.innerWidth - chatSize.w - 16, y: 16 }` (top-right with 16 px margin); after that it persists via `useChatPersistence`. If the persisted position would land off-screen (e.g. viewport shrunk between sessions), the overlay is clamped back inside the viewport at next open.
>
> `useChatPersistence` mirrors `useDockPersistence`'s pattern: hydrate on first mount from `localStorage['observatory.chat.*']`, debounce subsequent writes (200 ms).

**§6.5 Local-first user turn rendering & dedupe:**
> Implementation: a small chat-local state slice holds optimistic turns by id. … While the POST is in flight (no `id` yet), the optimistic turn carries a temporary client-side key and renders normally; on POST success the response `id` replaces the temp key; on POST failure the optimistic turn is replaced with an error placeholder.

(So the store also needs a `pendingChatTurns` map with rekey/fail/drop setters — this task adds it; ChatInput in Task 9 drives it.)

## Existing code surface

**`observatory/web-src/src/store.ts`** is a flat zustand store (`createStore` factory + `useStore` const). It already has fields like `regions`, `envelopes`, `envelopesReceivedTotal`, `selectedRegion`, `dockTab`, `pendingEnvelopeKey`, etc., wrapped with the `subscribeWithSelector` middleware. The `State` type is currently NOT exported — you must export it (Step 5 below). `Envelope`, `RegionMeta`, `MODULATOR_NAMES` are already exported.

**`observatory/web-src/src/dock/useDockPersistence.ts`** is the reference pattern: hydrate-once via `useRef(false)` guard, debounce writes 200 ms, subscribe via `subscribeWithSelector` overload. Read it for the house style — your hook should feel like a sibling.

## Implementation

### Step 1 — Extend the `State` type in `store.ts`

Above the `State` type, add the supporting type:

```ts
export type PendingChatTurn = {
  /** Stable id for React keys and lookup. Initially a client uuid; replaced
   * by the envelope id once POST returns. */
  id: string;
  text: string;
  speaker: string;
  /** ISO timestamp string. Initially the local time at submit; replaced
   * with the server-assigned envelope timestamp on POST success. */
  timestamp: string;
  /** Lifecycle state for rendering. */
  status: 'sending' | 'sent' | 'failed';
  /** Failure reason when status === 'failed'. */
  errorReason?: string;
};
```

In the `State` type, after the existing `pendingEnvelopeKey` entry and its `setPendingEnvelopeKey` setter, add:

```ts
  // Chat slice — see spec §6.2, §6.5
  chatVisible: boolean;
  chatPosition: { x: number; y: number };  // viewport px (top-left of overlay)
  chatSize: { w: number; h: number };
  /** Optimistic user turns awaiting firehose echo. Keyed by:
   *  - temporary client id while the POST is in flight (no envelope id yet)
   *  - envelope id once POST returns
   * Dropped when an envelope with the same id arrives in the firehose ring. */
  pendingChatTurns: Record<string, PendingChatTurn>;

  setChatVisible: (v: boolean) => void;
  setChatPosition: (p: { x: number; y: number }) => void;
  setChatSize: (s: { w: number; h: number }) => void;
  addPendingChatTurn: (turn: PendingChatTurn) => void;
  resolvePendingChatTurn: (clientId: string, envelopeId: string, timestamp: string) => void;
  failPendingChatTurn: (clientId: string, reason: string) => void;
  dropPendingChatTurn: (id: string) => void;
```

### Step 2 — Initial values + setters in the `create<State>()(...)` factory

Inside the `subscribeWithSelector(...)` factory, after the existing initial values (after `pendingEnvelopeKey: null,`), add:

```ts
    chatVisible: false,
    chatPosition: { x: 0, y: 16 },     // x is recomputed lazily on first open
    chatSize: { w: 320, h: 260 },
    pendingChatTurns: {},
```

After the existing setters (after `setPendingEnvelopeKey: ...,`), add:

```ts
    setChatVisible: (v) => set({ chatVisible: v }),
    setChatPosition: (p) => set({ chatPosition: p }),
    setChatSize: (s) => set({ chatSize: s }),
    addPendingChatTurn: (turn) => set((s) => ({
      pendingChatTurns: { ...s.pendingChatTurns, [turn.id]: turn },
    })),
    resolvePendingChatTurn: (clientId, envelopeId, timestamp) => set((s) => {
      const existing = s.pendingChatTurns[clientId];
      if (!existing) return {};
      const { [clientId]: _, ...rest } = s.pendingChatTurns;
      return {
        pendingChatTurns: {
          ...rest,
          [envelopeId]: { ...existing, id: envelopeId, timestamp, status: 'sent' },
        },
      };
    }),
    failPendingChatTurn: (clientId, reason) => set((s) => {
      const existing = s.pendingChatTurns[clientId];
      if (!existing) return {};
      return {
        pendingChatTurns: {
          ...s.pendingChatTurns,
          [clientId]: { ...existing, status: 'failed', errorReason: reason },
        },
      };
    }),
    dropPendingChatTurn: (id) => set((s) => {
      const { [id]: _, ...rest } = s.pendingChatTurns;
      return { pendingChatTurns: rest };
    }),
```

### Step 3 — Export `State`

Currently `store.ts` declares `type State = { ... }` (not exported). Change it to `export type State = { ... }`. `PendingChatTurn` you've already exported via `export type PendingChatTurn` in Step 1.

### Step 4 — Write the test (TDD red phase)

Create `observatory/web-src/src/chat/useChatPersistence.test.ts`:

```ts
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useStore } from '../store';
import { useChatPersistence } from './useChatPersistence';

describe('useChatPersistence', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('hydrates chatPosition + chatSize from localStorage on first mount', () => {
    localStorage.setItem('observatory.chat.position', JSON.stringify({ x: 50, y: 80 }));
    localStorage.setItem('observatory.chat.size', JSON.stringify({ w: 400, h: 300 }));

    renderHook(() => useChatPersistence(useStore));

    expect(useStore.getState().chatPosition).toEqual({ x: 50, y: 80 });
    expect(useStore.getState().chatSize).toEqual({ w: 400, h: 300 });
  });

  it('clamps hydrated position back inside the viewport', () => {
    Object.defineProperty(window, 'innerWidth', { value: 800, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 600, configurable: true });
    localStorage.setItem('observatory.chat.position', JSON.stringify({ x: 5000, y: 5000 }));
    localStorage.setItem('observatory.chat.size', JSON.stringify({ w: 320, h: 260 }));

    renderHook(() => useChatPersistence(useStore));

    const pos = useStore.getState().chatPosition;
    expect(pos.x).toBeLessThanOrEqual(800 - 320 - 16);
    expect(pos.y).toBeLessThanOrEqual(600 - 260 - 16);
  });

  it('debounces writes (200ms) on chatPosition changes', () => {
    renderHook(() => useChatPersistence(useStore));
    useStore.getState().setChatPosition({ x: 100, y: 200 });
    expect(localStorage.getItem('observatory.chat.position')).toBeNull();
    vi.advanceTimersByTime(199);
    expect(localStorage.getItem('observatory.chat.position')).toBeNull();
    vi.advanceTimersByTime(2);
    expect(JSON.parse(localStorage.getItem('observatory.chat.position')!))
      .toEqual({ x: 100, y: 200 });
  });

  it('debounces writes on chatSize changes', () => {
    renderHook(() => useChatPersistence(useStore));
    useStore.getState().setChatSize({ w: 500, h: 350 });
    vi.advanceTimersByTime(201);
    expect(JSON.parse(localStorage.getItem('observatory.chat.size')!))
      .toEqual({ w: 500, h: 350 });
  });
});
```

### Step 5 — Implement the persistence hook

Create `observatory/web-src/src/chat/useChatPersistence.ts`:

```ts
/**
 * localStorage persistence for the chat overlay's position + size.
 * Mirrors useDockPersistence: hydrate from localStorage on mount,
 * debounce 200ms on store changes back to localStorage. On hydrate,
 * clamp position so the overlay can't open off-screen if the viewport
 * shrunk between sessions. Spec §6.2.
 */
import { useEffect, useRef } from 'react';
import type { StoreApi } from 'zustand';

import type { State } from '../store';

const POSITION_KEY = 'observatory.chat.position';
const SIZE_KEY = 'observatory.chat.size';
const DEBOUNCE_MS = 200;
const VIEWPORT_MARGIN = 16;

function clampPosition(
  pos: { x: number; y: number },
  size: { w: number; h: number },
): { x: number; y: number } {
  const maxX = Math.max(0, window.innerWidth - size.w - VIEWPORT_MARGIN);
  const maxY = Math.max(0, window.innerHeight - size.h - VIEWPORT_MARGIN);
  return {
    x: Math.min(Math.max(VIEWPORT_MARGIN, pos.x), maxX),
    y: Math.min(Math.max(VIEWPORT_MARGIN, pos.y), maxY),
  };
}

export function useChatPersistence(store: StoreApi<State>): void {
  const hydratedRef = useRef(false);
  const posTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sizeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hydrate once on first mount.
  useEffect(() => {
    if (hydratedRef.current) return;
    hydratedRef.current = true;

    const sizeRaw = localStorage.getItem(SIZE_KEY);
    let size = store.getState().chatSize;
    if (sizeRaw) {
      try {
        const parsed = JSON.parse(sizeRaw);
        if (typeof parsed?.w === 'number' && typeof parsed?.h === 'number') {
          size = { w: parsed.w, h: parsed.h };
          store.getState().setChatSize(size);
        }
      } catch { /* corrupt — ignore, keep default */ }
    }

    const posRaw = localStorage.getItem(POSITION_KEY);
    if (posRaw) {
      try {
        const parsed = JSON.parse(posRaw);
        if (typeof parsed?.x === 'number' && typeof parsed?.y === 'number') {
          const clamped = clampPosition({ x: parsed.x, y: parsed.y }, size);
          store.getState().setChatPosition(clamped);
        }
      } catch { /* ignore */ }
    }
  }, [store]);

  // Debounced writes for position.
  useEffect(() => {
    return store.subscribe((s, prev) => {
      if (s.chatPosition === prev.chatPosition) return;
      if (posTimer.current) clearTimeout(posTimer.current);
      posTimer.current = setTimeout(() => {
        localStorage.setItem(POSITION_KEY, JSON.stringify(s.chatPosition));
      }, DEBOUNCE_MS);
    });
  }, [store]);

  // Debounced writes for size.
  useEffect(() => {
    return store.subscribe((s, prev) => {
      if (s.chatSize === prev.chatSize) return;
      if (sizeTimer.current) clearTimeout(sizeTimer.current);
      sizeTimer.current = setTimeout(() => {
        localStorage.setItem(SIZE_KEY, JSON.stringify(s.chatSize));
      }, DEBOUNCE_MS);
    });
  }, [store]);
}
```

## Gotchas

- The test imports `useStore` (the hook/UseBoundStore), not the inner StoreApi. UseBoundStore extends StoreApi, so passing `useStore` to a `StoreApi<State>`-typed parameter works structurally. Don't widen the param to `any` — keep `StoreApi<State>`.
- `subscribeWithSelector` middleware is *additive* — the basic `subscribe(listener)` overload (which the hook uses, with `(s, prev) => ...`) keeps working alongside the selector-scoped overload.
- In the `resolvePendingChatTurn`/`dropPendingChatTurn` setters the destructure-rest pattern uses `_` as the discard binding. ESLint's `no-unused-vars` typically allows the leading underscore; if your linter complains, leave the discard as `[clientId]: _unused` or similar that's still ignored — match whatever passes lint cleanly. Run `npx eslint .` after if available; otherwise rely on `tsc -b`.
- The test file lives in `observatory/web-src/src/chat/` — create that directory.
- `vitest.config.ts` has `globals: false`, so always import `describe`, `it`, `expect`, `beforeEach`, `afterEach`, `vi` explicitly.

## Verification

After implementing, run from `observatory/web-src/`:

```bash
npx vitest run src/chat/useChatPersistence.test.ts
npx tsc -b
npx vitest run    # full suite — should be 169 + 4 new = 173 passed
```

All must be green. tsc must report no output (clean).

## Commit

ONE commit. From `C:/repos/hive`:

```bash
git add observatory/web-src/src/store.ts observatory/web-src/src/chat/useChatPersistence.ts observatory/web-src/src/chat/useChatPersistence.test.ts
git commit -m "$(cat <<'EOF'
observatory(v4): store chat slice + useChatPersistence

Adds chatVisible/chatPosition/chatSize state and a pendingChatTurns
map to the zustand store, with setters for each. The pending-turns
map holds optimistic user turns keyed first by a temporary client id
during POST flight, then rekeyed to the envelope id once POST returns
(see Task 9 ChatInput for the lifecycle). Spec §6.2, §6.5.

useChatPersistence mirrors useDockPersistence: hydrate from localStorage
on mount, debounce 200ms on changes. Hydrated positions are clamped
back inside the viewport in case it shrunk between sessions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Status report

When done, report one of: DONE, DONE_WITH_CONCERNS, NEEDS_CONTEXT, or BLOCKED, with:
- the SHA of the commit
- summary of what changed (1–3 sentences)
- any concerns (deviations from this prompt, unexpected lint/type errors you had to work around, etc.)
- output of the final `npx vitest run` (last few lines: "Test Files X passed | Tests Y passed")
