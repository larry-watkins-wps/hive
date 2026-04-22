# Observatory v3 — Task 7 implementer prompt

One task, end-to-end. `superpowers:test-driven-development`. Report status + SHA when done.

**Working directory:** `C:\repos\hive`.
**Node:** `cd observatory/web-src && npx vitest run && npx tsc -b`.

---

## Task

Build the **Metacognition tab** and its dock-strip badge.

### Authoritative references

- **Spec §7** (lines 192–208): row schema, title extraction, coloring, click-through.
- **Spec §4.2 line 86** (dock badge severity colors): red if errors-in-60s > 0, amber if conflicts > 0 && errors == 0, grey otherwise.
- **Spec §8** (lines 209–237): click-through → selectRegionFromRow.
- **Plan Task 7:** `observatory/docs/plans/2026-04-22-observatory-v3-plan.md` lines 2055–2230.

---

## Plan Task 7 — verbatim

See plan lines 2055–2230. Summary of the contract:

### Files
- Create: `observatory/web-src/src/dock/Metacog.tsx`
- Create: `observatory/web-src/src/dock/Metacog.test.tsx`
- Modify: `observatory/web-src/src/dock/Dock.tsx`

### Row schema (spec §7.1)

```
HH:MM:SS.mmm  source_region    event-kind         title
14:22:05.112  amygdala         error.detected     LlmError: rate_limit_exceeded …
```

- Columns: `ts · source · event-kind (last two topic segments joined with '.') · title (≤120 chars)`.
- Row coloring: `error.*` left-border `#ff8a88`, `conflict.*` `#ffc07a`, `reflection.*` `rgba(210,212,220,.55)`.
- Title extraction: for errors, `payload.data.kind + ': ' + payload.data.detail` when both present; fall back to `JSON.stringify(payload.data).slice(0, 120)`.
- Row click: `selectRegionFromRow` (which sets `pendingEnvelopeKey` — Task 10 consumes this to scroll+expand in Messages).
- Empty-state: "No metacognition events yet."
- Auto-scroll near-bottom (40 px window).

### Dock badge (spec §4.2)

Count = metacog events in last 60 s. Severity:
- `errors-last-60s > 0` → severity `error` (red).
- `errors == 0 && conflicts > 0` → `conflict` (amber).
- else → `quiet` (grey).

### Plan Step 1 — failing tests

```tsx
import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanup } from '@testing-library/react';
import { Metacog } from './Metacog';
import { useStore } from '../store';

afterEach(() => { cleanup(); useStore.setState({ envelopes: [], envelopesReceivedTotal: 0 }); });

function pushMetacog(topic: string, source: string, data: unknown, observed_at = Date.now()) {
  useStore.getState().pushEnvelope({
    observed_at,
    topic,
    envelope: { payload: { content_type: 'application/json', data } } as unknown as Record<string, unknown>,
    source_region: source,
    destinations: [],
  });
}

describe('Metacog', () => {
  it('filters to hive/metacognition topics', () => {
    pushMetacog('hive/metacognition/error/detected', 'pfc', { kind: 'E', detail: 'd' });
    pushMetacog('hive/cognitive/pfc/plan', 'pfc', {});
    const { container } = render(<Metacog />);
    expect(container.querySelectorAll('[data-testid="metacog-row"]').length).toBe(1);
  });

  it('extracts title as kind + ": " + detail for errors', () => {
    pushMetacog('hive/metacognition/error/detected', 'pfc', { kind: 'LlmError', detail: 'rate_limit' });
    const { getByText } = render(<Metacog />);
    expect(getByText(/LlmError:\s*rate_limit/)).toBeTruthy();
  });
});
```

### Plan Step 3 — Metacog component (see plan for verbatim code; apply drifts below)

### Plan Step 4 — `useMetacogBadge()` in Dock.tsx (see plan; apply Drift A below)

---

## Drifts you MUST correct

### Drift A — `useMetacogBadge` reactivity

Plan's `useMetacogBadge` reads `envs` via `useStore((s) => s.envelopes)` reactively. Every envelope push re-runs the filter (O(ring)) and re-renders the Dock (which re-renders DockTabStrip). At firehose rates this is wasteful.

**Fix:** compute the badge at 1 Hz like `useFirehoseRate` (Task 5) and `useTopicStats` (Task 6):

```typescript
function useMetacogBadge(): { count: number; severity: 'error' | 'conflict' | 'quiet' } {
  const [badge, setBadge] = useState<{ count: number; severity: 'error' | 'conflict' | 'quiet' }>({ count: 0, severity: 'quiet' });
  useEffect(() => {
    const compute = () => {
      const envs = useStore.getState().envelopes;
      const now = Date.now();
      const recent = envs.filter((e) => e.topic.startsWith('hive/metacognition/') && now - e.observed_at < 60_000);
      const errors = recent.filter((e) => e.topic.includes('/error/')).length;
      const conflicts = recent.filter((e) => e.topic.includes('/conflict/')).length;
      setBadge({
        count: recent.length,
        severity: errors > 0 ? 'error' : conflicts > 0 ? 'conflict' : 'quiet',
      });
    };
    compute();  // initial tick
    const id = setInterval(compute, 1000);
    return () => clearInterval(id);
  }, []);
  return badge;
}
```

Same pattern as decisions entry 82 (monotonic polling, `useStore.getState()` inside the interval). The badge updates at 1 Hz, matching the other dock-strip badges.

### Drift B — Row height pin + source ellipsis width

Task 5 review-fix pinned Firehose rows to `h-[22px]` and source ellipsis to `max-w-[18ch]` per spec §5.1. Apply the same treatment to Metacog rows for consistency:

- Add `h-[22px]` to the row `<div>` className.
- Change `max-w-[14ch]` → `max-w-[18ch]` on the source span.

Spec §7 doesn't specify a row height but §5.1's 22 px is the dock-row standard; consistency beats inventing a different height for one tab.

### Drift C — `JSON.stringify(undefined)` defensive fallback

Plan's `titleOf`:
```typescript
try { return JSON.stringify(data).slice(0, 120); } catch { return String(data ?? ''); }
```

Same bug class as Task 5 Code I1: `JSON.stringify(undefined)` returns `undefined` (not a string), so `.slice(...)` throws TypeError.

**Fix:**
```typescript
try { return (JSON.stringify(data ?? null) ?? '').slice(0, 120); } catch { return String(data ?? ''); }
```

The `?? null` handles undefined → `"null"`; outer `?? ''` defends against any future edge case returning undefined.

### Drift D — Dock.tsx integration shape

After wiring `useMetacogBadge()`:

```tsx
// Inside Dock() body:
const firehoseRate = useFirehoseRate();
const topicStats = useTopicStats();
const metacogBadge = useMetacogBadge();

// JSX:
<DockTabStrip
  firehoseRate={firehoseRate}
  topicCount={topicStats.size}
  metacogBadge={metacogBadge}
/>
{!collapsed && (
  <div className="flex-1 overflow-hidden">
    {tab === 'firehose' && <Firehose />}
    {tab === 'topics' && <Topics stats={topicStats} />}
    {tab === 'metacog' && <Metacog />}
  </div>
)}
```

Delete `MetacogPlaceholder` (only the Metacog one; all three placeholders are gone after this task).

### Drift E — Dock.test.tsx update

The existing third test `'mounts the placeholder for the active tab'` was updated during Task 5 to swap the firehose placeholder for the real Firehose empty-state, and during Task 6 to swap the topics placeholder for the real Topics empty-state. Update for metacog as well: switch `useStore.setState({ dockTab: 'metacog' })` + assert Metacog's empty-state `"No metacognition events yet."` text surfaces.

---

## Existing-contract surface

**`observatory/web-src/src/store.ts`:**
- `Envelope` type (ts, topic, envelope, source_region, destinations[]).
- `envelopes: Envelope[]`, `envelopesReceivedTotal: number`, `pushEnvelope`, `applySnapshot`.

**`observatory/web-src/src/dock/selectRegionFromRow.ts`** (Task 4): `selectRegionFromRow(store, { regionName, envelopeKey })` → calls `select` + `setPendingEnvelopeKey`.

**`observatory/web-src/src/dock/Dock.tsx`** (current after Task 6): has `useFirehoseRate()` + `useTopicStats()`. Passes `firehoseRate`, `topicCount`, and `metacogBadge={{ count: 0, severity: 'quiet' }}` placeholder. Mounts `<Firehose />` + `<Topics stats={topicStats} />` + `MetacogPlaceholder`. Your task wires the real `useMetacogBadge()` + `<Metacog />`.

**`observatory/web-src/src/dock/Dock.test.tsx`**: three tests. Third test swaps placeholders for real components per-tab. Update metacog branch to assert Metacog's empty-state copy.

## Gotchas

- **Vitest globals:** import from `'vitest'` explicitly.
- **`data-testid="metacog-row"`** per plan's test — preserve it.
- **`parts.at(-2)` / `parts.at(-1)`** — `Array.prototype.at` is standard; works in TS 5 / ES2022.
- **topic.startsWith('hive/metacognition/')** — single source of truth for the filter (both Metacog and useMetacogBadge).
- **`titleOf(env)` receives `Envelope`** (outer); `env.envelope` is the inner record; `env.envelope.payload.data` is the metacog payload. Same access pattern as Firehose.
- **Keep plan's `${e.observed_at}|${e.topic}` key** — spec §7.2 line 208 uses the same shape for `pendingEnvelopeKey` consumption in Messages (Task 10).
- **React strict-mode double-mount** — `useMetacogBadge`'s `useEffect([])` cleanup clears the interval; no leak.

## Verification gates

```
cd observatory/web-src && npx vitest run && npx tsc -b
cd ../.. && .venv/Scripts/python.exe -m ruff check observatory/
```

Expected: **149 → 151 frontend tests** (+2 Metacog). Ruff clean. tsc clean.

## Hard rules

- Do NOT touch region_template/, glia/, regions/, bus/, shared/.
- Do NOT break existing Firehose/Topics behavior.
- Do NOT push.
- TDD: tests first, red, then green.
- If spec/plan conflict surfaces beyond A–E, stop with `NEEDS_CONTEXT`.

## Commit HEREDOC

```bash
git add observatory/web-src/src/dock/
git commit -m "$(cat <<'EOF'
observatory: metacognition tab + badge (v3 task 7)

Filters envelope ring to hive/metacognition/#; rows colored by kind
(error red, conflict amber, reflection grey) via left-border accent.
Title extraction uses payload.data.kind + ': ' + payload.data.detail
for errors, falling back to JSON.stringify(data ?? null) ?? '' with
120-char cap. Dock tab badge computed at 1 Hz (matches useFirehoseRate
and useTopicStats cadence): count-last-60s + severity red/amber/grey
per spec §4.2. Row height pinned h-[22px]; source ellipsis 18ch per
Task 5 review-fix precedent.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Report format

1. Status / SHA / files touched
2. Test delta (before/after)
3. Drift handling (A–E)
4. Other drift
5. Concerns
