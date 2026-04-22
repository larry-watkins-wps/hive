# Observatory v3 — Task 5 implementer prompt

You are an implementer subagent. One task, end-to-end. Report status + SHA when done. Use `superpowers:test-driven-development`.

**Working directory:** `C:\repos\hive`. **Node:** `cd observatory/web-src && npx vitest run && npx tsc -b`.

---

## Task

Build the **Firehose tab** + extend `topicColors.ts` with a new `kindTag(topic)` label mapper and a few missing prefix colors.

### Authoritative references

- **Spec §5 — Firehose tab** (lines 101–158): row schema, filter rules, kind-tag table, click-through, in-row payload expand.
- **Spec §8 — Interaction model** (lines 209–237): row click → `selectRegionFromRow`.
- **Spec §15 — Performance** (lines 455–459): max 1000 rendered rows; no per-frame allocations.
- **Plan Task 5**: `observatory/docs/plans/2026-04-22-observatory-v3-plan.md` lines 1347–1722.

---

## Plan Task 5 — verbatim

### Files
- Create: `observatory/web-src/src/dock/Firehose.tsx`
- Create: `observatory/web-src/src/dock/FirehoseRow.tsx`
- Create: `observatory/web-src/src/dock/Firehose.test.tsx`
- Modify: `observatory/web-src/src/scene/topicColors.ts`
- Modify: `observatory/web-src/src/scene/topicColors.test.ts`
- Modify: `observatory/web-src/src/dock/Dock.tsx` (wire real Firehose + live rate)

### Contract (spec §5)

- **Row schema:** `HH:MM:SS.mmm` · `source_region` · `→ topic` · `kind` badge · payload preview · chevron.
- **Preview (§5.1):** if `payload.content_type === 'application/json'` → `JSON.stringify(payload.data).slice(0, 120)`. Else `String(payload.data).slice(0, 120)`. Replace `\n` with `↵`. Trailing ellipsis when truncated.
- **Filter (§5.2):** substring (case-insensitive) by default; `/regex/` or `/regex/i` if the input starts with `/` and ends with `/` or `/i`. Invalid regex → red border, no filtering. 150 ms debounce. Filter state NOT persisted.
- **Pause:** snapshot the envelope ring at pause-time; while paused, do not re-read. On unpause, snap back to live.
- **Max rendered rows:** 1000.
- **Auto-scroll:** to newest when `scrollHeight - scrollTop - clientHeight < 40 px`.
- **Expand:** keyed by `${observed_at}|${topic}|${source_region ?? ''}`. Chevron toggles `toggleRowExpand`.

### Steps (plan verbatim code — preserve it unless a drift below overrides)

**Step 1 — Extend `topicColors.ts` with `kindTag`:**

```typescript
export function kindTag(topic: string): string {
  if (topic.startsWith('hive/cognitive/')) return 'cog';
  if (topic.startsWith('hive/sensory/')) return 'sns';
  if (topic.startsWith('hive/motor/')) return 'mot';
  if (topic.startsWith('hive/metacognition/')) return 'meta';
  if (topic.startsWith('hive/self/')) return 'self';
  if (topic.startsWith('hive/modulator/')) return 'mod';
  if (topic.startsWith('hive/attention/')) return 'att';
  if (topic.startsWith('hive/interoception/')) return 'intr';
  if (topic.startsWith('hive/habit/')) return 'hab';
  if (topic.startsWith('hive/rhythm/')) return 'rhy';
  if (topic.startsWith('hive/system/heartbeat/')) return 'hb';
  if (topic.startsWith('hive/system/region_stats/')) return 'rst';
  if (topic.startsWith('hive/system/metrics/')) return 'mtr';
  if (topic.startsWith('hive/system/sleep/')) return 'slp';
  if (topic.startsWith('hive/system/spawn/')) return 'spn';
  if (topic.startsWith('hive/system/codechange/')) return 'cc';
  if (topic.startsWith('hive/broadcast/')) return 'bcst';
  return '?';
}
```

**Step 2 — `kindTag` tests** (append to `topicColors.test.ts`):

```typescript
import { kindTag } from './topicColors';
describe('kindTag', () => {
  const cases: Array<[string, string]> = [
    ['hive/cognitive/pfc/plan', 'cog'],
    ['hive/sensory/visual/features', 'sns'],
    ['hive/motor/intent', 'mot'],
    ['hive/metacognition/error/detected', 'meta'],
    ['hive/self/identity', 'self'],
    ['hive/modulator/dopamine', 'mod'],
    ['hive/attention/focus', 'att'],
    ['hive/interoception/felt_state', 'intr'],
    ['hive/habit/suggestion', 'hab'],
    ['hive/rhythm/gamma', 'rhy'],
    ['hive/system/heartbeat/pfc', 'hb'],
    ['hive/system/region_stats/pfc', 'rst'],
    ['hive/system/metrics/compute', 'mtr'],
    ['hive/system/sleep/granted', 'slp'],
    ['hive/system/spawn/complete', 'spn'],
    ['hive/system/codechange/approved', 'cc'],
    ['hive/broadcast/shutdown', 'bcst'],
    ['unknown/topic', '?'],
  ];
  it.each(cases)('%s → %s', (topic, tag) => expect(kindTag(topic)).toBe(tag));
});
```

**Step 3 — Firehose tests.** (See plan's Step 3 code — 4 tests total covering: rows rendered, substring filter case-insensitive, regex filter, pause snapshots ring.)

**Step 4 — red.**

**Step 5 — `FirehoseRow`.** See plan's Step 5 code. Key bits: `previewOf` helper, `ts(ms)` helper producing `HH:MM:SS.mmm`, grid layout with chevron expand, click calls `selectRegionFromRow(useStore, { regionName, envelopeKey })`.

**Step 6 — `Firehose`.** See plan's Step 6 code. Key bits: `matcher(filter)` supports empty / regex / substring with `valid` flag; pause snapshot via `snapshotRef`; `rows = envs.slice(-MAX_ROWS).filter(match)`; auto-scroll near-bottom.

**Step 7 — Wire into `Dock.tsx`.** Replace `FirehosePlaceholder` with `<Firehose />`. Add `useFirehoseRate()` hook (1-Hz interval sampling `envelopesReceivedTotal` delta). Pass `firehoseRate={firehoseRate}` to `<DockTabStrip>`.

**Step 8 — verify tests + typecheck.**

**Step 9 — commit** per HEREDOC below.

---

## Drifts you MUST correct

### Drift A — topicColors.ts colors: preserve v1, add new prefixes only

Spec §5.3 line 148: *"Colors reuse existing v1 `topicColors.ts` where overlap exists; v3 adds the missing prefixes."*

**Current `PREFIXES` (keep unchanged):**
```typescript
const PREFIXES: Array<[string, string]> = [
  ['hive/cognitive/',     '#e8e8e8'],
  ['hive/sensory/',       '#99ee66'],
  ['hive/motor/',         '#ee9966'],
  ['hive/metacognition/', '#bb66ff'],
  ['hive/system/',        '#888888'],    // keep generic system bucket
  ['hive/habit/',         '#ffcc66'],
  ['hive/attention/',     '#66ccff'],
  ['hive/modulator/',     '#ff66bb'],
  ['hive/rhythm/',        '#66cccc'],
];
```

**Add three new entries** (before `hive/system/` so longest-match-wins is natural for this array's first-match-wins scan):

```typescript
['hive/self/',          '#d4b3ff'],   // new — spec §5.3
['hive/interoception/', '#ffc4d8'],   // new — spec §5.3
['hive/broadcast/',     '#d0d0d0'],   // new — spec §5.3
```

**Do NOT subdivide `hive/system/`** into heartbeat/region_stats/metrics/sleep/spawn/codechange at the `topicColor` level. The subdivisions only matter for `kindTag` (Firehose badge LABEL); `topicColor` feeds scene sparks and should stay visually coherent with v1 — one color per system branch.

Rationale: spec §5.3 says "reuse existing where overlap exists" and "v3 adds the missing prefixes". The missing prefixes are `self`, `interoception`, `broadcast`. System subdivisions are already covered by the generic `hive/system/` entry in v1 for scene purposes; `kindTag` gives them distinct badge labels, but the scene color stays consistent.

**Update `topicColor` + `COLOR_CACHE`** mechanically — `COLOR_CACHE` is built from `PREFIXES.map(([, hex]) => hex)`, so adding entries to `PREFIXES` grows the cache automatically.

**Extend the existing `topicColor` test's parametrized table** to include the three new prefixes:
```typescript
['hive/self/identity',           '#d4b3ff'],
['hive/interoception/felt_state','#ffc4d8'],
['hive/broadcast/shutdown',      '#d0d0d0'],
```

Note `kindTag` returns **different** labels per spec §5.3 (e.g. `cog`, `sns`), but topicColors `topicColor` keeps v1 colors. The two are decoupled.

### Drift B — `JsonTree` value type

`JsonTree` takes `value: JsonValue` where `JsonValue = string | number | boolean | null | JsonArray | JsonObject`. `env.envelope` is `Record<string, unknown>`. Plan's Step 5 FirehoseRow code passes `env.envelope` directly:

```tsx
<JsonTree value={env.envelope} />
```

This will fail TypeScript typecheck because `Record<string, unknown>` is not assignable to `JsonValue`. Use the same cast pattern that STM.tsx uses (decisions entry 89 equivalent):

```tsx
<JsonTree value={env.envelope as unknown as JsonValue} />
```

Import `JsonValue`:
```tsx
import { JsonTree, type JsonValue } from '../inspector/sections/JsonTree';
```

### Drift C — Envelope shape for previewOf

Plan's Step 5 `previewOf` reads `env.payload` but actually `env` here is the inner `envelope: Record<string, unknown>` from the `Envelope` type (the OUTER wrapper envelope from store.ts). The plan's code already handles this correctly:

```typescript
function previewOf(env: Record<string, unknown>): string {
  const payload = (env as { payload?: { content_type?: string; data?: unknown } }).payload;
  ...
}
```

And the caller is `previewOf(env.envelope)`, where `env` is an `Envelope` from the store and `env.envelope` is the inner MQTT payload record. This is correct; just noting the nested naming. Preserve the plan's code.

### Drift D — pause snapshot timing

The plan's Step 6 pause implementation:

```typescript
const snapshotRef = useRef<typeof liveEnvs | null>(null);
useEffect(() => {
  if (paused && snapshotRef.current == null) snapshotRef.current = liveEnvs;
  if (!paused) snapshotRef.current = null;
}, [paused, liveEnvs]);
const envs = paused && snapshotRef.current ? snapshotRef.current : liveEnvs;
```

There's a subtle timing bug here: on the first render where `paused` just flipped true, `snapshotRef.current` is still null at the point `const envs = ...` runs (the `useEffect` hasn't fired yet). So the first paused frame will render with the LIVE envs, then snap to the snapshot only after the effect fires.

**Fix: set the snapshot inline during render when transitioning into paused state:**

```typescript
if (paused && snapshotRef.current == null) {
  snapshotRef.current = liveEnvs;
}
if (!paused && snapshotRef.current != null) {
  snapshotRef.current = null;
}
const envs = paused ? (snapshotRef.current ?? liveEnvs) : liveEnvs;
```

This captures on the same render as the `paused` flip, eliminating the one-frame lag. Setting a ref during render is safe (it doesn't trigger a re-render; React guarantees the render is idempotent since this is an effect-free computation).

Alternative: wrap the snapshot-in-ref in `useMemo([paused])` — but the inline-check approach is simpler and matches the pause-should-be-immediate spec intent.

The plan's Step 3 test `'pause snapshots the ring'` exercises this: after `useStore.setState({ dockPaused: true })` + `rerender`, pushing more envelopes should NOT increase the row count. With the plan's deferred-effect approach, the test might pass anyway because `rerender` triggers a second render after the effect fires. But the fix makes the behavior immediate.

### Drift E — Dock.tsx integration shape

Plan Step 7's `useFirehoseRate()` hook is local to Dock.tsx. That's fine; place it in the same file. Wire:

```tsx
// In Dock(), after useDockPersistence():
const firehoseRate = useFirehoseRate();

// In the JSX:
<DockTabStrip
  firehoseRate={firehoseRate}
  topicCount={0}                                          // Task 6 wires
  metacogBadge={{ count: 0, severity: 'quiet' }}          // Task 7 wires
/>

// Replace FirehosePlaceholder:
{!collapsed && (
  <div className="flex-1 overflow-hidden">
    {tab === 'firehose' && <Firehose />}
    {tab === 'topics' && <TopicsPlaceholder />}
    {tab === 'metacog' && <MetacogPlaceholder />}
  </div>
)}
```

Delete `FirehosePlaceholder` since we're replacing it with the real component. Keep Topics + Metacog placeholders — Tasks 6 + 7 own those.

---

## Existing-contract surface

**`observatory/web-src/src/store.ts`:**
- `Envelope` type: `{ observed_at: number; topic: string; envelope: Record<string, unknown>; source_region: string | null; destinations: string[] }`.
- `envelopesReceivedTotal: number` (monotonic counter, decisions entry 82).
- `firehoseFilter: string`, `setFirehoseFilter`, `dockPaused: boolean`, `setDockPaused`, `expandedRowIds: Set<string>`, `toggleRowExpand(id)`.
- `selectedRegion: string | null`, `select(name)`, `setPendingEnvelopeKey(key)`.

**`observatory/web-src/src/inspector/sections/JsonTree.tsx`:**
- `export type JsonValue = string | number | boolean | null | JsonArray | JsonObject;`
- `export function JsonTree({ value, depth = 0 })`.

**`observatory/web-src/src/dock/selectRegionFromRow.ts`** (Task 4):
- `selectRegionFromRow(store, { regionName, envelopeKey }): void`.

**`observatory/web-src/src/dock/Dock.tsx`** (Task 4): currently imports `DockTabStrip` + `useDockPersistence` + three placeholders. Passes zero/quiet values to DockTabStrip. You update this to wire the real `firehoseRate` + the real `<Firehose />` component.

## Gotchas

- **Vitest `globals: false`:** import `describe, it, expect, afterEach` from `'vitest'`.
- **`fireEvent.change` with debounce:** Firehose tests use `setTimeout(r, 200)` after the `fireEvent` to let the 150 ms debounce fire. Don't tighten below 180.
- **`key` prop on mapped rows:** use `${e.observed_at}|${e.topic}|${e.source_region ?? ''}` — stable across re-renders.
- **Regex compile failure:** `new RegExp(pattern, flags)` throws `SyntaxError`; the plan's `matcher` catches with `try/catch`, returning `{ fn: () => true, valid: false }` so the UI shows red border but rows aren't filtered out.
- **Testing-library `fireEvent.change` vs `userEvent`:** stay with `fireEvent.change(input, { target: { value: '...' } })` to match the existing test file idiom (Messages.test.tsx).
- **`useStore.getState()` inside intervals:** see decisions entry 82. Use this pattern for `useFirehoseRate`; NOT `useStore((s) => s.envelopesReceivedTotal)` inside the hook body (would cause the interval itself to tear down + recreate on every change).
- **ISO timestamp slicing:** `new Date(ms).toISOString().slice(11, 23)` yields `HH:MM:SS.mmm`. Works for both ms-scale and second-scale `observed_at` because the Python side emits `time.monotonic() * 1000` (ms). Verify by pushing a test envelope with `observed_at: 1234567.89` and checking the rendered row.
- **`@react-three/drei` / three.js unchanged.** Firehose is a DOM component; no scene-graph modifications.

## Verification gates (all must pass before commit)

```
cd observatory/web-src && npx vitest run && npx tsc -b
cd ../.. && .venv/Scripts/python.exe -m ruff check observatory/
```

Expected: **~131 frontend tests passing** (was 113 → add 18 kindTag + 3 topicColor + 4 Firehose = +25; margin for minor delta = 130–133). tsc clean. Ruff clean.

## Hard rules

- Do NOT change existing `topicColor` hex values — spec says "reuse existing".
- Do NOT subdivide `hive/system/` at the color level. Only `kindTag` subdivides.
- Do NOT touch `region_template/`, `glia/`, `regions/`, `bus/`, `shared/`.
- Do NOT push.
- TDD: tests first, red, then green.
- If a spec-vs-plan conflict surfaces beyond A–E above, stop with `NEEDS_CONTEXT`.

## Commit HEREDOC

```bash
git add observatory/web-src/src/dock/ observatory/web-src/src/scene/topicColors.ts observatory/web-src/src/scene/topicColors.test.ts
git commit -m "$(cat <<'EOF'
observatory: firehose tab + topicColors kindTag (v3 task 5)

Firehose renders the envelope ring with timestamp, source, topic, kind
badge, preview; substring + /regex/i filter with 150 ms debounce; pause
snapshots the ring at pause time and re-syncs on resume. Rows use the
shared selectRegionFromRow helper for click-through. Auto-scroll to
newest when user is within 40 px of bottom. Max rendered rows capped
at 1000. kindTag extends topicColors with all v3 prefixes; topicColor
scene palette preserves v1 hex values and adds three new prefix colors
for self / interoception / broadcast (spec §5.3 "reuse existing + add
missing"). Pause snapshot captured inline during render to eliminate
the one-frame lag the plan's useEffect-only path had.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Report format

1. Status / SHA / files touched
2. Test delta (before/after)
3. Drift notes: what you did with Drifts A–E, any new drift
4. Concerns
