# Observatory v3 — Task 10 implementer prompt

One task, end-to-end. `superpowers:test-driven-development`. Report status + SHA.

**Working directory:** `C:\repos\hive`. **Node:** `cd observatory/web-src && npx vitest run && npx tsc -b`.

---

## Task

Upgrade `Messages.tsx`: replace the plain `<pre>` JSON expansion with the shared `JsonTree` component, and consume `store.pendingEnvelopeKey` to scroll-and-expand a specific row (set by Firehose or Metacog click-through from Tasks 5/7).

### Authoritative references

- **Spec §7.2** (lines 205-208): Metacog click-through sets `pendingEnvelopeKey`; Messages consumes + clears on mount or selectRegion change.
- **Spec §11** (lines 334-341): Messages section upgrade — chevron expand uses JsonTree; key `${observed_at}|${topic}`; `pendingEnvelopeKey` causes scroll + auto-expand.
- **Plan Task 10:** `observatory/docs/plans/2026-04-22-observatory-v3-plan.md` lines 2744-2847.

---

## Plan Task 10 — verbatim (with drifts below)

### Files
- Modify: `observatory/web-src/src/inspector/sections/Messages.tsx`
- Modify: `observatory/web-src/src/inspector/Messages.test.tsx`

### Contract

- Chevron per row; clicking toggles expand state for that row.
- Expanded row renders `<JsonTree value={env.envelope as unknown as JsonValue} />` inline below the row.
- Row identity key `${observed_at}|${topic}` — matches v2 Task 14's current key shape.
- `pendingEnvelopeKey` consumption: when set to a non-null key matching a visible row's id, scroll that row into view + auto-expand it, then clear `pendingEnvelopeKey` (by calling `setPendingEnvelopeKey(null)`).
- Auto-scroll-to-bottom for NEW envelopes (existing v2 behavior) must stay intact. The pendingEnvelopeKey scroll is a one-shot override.

---

## Drifts you MUST correct

### Drift A — Expand state lives LOCAL to Messages, not in `store.expandedRowIds`

Plan's Step 3 reads `expandedRowIds = useStore((s) => s.expandedRowIds)` and calls `toggleRowExpand` from the store. **This is wrong for Messages.**

`store.expandedRowIds` is dock-scoped (spec §12 line 355): *"transient, cleared on tab change"* (see `setDockTab` in store.ts). Firehose uses it for in-row payload expand; when the user switches dock tabs, it clears. Messages is in the inspector panel, NOT the dock — sharing the same Set would:
- Cause dock tab switches to collapse Messages rows (bad).
- Cross-contaminate: expand a Firehose row with key X, Messages row with the same key also expands silently.

**Fix:** keep Messages' existing LOCAL `expanded: Set<string>` state (see current `Messages.tsx:31`). Preserve `setExpanded((s) => { const n = new Set(s); ... })` toggle pattern. Only `pendingEnvelopeKey` + `setPendingEnvelopeKey` are read from the store.

### Drift B — Replace `<pre>{JSON.stringify(...)}` with `<JsonTree value={...} />`

Current Messages.tsx:121-125:
```tsx
{isExpanded && (
  <pre className="text-[10px] text-[#8a8e99] whitespace-pre-wrap pl-[76px] pt-1">
    {JSON.stringify(e.envelope, null, 2)}
  </pre>
)}
```

Replace with the shared JsonTree (same component used by v2 STM + v3 Firehose):

```tsx
{isExpanded && (
  <div className="text-[10px] pl-[76px] pt-1">
    <JsonTree value={e.envelope as unknown as JsonValue} />
  </div>
)}
```

Imports:
```tsx
import { JsonTree, type JsonValue } from './JsonTree';
```

### Drift C — Row has an explicit chevron button

Current Messages renders its entire row as clickable (onClick on the whole `.grid` div) to toggle expand. That's OK, but spec §11 intent is a chevron. Add an explicit chevron visual at the end of the row. Keep the row-click-to-toggle for UX continuity:

```tsx
<div
  className="grid grid-cols-[60px_14px_1fr_16px] gap-2 cursor-pointer items-start"
  onClick={() => setExpanded(toggle(id))}
>
  <span className="text-[#8a8e99]">{renderTime(e.observed_at)}</span>
  <span className={direction === '↑' ? 'text-[#ffb36a]' : 'text-[#8fd6a0]'}>{direction}</span>
  <span>
    {e.topic}
    {!isExpanded && <span className="text-[#8a8e99]"> &nbsp;{previewPayload(e)}</span>}
  </span>
  <span className="text-[#8a8e99] text-[10px]">{isExpanded ? '▾' : '▸'}</span>
</div>
```

Where `toggle(id)` is a local helper:
```tsx
const toggle = (id: string) => (s: Set<string>) => {
  const n = new Set(s);
  if (n.has(id)) n.delete(id); else n.add(id);
  return n;
};
```

Or inline the set-mutation as the current code does — whichever reads cleaner.

### Drift D — `pendingEnvelopeKey` consumption

Add the hook:

```tsx
const pendingKey = useStore((s) => s.pendingEnvelopeKey);
const setPendingKey = useStore((s) => s.setPendingEnvelopeKey);
const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());

useEffect(() => {
  if (!pendingKey) return;
  // Check if the target row is currently rendered; if so, scroll + expand.
  // If not, still clear the key (spec §7.2: "consumes + clears").
  const node = rowRefs.current.get(pendingKey);
  if (node) {
    node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    setExpanded((s) => {
      if (s.has(pendingKey)) return s;
      const n = new Set(s);
      n.add(pendingKey);
      return n;
    });
    // Pending-key scroll is a one-shot override of follow-tail auto-scroll.
    followTailRef.current = false;
  }
  setPendingKey(null);
}, [pendingKey, setPendingKey]);
```

Attach ref to each row:
```tsx
<div
  key={id}
  ref={(n) => {
    if (n) rowRefs.current.set(id, n);
    else rowRefs.current.delete(id);
  }}
  className="py-1 border-b border-dotted border-[#23232b]"
>
  ... inner grid + expanded JsonTree
</div>
```

`followTailRef.current = false` after a pending-key scroll prevents the next new-envelope auto-scroll from yanking the user away. If the user later scrolls to the bottom manually, the existing `onScroll` listener flips `followTailRef` back to true.

### Drift E — MAX_ROWS 100 vs spec §7

Spec doesn't specify a Messages MAX_ROWS. Current impl has `MAX_ROWS = 100`. Preserve unchanged.

---

## Existing-contract surface

**`observatory/web-src/src/inspector/sections/Messages.tsx`** (current v2 Task 14 shape):
- Props: `{name: string}`.
- Local `filtered: Envelope[]` + `expanded: Set<string>` state.
- `lastTotalRef` for incremental scan via monotonic `envelopesReceivedTotal` counter.
- `containerRef` + `followTailRef` for auto-scroll-to-bottom.
- Row identity key `${e.observed_at}|${e.topic}` — exact key shape pendingEnvelopeKey will match.
- Renders direction arrow `↑`/`↓` + timestamp + topic + preview + pre-wrapped JSON.

**`observatory/web-src/src/store.ts`**:
- `pendingEnvelopeKey: string | null` (default null).
- `setPendingEnvelopeKey: (key: string | null) => void`.
- Both wired in Task 2.

**`observatory/web-src/src/inspector/sections/JsonTree.tsx`**:
- `export function JsonTree({ value, depth = 0 }: { value: JsonValue; depth?: number })`.
- `export type JsonValue = string | number | boolean | null | JsonArray | JsonObject`.
- Already used by STM (v2 Task 13) + Firehose (v3 Task 5).

**`observatory/web-src/src/inspector/Messages.test.tsx`**:
- Existing 3 tests; `describe('Messages', () => { ... })`. Uses `beforeEach` to reset store + seed a region named `'r'`.
- Envelope push pattern: `useStore.getState().pushEnvelope({observed_at, topic, envelope, source_region, destinations})`.

## Tests to add

Append to `Messages.test.tsx`:

```tsx
import { fireEvent, waitFor } from '@testing-library/react';

it('chevron click expands row to JsonTree view', () => {
  useStore.getState().pushEnvelope({
    observed_at: 0, topic: 'hive/x', envelope: { goal: 'reach', priority: 0.7 },
    source_region: 'r', destinations: [],
  });
  const { container } = render(<Messages name="r" />);
  // Collapsed: preview contains the JSON.stringify prefix, but no JsonTree key
  // row rendered yet. Click the row to expand.
  const row = container.querySelector('.grid') as HTMLElement;
  fireEvent.click(row);
  // After expand, JsonTree renders the key "goal" in the value map.
  expect(container.textContent).toContain('goal');
  expect(container.textContent).toContain('reach');
});

it('pendingEnvelopeKey scrolls + auto-expands then clears the key', async () => {
  useStore.getState().pushEnvelope({
    observed_at: 100, topic: 'hive/metacog/error', envelope: { kind: 'LlmError', detail: 'rate_limit' },
    source_region: 'r', destinations: [],
  });
  const { container } = render(<Messages name="r" />);
  // Trigger the consumption pathway:
  useStore.getState().setPendingEnvelopeKey('100|hive/metacog/error');
  await waitFor(() => {
    // Key should clear after consumption.
    expect(useStore.getState().pendingEnvelopeKey).toBeNull();
  });
  // Row should now be expanded (JsonTree renders "kind" key).
  expect(container.textContent).toContain('kind');
  expect(container.textContent).toContain('LlmError');
});
```

## Gotchas

- **`JsonTree` is in `./JsonTree` relative to Messages.tsx** (both live in `sections/`). Import path: `import { JsonTree, type JsonValue } from './JsonTree'`.
- **`env.envelope` type is `Record<string, unknown>`**; JsonValue is a recursive union. The `as unknown as JsonValue` cast is the established pattern (see Firehose FirehoseRow.tsx:96 + decisions entry 97).
- **`scrollIntoView` in jsdom:** jsdom 20+ implements `scrollIntoView` as a no-op (doesn't throw). The test can't verify scroll position but can verify the expand state + key-clear side effects. That's sufficient.
- **`rowRefs.current.delete(id)` on unmount callback:** `ref={(n) => { ... }}` fires with `null` on unmount. The `else rowRefs.current.delete(id)` guard handles it.
- **Preserve `followTail` behavior:** after the pendingKey scroll, set `followTailRef.current = false` so the next new-envelope auto-scroll doesn't yank the user away. User can restore by scrolling to bottom manually.
- **Test's `setPendingEnvelopeKey` triggers a re-render** which fires the useEffect. `waitFor` handles async state settle.

## Verification gates

```
cd observatory/web-src && npx vitest run && npx tsc -b
cd ../.. && .venv/Scripts/python.exe -m ruff check observatory/
```

Expected: **165 → 167 frontend tests** (+2 Messages tests). tsc clean, ruff clean.

## Hard rules

- Do NOT touch region_template/, glia/, regions/, bus/, shared/.
- Do NOT modify JsonTree / store.ts / pendingEnvelopeKey store plumbing.
- Do NOT push.
- TDD: tests first, red, then green.
- If spec/plan conflict surfaces beyond A-E, stop with NEEDS_CONTEXT.

## Commit HEREDOC

```bash
git add observatory/web-src/src/inspector/
git commit -m "$(cat <<'EOF'
observatory: Messages — JsonTree expand + pendingEnvelopeKey (v3 task 10)

Row chevron expands full envelope JSON via shared JsonTree component
(same instance used by v2 Stm + v3 Firehose/Topics/Metacog). Expanded
JSON replaces the v2 pre-wrapped JSON.stringify output. Expand state
stays LOCAL to Messages (store.expandedRowIds is dock-scoped per spec
§12 and would cross-contaminate with Firehose + clear on dock tab
switch — wrong for the inspector panel).

pendingEnvelopeKey consumption: when the store field is set to a row
identity key ({observed_at}|{topic}), Messages scrolls that row into
view and auto-expands, then clears the key (spec §7.2). Pending-key
scroll sets followTailRef=false so the next new-envelope auto-scroll
doesn't yank the user away from the highlighted row.

v2 auto-scroll-to-bottom for new envelopes and incremental scan
against envelopesReceivedTotal stay intact.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Report format

1. Status / SHA / files touched
2. Test delta (165 → 167 expected)
3. Drift handling (A/B/C/D/E)
4. Other drift
5. Concerns
