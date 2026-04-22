# Observatory v3 — Task 6 implementer prompt

You own one task end-to-end. Use `superpowers:test-driven-development`.

**Working directory:** `C:\repos\hive`.
**Node:** `cd observatory/web-src && npx vitest run && npx tsc -b`.

---

## Task

Build the **Topics tab** + `useTopicStats` 1 Hz selector hook.

### Authoritative references

- **Spec §6** (lines 160–190): row schema, derivation, selector contract, row click + expand.
- **Spec §8** (lines 209–237): click-through.
- **Spec §15** (lines 455–459): 1 Hz cadence for topic stats selector.
- **Plan Task 6** (`observatory/docs/plans/2026-04-22-observatory-v3-plan.md` lines 1724–2052).

---

## Plan Task 6 — verbatim

See lines 1724–2052 of the plan for the full task. Summary:

### Files
- Create: `observatory/web-src/src/dock/useTopicStats.ts`
- Create: `observatory/web-src/src/dock/useTopicStats.test.ts`
- Create: `observatory/web-src/src/dock/Topics.tsx`
- Create: `observatory/web-src/src/dock/Topics.test.tsx`
- Modify: `observatory/web-src/src/dock/Dock.tsx` (wire live topic count + mount Topics)

### `TopicStat` shape (spec §6.2, extended with `publisherLastSeen` for decay impl)

```typescript
export type TopicStat = {
  topic: string;
  ewmaRate: number;               // per-second, α=0.1
  sparkBuckets: number[];         // length 6, each = count in 10 s bucket
  publishers: Set<string>;        // source_region seen last 60 s
  publisherLastSeen: Map<string, number>;
  lastSeenMs: number;             // wallclock Date.now() of most recent envelope
};
```

### `useTopicStats` — verbatim hook (plan Step 3)

```typescript
import { useEffect, useRef, useState } from 'react';
import { useStore } from '../store';

export type TopicStat = { /* as above */ };

const ALPHA = 0.1;
const BUCKETS = 6;
const PUBLISHER_DECAY_MS = 60_000;

export function useTopicStats(): Map<string, TopicStat> {
  const [snapshot, setSnapshot] = useState<Map<string, TopicStat>>(new Map());
  const stateRef = useRef<Map<string, TopicStat>>(new Map());
  const lastIndexRef = useRef<number>(0);

  useEffect(() => {
    const tick = () => {
      const now = Date.now();
      const envs = useStore.getState().envelopes;
      const total = useStore.getState().envelopesReceivedTotal;

      const delta = Math.max(0, total - lastIndexRef.current);
      const take = Math.min(delta, envs.length);
      const fresh = envs.slice(envs.length - take);
      lastIndexRef.current = total;

      // Roll bucket window forward + decay old publishers
      for (const stat of stateRef.current.values()) {
        stat.sparkBuckets.shift();
        stat.sparkBuckets.push(0);
        for (const [pub, last] of stat.publisherLastSeen) {
          if (now - last > PUBLISHER_DECAY_MS) {
            stat.publisherLastSeen.delete(pub);
            stat.publishers.delete(pub);
          }
        }
      }

      // Absorb new envelopes
      for (const e of fresh) {
        let s = stateRef.current.get(e.topic);
        if (!s) {
          s = {
            topic: e.topic,
            ewmaRate: 0,
            sparkBuckets: new Array(BUCKETS).fill(0),
            publishers: new Set<string>(),
            publisherLastSeen: new Map<string, number>(),
            lastSeenMs: now,
          };
          stateRef.current.set(e.topic, s);
        }
        s.sparkBuckets[BUCKETS - 1] += 1;
        s.lastSeenMs = now;
        if (e.source_region) {
          s.publishers.add(e.source_region);
          s.publisherLastSeen.set(e.source_region, now);
        }
      }

      // EWMA on per-tick count
      const perTopicCount = new Map<string, number>();
      for (const e of fresh) perTopicCount.set(e.topic, (perTopicCount.get(e.topic) ?? 0) + 1);
      for (const stat of stateRef.current.values()) {
        const n = perTopicCount.get(stat.topic) ?? 0;
        stat.ewmaRate = ALPHA * n + (1 - ALPHA) * stat.ewmaRate;
      }

      setSnapshot(new Map(stateRef.current));
    };
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return snapshot;
}
```

### Topics tests (plan Step 1, 3 test total — stats empty / accumulates / decays)

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';
import { useTopicStats } from './useTopicStats';
import { useStore } from '../store';

describe('useTopicStats', () => {
  beforeEach(() => { vi.useFakeTimers(); useStore.setState({ envelopes: [], envelopesReceivedTotal: 0 }); });
  afterEach(() => { vi.useRealTimers(); cleanup(); });

  it('returns empty map initially', () => { /* ... */ });
  it('accumulates after first tick', () => { /* ... */ });
  it('publishers decay after 60 s of no envelopes', () => { /* ... */ });
});
```

Plan's Step 5 Topics tests: empty state message + no-crash when envelopes exist.

### Topics component (plan Step 6)

`Sparkline` SVG (inline 48×8 bars), `Row` component (topic · kind · rate · sparkline · publishers count · relativeTime · chevron → expand to recent 5), `Topics` wrapper (sorts by rate desc, lastSeenMs asc as tiebreaker; empty-state message).

---

## Drifts you MUST handle

### Drift A — `useTopicStats` called twice (once in Dock for count, once in Topics for rows)

Plan Step 7 shows `Dock.tsx` calling `useTopicStats()` to get `topicCount`. Plan Step 6 shows `Topics.tsx` independently calling `useTopicStats()` for rows. Two separate hook instances = two separate `useState`/`useEffect`/`setInterval` pairs = state divergence + duplicated work.

**Fix:** call the hook **once** in `Dock.tsx`, pass the map down:

```tsx
// Dock.tsx
const topicStats = useTopicStats();
const topicCount = topicStats.size;
// ...
<DockTabStrip firehoseRate={firehoseRate} topicCount={topicCount} metacogBadge={{count: 0, severity: 'quiet'}} />
{!collapsed && tab === 'topics' && <Topics stats={topicStats} />}
```

Update `Topics` signature: `export function Topics({ stats }: { stats: Map<string, TopicStat> }) { ... }`.

Update the `Topics.test.tsx` to pass a map:
```tsx
const { container } = render(<Topics stats={new Map()} />);  // empty-state
```

For the "no crash when envelopes" test, you can either (a) construct a stats map directly in the test and pass it in, or (b) keep calling `useTopicStats()` inside a wrapper. Option (a) is cleaner — the component under test is now pure from props.

### Drift B — `Row`'s `recent5` computed via reactive `useStore((s) => s.envelopes)`

Plan Step 6's `Row` component reads `envelopes` reactively and recomputes `recent5 = envelopes.filter((e) => e.topic === stat.topic).slice(-5).reverse()` on every envelope push. For N visible topic rows and a 5000-element ring, that's N filter ops per push — potentially expensive at firehose rates.

**Fix (preferred):** compute `recent5` INSIDE `useTopicStats` at 1 Hz, stash as `TopicStat.recent5`. Row reads `stat.recent5` (non-reactive). Add to the `TopicStat` type:

```typescript
export type TopicStat = {
  // ...
  recent5: Envelope[];             // last 5 envelopes on this topic, newest-first
};
```

In the hook's `tick()`, after absorbing new envelopes, compute `recent5` per topic:

```typescript
for (const stat of stateRef.current.values()) {
  stat.recent5 = envs.filter((e) => e.topic === stat.topic).slice(-5).reverse();
}
```

Or more efficiently, walk backward through `envs` once and bucket into `stat.recent5`:

```typescript
// Initialize empties for this tick
for (const stat of stateRef.current.values()) stat.recent5 = [];
for (let i = envs.length - 1; i >= 0; i--) {
  const e = envs[i];
  const s = stateRef.current.get(e.topic);
  if (s && s.recent5.length < 5) s.recent5.push(e);
}
```

Note: recent5 is "newest-first" (the plan's `.reverse()` achieves this).

Import `Envelope` from `../store` at the top of `useTopicStats.ts`.

Update `Row` in `Topics.tsx`:
```tsx
function Row({ stat }: { stat: TopicStat }) {
  const [expanded, setExpanded] = useState(false);
  const recent5 = stat.recent5;  // non-reactive
  // ...
}
```

### Drift C — Scene outline ring on topic row click NOT implemented

Spec §6.1 (line 171):
> "Row click: select the publisher with the most recent envelope on that topic + camera fit + inspector open. Additionally every region currently publishing that topic (within last 60 s) gets a 2 px outline ring in the scene until the user selects another row or dismisses."

Plan Task 6 does **not** implement the 2 px outline ring. This requires scene-level state + rendering (a new store field like `outlinedRegions: Set<string>` consumed by FuzzyOrbs / scene).

**Decision:** DEFER this to a follow-up. Do not add scene changes in Task 6. Document the gap in `observatory/memory/decisions.md` noting the scope split. Task 11 may pick it up or bump to v4.

The basic row click — `selectRegionFromRow` with the most recent publisher — stays per plan.

### Drift D — Empty-state copy

Plan Step 6 uses `"No topics yet — waiting for envelopes…"`. Spec doesn't specify the exact copy. Keep plan's wording.

---

## Existing-contract surface

**`observatory/web-src/src/store.ts`:**
- `envelopes: Envelope[]` (RING_CAP=5000), `envelopesReceivedTotal: number` (monotonic), `pushEnvelope`.
- `Envelope` type already exported: `{ observed_at, topic, envelope, source_region: string|null, destinations[] }`.

**`observatory/web-src/src/dock/selectRegionFromRow.ts`** (Task 4): pure helper.

**`observatory/web-src/src/scene/topicColors.ts`** (Task 5): `kindTag(topic) -> string`.

**`observatory/web-src/src/dock/Dock.tsx`** (current): has `useFirehoseRate()`. You add `useTopicStats()` alongside. Passes `topicCount={topicStats.size}` to `<DockTabStrip>` and `<Topics stats={topicStats} />` for the topics tab.

## Gotchas

- **`vi.useFakeTimers()` + `vi.advanceTimersByTime()`:** required for testing the 1 Hz interval deterministically. The plan's test uses this pattern.
- **`act()` around timer advancement:** wrap `vi.advanceTimersByTime(...)` in `act()` so React flushes the resulting state update before assertions.
- **`setSnapshot(new Map(stateRef.current))`:** forces React to treat the state as new (reference-changed), even when the Map contents are conceptually the same. Necessary so subscribers re-render after a tick.
- **`lastIndexRef`/`total` delta:** see decisions entry 82 for the monotonic-counter pattern. This replaces the `envelopes.length`-based incremental scan which breaks once the ring caps.
- **`publishers.clear()` on decay:** the plan's code calls `publisherLastSeen.delete(pub)` + `publishers.delete(pub)` together. Don't skip one or the other.
- **`publishers: new Set<string>()`** — React's `useState` with a Map of Sets: when the Map is cloned via `new Map(...)`, the inner Sets are shared references. This is fine for reads, but if a consumer later mutates a Set, it would be visible in the ref's next tick. Don't mutate from consumers.
- **Sparkline height `(n / max) * 8`:** when all buckets are zero, `max = Math.max(1, ...)` guarantees no div-by-zero.
- **`new Date(ms).toISOString().slice(11, 23)`** — same HH:MM:SS.mmm pattern as Firehose.

## Verification gates (all must pass before commit)

```
cd observatory/web-src && npx vitest run && npx tsc -b
cd ../.. && .venv/Scripts/python.exe -m ruff check observatory/
```

Expected: **~146 frontend tests** (was 141 after Task 5 → add 3 useTopicStats + 2 Topics = +5 = 146). tsc clean, ruff clean.

## Hard rules

- Do NOT touch region_template/, glia/, regions/, bus/, shared/.
- Do NOT add scene changes (outline rings) — that's Drift C, deferred.
- Do NOT push.
- TDD: tests first, observe red, then green.
- If spec-vs-plan conflict surfaces beyond A–D, stop with `NEEDS_CONTEXT`.

## Commit HEREDOC

```bash
git add observatory/web-src/src/dock/ observatory/memory/decisions.md
git commit -m "$(cat <<'EOF'
observatory: topics tab + useTopicStats (v3 task 6)

1 Hz selector builds Map<topic, TopicStat> with EWMA rate (α=0.1),
rolling 6-bucket * 10 s sparkline, publisher set decaying after 60 s
of silence, wallclock last-seen, and recent-5 envelope list (computed
inside the tick so Row stays non-reactive). Topics tab renders rows
sorted by ewmaRate desc (tie-break lastSeenMs asc) with per-row expand
into last 5 envelopes. Reuses selectRegionFromRow for click-through.

Dock calls useTopicStats once and threads the map to both the badge
count and the Topics component — single interval, single state. The
scene-outline-ring spec §6.1/§8 behavior is deferred to a follow-up
(decisions.md logged).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Report format

1. Status / SHA / files touched
2. Test delta (before/after)
3. Drift handling summary (A/B/C/D)
4. Any other drift
5. Concerns
