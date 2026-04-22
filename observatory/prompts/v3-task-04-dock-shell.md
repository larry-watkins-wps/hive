# Observatory v3 — Task 4 implementer prompt

You are an implementer subagent. One task, end-to-end. Report status + SHA when done.

Use `superpowers:test-driven-development`.

**Working directory:** `C:\repos\hive`.
**Node:** `cd observatory/web-src && npx vitest run && npx tsc -b`.

---

## Task

Build the bottom-dock **shell** (frame + tab strip + persistence + keys + row-select helper). Three placeholder bodies for Firehose / Topics / Metacog — real content lands in Tasks 5-7.

### Authoritative references

- **Spec §4 — Bottom dock** (lines 63–99 of `observatory/docs/specs/2026-04-22-observatory-v3-design.md`):
  - §4.1 Frame: fixed bottom, default 220 px, collapsed 28 px, resize drag top 4 px edge, clamp [120, 520], debounced localStorage.
  - §4.2 Tab strip: 28 px tall, three tabs + pause + collapse; active-tab 1 px top-border accent.
  - §4.3 Visual language: thin borders, soft panel, hover-reveal.
- **Spec §8 — Interaction model** (lines 209–237): row click → `setSelectedRegion` + `setPendingEnvelopeKey`.
- **Spec §12 — Data model** (lines 343–371; already wired in Task 2).
- **Plan Task 4**: `observatory/docs/plans/2026-04-22-observatory-v3-plan.md` lines 871–1344.

---

## Plan Task 4 — verbatim (reproduced for self-containment)

### Files
- Create: `observatory/web-src/src/dock/Dock.tsx`
- Create: `observatory/web-src/src/dock/DockTabStrip.tsx`
- Create: `observatory/web-src/src/dock/useDockPersistence.ts`
- Create: `observatory/web-src/src/dock/useDockKeys.ts`
- Create: `observatory/web-src/src/dock/selectRegionFromRow.ts`
- Create: `observatory/web-src/src/dock/Dock.test.tsx`
- Create: `observatory/web-src/src/dock/useDockPersistence.test.ts`
- Create: `observatory/web-src/src/dock/selectRegionFromRow.test.ts`
- Modify: `observatory/web-src/src/App.tsx`

### Contract

**Keyboard:** `` ` `` → toggles `dockCollapsed`; `Space` (only when target is inside `#dock-root`) → toggles `dockPaused`. Both no-op on input / textarea / contenteditable targets.

**Resize:** drag top 4 px edge. `pointerdown` captures `startY` + `startH`, `pointermove` sets `dockHeight = startH + (startY - clientY)`, `pointerup` releases. `useDockPersistence` subscribes + debounces 200 ms to localStorage; rehydrates on mount (clamped).

**`selectRegionFromRow(store, { regionName, envelopeKey })`** — pure helper. Calls `select(regionName)` + `setPendingEnvelopeKey(envelopeKey)`. No-op when `regionName` is null. Implements spec §8.

### Steps

**Step 1 — failing `useDockPersistence` tests:**

```typescript
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';
import { useDockPersistence } from './useDockPersistence';
import { createStore } from '../store';

describe('useDockPersistence', () => {
  beforeEach(() => { localStorage.clear(); });
  afterEach(() => { cleanup(); });

  it('hydrates from localStorage on mount', () => {
    localStorage.setItem('observatory.dock.height', '300');
    localStorage.setItem('observatory.dock.collapsed', 'true');
    const store = createStore();
    renderHook(() => useDockPersistence(store));
    expect(store.getState().dockHeight).toBe(300);
    expect(store.getState().dockCollapsed).toBe(true);
  });

  it('clamps out-of-range height on hydrate', () => {
    localStorage.setItem('observatory.dock.height', '60');
    const store = createStore();
    renderHook(() => useDockPersistence(store));
    expect(store.getState().dockHeight).toBe(120);
  });

  it('writes to localStorage on state change (debounced)', async () => {
    const store = createStore();
    renderHook(() => useDockPersistence(store));
    act(() => { store.getState().setDockHeight(350); });
    await new Promise((r) => setTimeout(r, 260));
    expect(localStorage.getItem('observatory.dock.height')).toBe('350');
  });

  it('ignores malformed stored values', () => {
    localStorage.setItem('observatory.dock.height', 'abc');
    const store = createStore();
    renderHook(() => useDockPersistence(store));
    expect(store.getState().dockHeight).toBe(220);
  });
});
```

**Step 2 — Run. Red.**

**Step 3 — Implement `useDockPersistence.ts`:**

```typescript
import { useEffect, useRef } from 'react';
import type { StoreApi, UseBoundStore } from 'zustand';

const KEY_HEIGHT = 'observatory.dock.height';
const KEY_COLLAPSED = 'observatory.dock.collapsed';
const DEBOUNCE_MS = 200;
const MIN = 120;
const MAX = 520;

type AnyStore = UseBoundStore<StoreApi<{
  dockHeight: number;
  dockCollapsed: boolean;
  setDockHeight: (n: number) => void;
  setDockCollapsed: (b: boolean) => void;
}>>;

export function useDockPersistence(store: AnyStore): void {
  const hydrated = useRef(false);

  useEffect(() => {
    if (hydrated.current) return;
    hydrated.current = true;
    const h = Number(localStorage.getItem(KEY_HEIGHT));
    if (Number.isFinite(h) && h > 0) {
      store.getState().setDockHeight(Math.max(MIN, Math.min(MAX, h)));
    }
    const c = localStorage.getItem(KEY_COLLAPSED);
    if (c === 'true' || c === 'false') {
      store.getState().setDockCollapsed(c === 'true');
    }
  }, [store]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = (fn: () => void) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(fn, DEBOUNCE_MS);
    };
    const unsub = store.subscribe((s, prev) => {
      if (s.dockHeight !== prev.dockHeight) {
        schedule(() => localStorage.setItem(KEY_HEIGHT, String(s.dockHeight)));
      }
      if (s.dockCollapsed !== prev.dockCollapsed) {
        schedule(() => localStorage.setItem(KEY_COLLAPSED, String(s.dockCollapsed)));
      }
    });
    return () => { unsub(); if (timer) clearTimeout(timer); };
  }, [store]);
}
```

**Step 4 — Run persistence tests. 4 PASS.**

**Step 5 — failing `selectRegionFromRow` tests:**

```typescript
import { describe, it, expect } from 'vitest';
import { createStore } from '../store';
import { selectRegionFromRow } from './selectRegionFromRow';

describe('selectRegionFromRow', () => {
  it('sets selectedRegion and pendingEnvelopeKey', () => {
    const store = createStore();
    selectRegionFromRow(store, { regionName: 'pfc', envelopeKey: '123|hive/cog' });
    expect(store.getState().selectedRegion).toBe('pfc');
    expect(store.getState().pendingEnvelopeKey).toBe('123|hive/cog');
  });

  it('accepts null envelopeKey', () => {
    const store = createStore();
    selectRegionFromRow(store, { regionName: 'pfc', envelopeKey: null });
    expect(store.getState().selectedRegion).toBe('pfc');
    expect(store.getState().pendingEnvelopeKey).toBeNull();
  });

  it('no-op when regionName is null', () => {
    const store = createStore();
    store.getState().select('existing');
    selectRegionFromRow(store, { regionName: null, envelopeKey: null });
    expect(store.getState().selectedRegion).toBe('existing');
  });
});
```

**Step 6 — Implement:**

```typescript
import type { StoreApi, UseBoundStore } from 'zustand';

type MinStore = UseBoundStore<StoreApi<{
  select: (name: string | null) => void;
  setPendingEnvelopeKey: (key: string | null) => void;
  selectedRegion: string | null;
}>>;

export function selectRegionFromRow(
  store: MinStore,
  { regionName, envelopeKey }: { regionName: string | null; envelopeKey: string | null },
): void {
  if (regionName == null) return;
  store.getState().select(regionName);
  store.getState().setPendingEnvelopeKey(envelopeKey);
}
```

**Step 7 — Run helper tests. 3 PASS.**

**Step 8 — Implement `useDockKeys.ts`:**

```typescript
import { useEffect } from 'react';
import { useStore } from '../store';

function isEditableTarget(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  if (t instanceof HTMLInputElement) return true;
  if (t instanceof HTMLTextAreaElement) return true;
  return t.isContentEditable;
}

function inDock(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return t.closest('#dock-root') != null;
}

export function useDockKeys(): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isEditableTarget(e.target)) return;
      if (e.key === '`' && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        const { dockCollapsed, setDockCollapsed } = useStore.getState();
        setDockCollapsed(!dockCollapsed);
        return;
      }
      if (e.key === ' ' && inDock(e.target)) {
        e.preventDefault();
        const { dockPaused, setDockPaused } = useStore.getState();
        setDockPaused(!dockPaused);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);
}
```

**Step 9 — Implement `DockTabStrip.tsx`:**

```tsx
import { useStore } from '../store';

const TABS: Array<{ id: 'firehose' | 'topics' | 'metacog'; label: string }> = [
  { id: 'firehose', label: 'Firehose' },
  { id: 'topics', label: 'Topics' },
  { id: 'metacog', label: 'Metacog' },
];

export function DockTabStrip({ firehoseRate, topicCount, metacogBadge }: {
  firehoseRate: number;
  topicCount: number;
  metacogBadge: { count: number; severity: 'error' | 'conflict' | 'quiet' };
}) {
  const dockTab = useStore((s) => s.dockTab);
  const setDockTab = useStore((s) => s.setDockTab);
  const dockCollapsed = useStore((s) => s.dockCollapsed);
  const setDockCollapsed = useStore((s) => s.setDockCollapsed);
  const dockPaused = useStore((s) => s.dockPaused);
  const setDockPaused = useStore((s) => s.setDockPaused);

  const badgeColor =
    metacogBadge.severity === 'error' ? 'text-[#ff8a88]' :
    metacogBadge.severity === 'conflict' ? 'text-[#ffc07a]' : 'text-[rgba(230,232,238,.45)]';

  return (
    <div className="flex items-center h-7 px-2 border-b border-[rgba(80,84,96,.55)] select-none" style={{ fontSize: 11 }}>
      {TABS.map((t) => {
        const active = dockTab === t.id;
        const count =
          t.id === 'firehose' ? `${firehoseRate.toFixed(0)}/s` :
          t.id === 'topics' ? `${topicCount}` :
          `·${metacogBadge.count}`;
        const countClass = t.id === 'metacog' ? badgeColor : 'text-[rgba(230,232,238,.55)]';
        return (
          <button
            key={t.id}
            onClick={() => setDockTab(t.id)}
            className={[
              'px-3 h-7 mr-1',
              active ? 'text-[rgba(230,232,238,.95)] border-t border-[rgba(230,232,238,.9)]' : 'text-[rgba(230,232,238,.45)]',
            ].join(' ')}
          >
            {t.label}
            {' '}
            <span className={['font-mono ml-1', countClass].join(' ')} style={{ fontSize: 10 }}>
              {count}
            </span>
          </button>
        );
      })}
      <div className="flex-1" />
      <button
        className="w-6 h-6 text-[rgba(230,232,238,.55)] hover:text-[rgba(230,232,238,.95)]"
        onClick={() => setDockPaused(!dockPaused)}
        title={dockPaused ? 'Resume (Space)' : 'Pause (Space)'}
      >
        {dockPaused ? '▶' : '⏸'}
      </button>
      <button
        className="w-6 h-6 text-[rgba(230,232,238,.55)] hover:text-[rgba(230,232,238,.95)]"
        onClick={() => setDockCollapsed(!dockCollapsed)}
        title={dockCollapsed ? 'Expand (`)' : 'Collapse (`)'}
      >
        {dockCollapsed ? '˄' : '˅'}
      </button>
    </div>
  );
}
```

**Step 10 — Implement `Dock.tsx`:**

```tsx
import { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';
import { DockTabStrip } from './DockTabStrip';
import { useDockPersistence } from './useDockPersistence';

function FirehosePlaceholder() {
  return <div className="p-3 text-xs opacity-60">Firehose — implemented in v3 Task 5</div>;
}
function TopicsPlaceholder() {
  return <div className="p-3 text-xs opacity-60">Topics — implemented in v3 Task 6</div>;
}
function MetacogPlaceholder() {
  return <div className="p-3 text-xs opacity-60">Metacog — implemented in v3 Task 7</div>;
}

export function Dock() {
  useDockPersistence(useStore);
  const tab = useStore((s) => s.dockTab);
  const collapsed = useStore((s) => s.dockCollapsed);
  const height = useStore((s) => s.dockHeight);
  const setDockHeight = useStore((s) => s.setDockHeight);

  const [dragging, setDragging] = useState(false);
  const startY = useRef(0);
  const startH = useRef(220);

  useEffect(() => {
    if (!dragging) return;
    const onMove = (e: PointerEvent) => {
      const delta = startY.current - e.clientY;
      setDockHeight(startH.current + delta);
    };
    const onUp = () => setDragging(false);
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [dragging, setDockHeight]);

  const activeHeight = collapsed ? 28 : height;

  return (
    <div
      id="dock-root"
      tabIndex={0}
      className="fixed bottom-0 left-0 right-0 bg-[rgba(14,15,19,.86)] border-t border-[rgba(80,84,96,.55)] text-[rgba(230,232,238,.85)] z-30 flex flex-col"
      style={{ height: activeHeight }}
    >
      <div
        className="absolute -top-1 left-0 right-0 h-1 cursor-ns-resize"
        onPointerDown={(e) => {
          startY.current = e.clientY;
          startH.current = height;
          setDragging(true);
        }}
      />
      <DockTabStrip
        firehoseRate={0}
        topicCount={0}
        metacogBadge={{ count: 0, severity: 'quiet' }}
      />
      {!collapsed && (
        <div className="flex-1 overflow-hidden">
          {tab === 'firehose' && <FirehosePlaceholder />}
          {tab === 'topics' && <TopicsPlaceholder />}
          {tab === 'metacog' && <MetacogPlaceholder />}
        </div>
      )}
    </div>
  );
}
```

**Step 11 — Mount in `App.tsx`.** Call `useDockKeys()` + render `<Dock />`. See drift A below.

**Step 12 — Failing Dock component test:**

```tsx
import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { Dock } from './Dock';
import { useStore } from '../store';

afterEach(() => { cleanup(); localStorage.clear(); useStore.setState({ dockCollapsed: false, dockTab: 'firehose', dockHeight: 220 }); });

describe('Dock frame', () => {
  it('renders at default height 220px', () => {
    const { container } = render(<Dock />);
    const root = container.querySelector('#dock-root') as HTMLElement;
    expect(root.style.height).toBe('220px');
  });

  it('collapses to 28px when dockCollapsed is true', () => {
    const { container, rerender } = render(<Dock />);
    useStore.setState({ dockCollapsed: true });
    rerender(<Dock />);
    const root = container.querySelector('#dock-root') as HTMLElement;
    expect(root.style.height).toBe('28px');
  });

  it('mounts the placeholder for the active tab', () => {
    const { queryByText, rerender } = render(<Dock />);
    expect(queryByText(/Firehose — implemented/)).toBeTruthy();
    useStore.setState({ dockTab: 'topics' });
    rerender(<Dock />);
    expect(queryByText(/Topics — implemented/)).toBeTruthy();
  });
});
```

**Step 13 — Run full suite + typecheck:**

```
cd observatory/web-src && npx vitest run && npx tsc -b
```

**Step 14 — Commit.** HEREDOC per the plan.

---

## Drifts you MUST correct

### Drift A — App.tsx structure mismatch

The plan's Step 11 shows `<div className="w-screen h-screen overflow-hidden bg-hive-bg text-hive-fg">` with an ASCII-comment placeholder for existing mounts. The **real** `App.tsx` (read verbatim below) uses `<div className="relative w-full h-full">` and mounts `<Scene />`, `<Hud />`, `<Inspector />`. Preserve the existing wrapper + children; just add imports, call `useDockKeys()`, and render `<Dock />` as a sibling after `<Inspector />`.

Current `App.tsx`:

```tsx
import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { Hud } from './hud/Hud';
import { Inspector } from './inspector/Inspector';
import { useInspectorKeys } from './inspector/useInspectorKeys';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  // Strict-mode safe: connect() returns a cleanup that closes the socket; the
  // double mount/unmount in dev is absorbed by the reconnect guard in ws.ts.
  useEffect(() => connect(useStore), []);
  // Window-level keydown bindings for Esc / [ / ] / R. Installed once at the
  // App root so no per-component listeners duplicate. Spec §3.1 / §4.
  useInspectorKeys();
  return (
    <div className="relative w-full h-full">
      <Scene />
      <Hud />
      <Inspector />
    </div>
  );
}
```

After Task 4:

```tsx
import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { Hud } from './hud/Hud';
import { Inspector } from './inspector/Inspector';
import { Dock } from './dock/Dock';
import { useInspectorKeys } from './inspector/useInspectorKeys';
import { useDockKeys } from './dock/useDockKeys';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  useEffect(() => connect(useStore), []);
  useInspectorKeys();
  useDockKeys();
  return (
    <div className="relative w-full h-full">
      <Scene />
      <Hud />
      <Inspector />
      <Dock />
    </div>
  );
}
```

Preserve the strict-mode-safe comment + the useInspectorKeys comment. Add a one-line comment above `useDockKeys()` noting it owns backtick + Space in spec §4.1.

### Drift B — default export

The plan's Step 11 uses `export default function App()`. The real `App.tsx` uses `export function App()` (named export). Don't change this.

### Drift C — input-focus guard duplication

Plan's `useDockKeys` has its own `isEditableTarget` helper. `useInspectorKeys.ts` has an inline equivalent (lines 35-41). The plan's drift note #9 says: "Factor the guard into a shared helper if clean; otherwise inline-copy with a comment."

**Recommendation: keep them separate for now.** `useInspectorKeys`'s inline block has a different predicate style (`t.tagName === 'INPUT'` vs `t instanceof HTMLInputElement`) and is only 7 lines. Factoring risks touching a v2 hook when Task 4 should stay tightly scoped to the dock. Leave it; if a third hook later needs the same guard, extract then.

If the implementer prefers to extract (judgment call), put it in `observatory/web-src/src/keyboard.ts` and refactor both hooks. Document the call in `decisions.md`.

---

## Existing-contract surface

**`observatory/web-src/src/store.ts`** — Task 2 landed these:
- `dockTab: 'firehose' | 'topics' | 'metacog'` (default `'firehose'`)
- `dockCollapsed: boolean` (default `false`)
- `dockHeight: number` (default `220`, clamped [120, 520] in `setDockHeight`)
- `dockPaused: boolean` (default `false`)
- `firehoseFilter: string` (default `''`)
- `expandedRowIds: Set<string>` (cleared on `setDockTab`)
- `pendingEnvelopeKey: string | null` (default `null`)
- Setters: `setDockTab`, `setDockCollapsed`, `setDockHeight`, `setDockPaused`, `setFirehoseFilter`, `toggleRowExpand`, `setPendingEnvelopeKey`.
- `useStore = createStore()` at module bottom. `createStore()` also exported for test isolation.

**`observatory/web-src/src/inspector/useInspectorKeys.ts`** — reference only. Inline input-focus guard on lines 35-41.

**`observatory/web-src/src/App.tsx`** — preserve existing mounts + comments; add Dock + useDockKeys.

**Zustand `store.subscribe((state, prev) => void)`** — the classic two-arg overload. Works with vanilla store or wrapped hook (`useStore` is both).

## Gotchas

- **Zustand `subscribe` changed API in v4:** `store.subscribe((state, prev) => …)` fires on every state change, passing current + previous full state. The plan's code uses this two-arg form correctly; don't switch to selector form (`store.subscribe(selector, listener)`).
- **`act()` on async state updates:** Step 1's test wraps `setDockHeight` in `act()` to flush React's batched update. Keep it — the debounced localStorage write is timer-based so the `await setTimeout(260)` covers it.
- **`store.setState()` inside tests:** Step 12's test calls `useStore.setState({...})` to force state changes between renders. This only works on zustand v4's `create()` output (which our `createStore` returns). Already verified via Task 2.
- **`ResizeObserver` / `PointerEvent` in jsdom:** the Dock uses `pointerdown`/`pointermove`/`pointerup`. jsdom supports `PointerEvent` in recent versions (our vitest jsdom environment has it). If the drag test breaks, fall back to `mousedown` — but the plan's test doesn't exercise drag, only height/collapse state, so this should be fine.
- **`#dock-root`:** unique DOM id. `document.querySelectorAll('#dock-root')` must return exactly one element. With React strict-mode double-mount in dev, this holds only because the second mount unmounts the first synchronously.
- **Tab-strip counts are props, not store selectors here.** Real values get wired in Tasks 5-7 (firehose rate from `envelopesReceivedTotal` delta, topic count from `useTopicStats`, metacog badge from metacog selector). For Task 4, the `<Dock>` passes zero/quiet placeholders.
- **`select-none`** on the tab strip prevents text selection when double-clicking tabs.
- **Ref-style `startH.current = height` on `pointerdown`:** captures the *current* height at drag start; don't try to read from store inside the move handler — it'd re-subscribe and cause re-renders.
- **`bg-[rgba(14,15,19,.86)]`** arbitrary-value Tailwind syntax — already used in v2 Inspector. No config change needed.

## Verification gates (must all pass before commit)

```
cd observatory/web-src && npx vitest run && npx tsc -b
cd ../.. && .venv/Scripts/python.exe -m ruff check observatory/
```

Expected: **~114 frontend tests passing** (was 103 after Task 3 → add 4 persistence + 3 helper + 3 Dock frame = +10 = 113; +1 drift margin OK). Ruff clean. tsc clean.

## Hard rules

- Do NOT touch `region_template/`, `glia/`, `regions/`, `bus/`, `shared/`.
- Do NOT touch `useInspectorKeys.ts` unless extracting the input-focus guard (Drift C).
- Do NOT modify `connect()` / `ws.ts` / `store.ts` (already done in prior tasks).
- Do NOT push.
- TDD: tests FIRST, observe red, THEN implement.
- If a spec-vs-plan conflict surfaces not covered above, stop with `NEEDS_CONTEXT`.

## Report format

1. Status / SHA / files touched
2. Test delta (before/after)
3. Drift C option taken + rationale
4. Any other drift from this brief
5. Concerns
