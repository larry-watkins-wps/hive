# v2 Task 14 — Inspector Messages section (filter + auto-scroll + row expand)

You are the **implementer subagent** for v2 Task 14 of the Hive observatory
sub-project. Fresh context. Everything you need is here.

## Where this task fits

Observatory v2 inspector panel (`observatory/web-src/src/inspector/`). Tasks
6–13 landed the shell + 7 of 8 sections. Only **Messages** remains. Task
15 is integration + HANDOFF closure and does NOT add more sections.

## Authority ordering

1. **Spec wins over plan prose.** Flag any spec/plan disagreement.
2. **User (Larry) instructions always override.**

## Files

- REPLACE stub: `observatory/web-src/src/inspector/sections/Messages.tsx`
- CREATE: `observatory/web-src/src/inspector/Messages.test.tsx`

**Do NOT modify** any other file. `Inspector.tsx` already imports
`Messages` and wires it with `name={displayName}` — your stub-replacement
makes it live.

## Current stub (you will replace this verbatim)

```tsx
// TODO(Task 14): ...
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function Messages(_props: { name: string }) {
  return null;
}
```

## Spec excerpt — §3.2 item 5 (Messages), §3.3 row, §3.4 empty state

**§3.2 item 5 — Messages log:**
> Expanded by default. Scrolling list of last ~100 envelopes where
> `source_region == name || name ∈ destinations`. Client-side filter over
> the store's `recent` ring buffer; no backend change. Row layout:
> `HH:MM:SS · ↑/↓ · topic · payload-preview (first 80 chars)`. Click a
> row to expand full envelope JSON inline. Auto-scroll: when the user's
> scroll position is within 40 px of the bottom, new arrivals scroll
> into view; otherwise auto-scroll pauses until the user returns near
> bottom. Implementation: `lastLenRef`-based incremental scan over the
> ring buffer (same pattern as v1 Sparks/Rhythm).

**§3.3 refetch row:** Messages — `(from store ring buffer)` — auto-refetch
triggers: `envelope arrival`. I.e., no HTTP fetch. Purely store-driven.

**§3.4 empty states:** Spec doesn't spell out Messages-empty copy, but for
consistency with other sections use a grey `No messages yet.` line.

## Existing contracts you will consume

### `observatory/web-src/src/store.ts`

```tsx
export type Envelope = {
  observed_at: number;          // unix seconds (float)
  topic: string;
  envelope: Record<string, unknown>;
  source_region: string | null;   // NOTE: nullable — comparisons vs. string name are fine
  destinations: string[];
};

type State = {
  regions: Record<string, RegionMeta>;
  envelopes: Envelope[];                 // ring, capped at RING_CAP=5000
  envelopesReceivedTotal: number;        // MONOTONIC counter (never plateaus)
  // ...
  applyRegionDelta(regions): void;       // REPLACES regions dict
  pushEnvelope(env: Envelope): void;     // concats, splices if over RING_CAP
};

export const useStore = create<...>(...)   // zustand; plain create, no middleware.
```

`useStore.subscribe(listener)` is zustand's plain subscribe — listener
gets called on every state change. `useStore.getState()` reads
synchronously. No selector-based subscribe on this store.

### `observatory/web-src/src/inspector/Inspector.tsx` (already wired)

```tsx
<Messages name={displayName} />
```

## Plan (verbatim from plan lines 2887–3092)

### Step 1 — Create `Messages.tsx`

```tsx
import { useEffect, useRef, useState } from 'react';
import { useStore, type Envelope } from '../../store';

const MAX_ROWS = 100;
const AUTOSCROLL_PX = 40;

function relevantToRegion(env: Envelope, name: string): boolean {
  return env.source_region === name || env.destinations.includes(name);
}

function renderTime(observedAt: number): string {
  const d = new Date(observedAt * 1000);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function previewPayload(env: Envelope): string {
  try {
    const s = JSON.stringify(env.envelope);
    return s.length > 80 ? s.slice(0, 80) + '…' : s;
  } catch {
    return '';
  }
}

export function Messages({ name }: { name: string }) {
  const [filtered, setFiltered] = useState<Envelope[]>([]);
  const lastLenRef = useRef(0);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const containerRef = useRef<HTMLDivElement | null>(null);
  const followTailRef = useRef(true);

  // (incremental scan effect — see gotcha #1 below for required fix)

  // Track follow-tail state on user scroll.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= AUTOSCROLL_PX;
      followTailRef.current = atBottom;
    };
    el.addEventListener('scroll', onScroll);
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // Auto-scroll when new row lands AND user was at bottom.
  useEffect(() => {
    if (!followTailRef.current) return;
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [filtered]);

  return (
    <details open className="border-b border-[#1f1f27]">
      <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
        <span className="font-semibold">Messages <span className="text-[#8a8e99] text-[10px]">· filtered to {name} · {filtered.length} recent</span></span>
      </summary>
      <div ref={containerRef} className="px-4 pb-2 text-[10.5px] font-mono text-[#cfd2da] max-h-[220px] overflow-y-auto">
        {filtered.length === 0 && <div className="text-[#8a8e99]">No messages yet.</div>}
        {filtered.map((e, i) => {
          const isExpanded = expanded.has(i);
          const direction = e.source_region === name ? '↑' : '↓';
          return (
            <div key={`${e.observed_at}-${i}`} className="py-1 border-b border-dotted border-[#23232b]">
              <div
                className="grid grid-cols-[60px_14px_1fr] gap-2 cursor-pointer"
                onClick={() => setExpanded((s) => {
                  const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n;
                })}
              >
                <span className="text-[#8a8e99]">{renderTime(e.observed_at)}</span>
                <span className={direction === '↑' ? 'text-[#ffb36a]' : 'text-[#8fd6a0]'}>{direction}</span>
                <span>
                  {e.topic}
                  {!isExpanded && <span className="text-[#8a8e99]"> &nbsp;{previewPayload(e)}</span>}
                </span>
              </div>
              {isExpanded && (
                <pre className="text-[10px] text-[#8a8e99] whitespace-pre-wrap pl-[76px] pt-1">
                  {JSON.stringify(e.envelope, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}
```

### Step 2 — Create `Messages.test.tsx`

```tsx
import { describe, it, expect } from 'vitest';  // NOTE: add `beforeEach`
import { render, screen } from '@testing-library/react';
import { Messages } from './sections/Messages';
import { useStore } from '../store';

describe('Messages', () => {
  beforeEach(() => {
    useStore.setState({ envelopes: [], envelopesReceivedTotal: 0, regions: {} });
    useStore.getState().applyRegionDelta({
      r: { role: 'x', llm_model: '', stats: { phase: 'wake', queue_depth: 0, stm_bytes: 0, tokens_lifetime: 0, handler_count: 0, last_error_ts: null, msg_rate_in: 0, msg_rate_out: 0, llm_in_flight: false } },
    });
  });

  it('shows only envelopes where region is source or destination', () => {
    useStore.getState().pushEnvelope({ observed_at: 0, topic: 'hive/a', envelope: {}, source_region: 'r', destinations: [] });
    useStore.getState().pushEnvelope({ observed_at: 1, topic: 'hive/b', envelope: {}, source_region: 'other', destinations: ['r'] });
    useStore.getState().pushEnvelope({ observed_at: 2, topic: 'hive/c', envelope: {}, source_region: 'other', destinations: ['nope'] });
    render(<Messages name="r" />);
    expect(screen.getByText(/hive\/a/)).toBeTruthy();
    expect(screen.getByText(/hive\/b/)).toBeTruthy();
    expect(screen.queryByText(/hive\/c/)).toBeNull();
  });

  it('shows direction ↑ for source, ↓ for destination', () => {
    useStore.getState().pushEnvelope({ observed_at: 0, topic: 't/one', envelope: {}, source_region: 'r', destinations: [] });
    useStore.getState().pushEnvelope({ observed_at: 1, topic: 't/two', envelope: {}, source_region: 'x', destinations: ['r'] });
    render(<Messages name="r" />);
    expect(screen.getAllByText('↑').length).toBe(1);
    expect(screen.getAllByText('↓').length).toBe(1);
  });

  it('caps rendered rows at MAX_ROWS', () => {
    for (let i = 0; i < 150; i++) {
      useStore.getState().pushEnvelope({ observed_at: i, topic: `t/${i}`, envelope: {}, source_region: 'r', destinations: [] });
    }
    const { container } = render(<Messages name="r" />);
    const rows = container.querySelectorAll('.grid.grid-cols-\\[60px_14px_1fr\\]');
    expect(rows.length).toBe(100);
  });
});
```

## REQUIRED drifts from plan — apply these fixes

### Gotcha #1 (IMPORTANT) — incremental-scan ring-saturation race

The plan's code uses `lastLenRef` + `env.length`. Once the ring caps at
`RING_CAP=5000`, `env.length` plateaus at 5000. `pushEnvelope` does
`splice(0, 1)` (drop oldest) + concat (append new); length stays 5000.
At that point: `startIdx = max(0, 5000) = 5000`, loop body never
executes, and **every new envelope is missed**. v1 Counters hit the
equivalent bug under its `envelopes.length` plateau and the fix was to
add the monotonic `envelopesReceivedTotal` counter (already landed — see
store.ts line 44, 94, 113).

**Required fix:** gate on `envelopesReceivedTotal` (monotonic) instead
of `envelopes.length` (plateaus). The new envelopes always sit at the
tail of the ring, so `.slice(-delta)`-style tail reads pick them up.

Replace the plan's incremental-scan effect with:

```tsx
const lastTotalRef = useRef(0);

useEffect(() => {
  const unsub = useStore.subscribe((s) => {
    const total = s.envelopesReceivedTotal;
    const delta = total - lastTotalRef.current;
    if (delta <= 0) return;                      // no new envelopes
    const env = s.envelopes;
    const take = Math.min(delta, env.length);    // defensive clamp
    const newOnes: Envelope[] = [];
    for (let i = env.length - take; i < env.length; i++) {
      const e = env[i];
      if (relevantToRegion(e, name)) newOnes.push(e);
    }
    lastTotalRef.current = total;
    if (newOnes.length > 0) {
      setFiltered((f) => {
        const next = f.concat(newOnes);
        return next.length > MAX_ROWS ? next.slice(-MAX_ROWS) : next;
      });
    }
  });
  // Seed from current ring contents (useful when panel just opened).
  const state = useStore.getState();
  const ring = state.envelopes;
  const initial: Envelope[] = [];
  for (const e of ring) if (relevantToRegion(e, name)) initial.push(e);
  setFiltered(initial.slice(-MAX_ROWS));
  lastTotalRef.current = state.envelopesReceivedTotal;
  return unsub;
}, [name]);
```

Replace `lastLenRef` declaration with `lastTotalRef`. Remove the unused
`lastLenRef` declaration entirely — `noUnusedLocals` will fail
otherwise.

Document this in a block comment on the effect: "Keyed on
`envelopesReceivedTotal` (monotonic) not `envelopes.length` (plateaus at
RING_CAP). Same precedent as Task 15's Counters store field."

### Gotcha #2 (IMPORTANT) — expanded-row key instability

The plan keys both `expanded: Set<number>` and the row `key=` on the
filtered-array index `i`. When new rows land and `.slice(-MAX_ROWS)`
drops the oldest, indices shift down. The `expanded` set still holds
old indices, now pointing to different envelopes. Users with rows
expanded during a live stream would see "wrong" envelopes expand.

**Required fix:** key both the Set and the React row on a stable
identity — use `` `${e.observed_at}|${e.topic}` `` as the identity
string. Two envelopes sharing timestamp+topic are vanishingly unlikely
in practice; if collisions matter later, a WS-delivered envelope id
would be the right v1.x follow-up.

Change:
- `const [expanded, setExpanded] = useState<Set<number>>(new Set());` →
  `const [expanded, setExpanded] = useState<Set<string>>(new Set());`
- Compute per-row: `const id = \`${e.observed_at}|${e.topic}\`;`
- Row: `key={id}` (was `` `${e.observed_at}-${i}` ``).
- Expand check: `expanded.has(id)` (was `expanded.has(i)`).
- Toggle: `n.has(id) ? n.delete(id) : n.add(id)` (was `i`).

### Gotcha #3 — vitest `globals: false`

The plan's test imports only `describe, it, expect` but uses
`beforeEach`. Add `beforeEach` to the import. Mirror Task 13's pattern.

### Gotcha #4 — `getAllByText('↑')` disambiguation (nice-to-verify)

The third plan test queries by exact text `'↑'` / `'↓'` — fine because
these arrows appear only as row-direction glyphs inside this component.
If the arrow appears elsewhere later, the test will break visibly — OK
for now. Don't change it.

### Gotcha #5 — `text-[10.5px]` arbitrary value

Tailwind's JIT accepts `10.5px` via arbitrary-value syntax. Verify
`observatory/web-src/tailwind.config.ts` has no `content: []` drift that
would fail to pick this up. The plan uses it; `tsc -b` won't catch
Tailwind class typos. Manual visual QA is deferred, so trust the plan.

### Gotcha #6 — `text-[10.5px]` + `font-mono` on a `<div>` body

The body div is rendered regardless of `<details>` open state (browser
hides the body when closed). Fine. Tests asserting row content must
render WITHOUT opening the details programmatically. The plan's tests
assume this and succeed because React renders the full DOM tree; only
browser layout hides closed-details children. In jsdom (testing
environment), `<details>` close state does NOT hide children from the
DOM queries — so tests work.

### Gotcha #7 — effect cleanup ordering

`[name]` dep on the incremental-scan effect means cycling regions
(via `[` / `]`) will unsubscribe, re-subscribe, re-seed. Good. Don't
restructure.

## Verification — all must pass

```bash
cd observatory/web-src
npx tsc -b
npm run test -- --run
npm run build
cd ../..
```

**Baseline:** 81 tests passing (Task 13 + review-fix shipped). Task 14
adds 3 tests → target: **84 passing**.

Don't run `python -m pytest` or `ruff` — frontend-only task.

## Commit

Stage exactly:

```bash
git add observatory/web-src/src/inspector/sections/Messages.tsx \
        observatory/web-src/src/inspector/Messages.test.tsx
```

Pre-existing untracked (leave alone):
- `_test_review_tmp/`
- `observatory/prompts/v2-task-13-prompt-stm-jsontree.md`
- `observatory/prompts/v2-task-14-messages.md`  (this prompt — leave as audit artifact)
- `regions/prefrontal_cortex/.gitignore`
- `regions/prefrontal_cortex/handlers/notebook.py`

Commit HEREDOC:

```
git commit -m "$(cat <<'EOF'
observatory: inspector Messages section — filter + auto-scroll (v2 task 14)

Client-side filter over the store envelope ring buffer via monotonic
envelopesReceivedTotal delta (plan's lastLenRef would miss envelopes
once the RING_CAP=5000 ring saturates — same class of bug as v1
Counters'). MAX_ROWS=100. Direction ↑/↓ by source-vs-destination.
Auto-scroll follows tail when user within 40 px of bottom; pauses
otherwise. Row expand-state keyed on observed_at|topic (stable across
MAX_ROWS-window shifts), not filtered-array index.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

One commit. No review-fix commits — controller drives those.

## Status report — return ONE of

- **DONE** — files created, tests pass, verification clean, commit
  created. Report:
  1. Commit SHA.
  2. Final test count.
  3. Any deviation from this prompt's instructions (gotchas #1–#7 are
     expected fixes; call out others).
- **DONE_WITH_CONCERNS** — same + something the controller should know.
- **NEEDS_CONTEXT** — a fact in this prompt is wrong.
- **BLOCKED** — structural blocker.

Execute. No confirmation needed.
