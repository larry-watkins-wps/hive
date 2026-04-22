# Observatory v3 — Task 2 implementer prompt

You are an implementer subagent. You own **exactly one task** end-to-end: implementation, tests, verification, commit. When done, report `DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED` with the commit SHA.

Use `superpowers:test-driven-development`. Red → green → refactor.

**Working directory:** `C:\repos\hive`.

**Node invocation:** `cd observatory/web-src && npx vitest ...`. `npx tsc -b` for typecheck.

---

## Task

Add dock state (six fields + seven actions) + `pendingEnvelopeKey` to the zustand store, and fix the broken self-state handling. The store currently references `developmental_stage` and `age` — both dead since commit `155854d` which dropped those retained topics from Hive. Replace them with the four current `hive/self/*` topics (`identity`, `values`, `personality`, `autobiographical_index`) per spec §10.2 and §12.

### Authoritative references

1. **Spec §12 — Data model (zustand store additions)**: `observatory/docs/specs/2026-04-22-observatory-v3-design.md` lines 343–371.
2. **Spec §10.2 — Self-State tile**: lines 317–331 (for the self-field contract).
3. **Plan Task 2**: `observatory/docs/plans/2026-04-22-observatory-v3-plan.md` lines 306–567.
4. **Plan drift note #2** (`observatory/docs/plans/2026-04-22-observatory-v3-plan.md:22`): `extractAmbient` currently pulls `developmental_stage`/`age`, but those topics were dropped in commit `155854d`. Remove those paths; add `values`/`personality`/`autobiographical_index`.

---

## Plan Task 2 — verbatim (with fidelity notes)

```
## Task 2 — Store: dock state + `pendingEnvelopeKey` + self-state retained handling

**Files:**
- Modify: `observatory/web-src/src/store.ts`
- Modify: `observatory/web-src/src/store.test.ts`

**Persistence:** dock-persistence hook in Task 4 reads/writes localStorage. Store is persistence-agnostic.

**No changes to the `envelopes` ring or `envelopesReceivedTotal` counter.**
```

**Step 1 — failing store tests (append to store.test.ts):**

```typescript
describe('dock state', () => {
  it('has sensible defaults', () => {
    const s = createStore().getState();
    expect(s.dockTab).toBe('firehose');
    expect(s.dockCollapsed).toBe(false);
    expect(s.dockHeight).toBe(220);
    expect(s.dockPaused).toBe(false);
    expect(s.firehoseFilter).toBe('');
    expect(s.expandedRowIds.size).toBe(0);
    expect(s.pendingEnvelopeKey).toBeNull();
  });

  it('setDockTab switches tab and clears expandedRowIds', () => {
    const store = createStore();
    store.getState().toggleRowExpand('row-1');
    expect(store.getState().expandedRowIds.has('row-1')).toBe(true);
    store.getState().setDockTab('topics');
    expect(store.getState().dockTab).toBe('topics');
    expect(store.getState().expandedRowIds.size).toBe(0);
  });

  it('setDockHeight clamps to [120, 520]', () => {
    const store = createStore();
    store.getState().setDockHeight(50);
    expect(store.getState().dockHeight).toBe(120);
    store.getState().setDockHeight(1000);
    expect(store.getState().dockHeight).toBe(520);
    store.getState().setDockHeight(300);
    expect(store.getState().dockHeight).toBe(300);
  });

  it('toggleRowExpand toggles set membership', () => {
    const store = createStore();
    store.getState().toggleRowExpand('a');
    expect(store.getState().expandedRowIds.has('a')).toBe(true);
    store.getState().toggleRowExpand('a');
    expect(store.getState().expandedRowIds.has('a')).toBe(false);
  });

  it('setPendingEnvelopeKey sets and clears', () => {
    const store = createStore();
    store.getState().setPendingEnvelopeKey('123|hive/a');
    expect(store.getState().pendingEnvelopeKey).toBe('123|hive/a');
    store.getState().setPendingEnvelopeKey(null);
    expect(store.getState().pendingEnvelopeKey).toBeNull();
  });
});

describe('self-state retained handling', () => {
  it('applySnapshot picks up identity / values / personality / autobiographical_index', () => {
    const store = createStore();
    store.getState().applySnapshot({
      regions: {},
      retained: {
        'hive/self/identity': { payload: { value: 'I am Hive.' } },
        'hive/self/values': { payload: { value: ['curiosity', 'care'] } },
        'hive/self/personality': { payload: { value: { warmth: 0.8 } } },
        'hive/self/autobiographical_index': { payload: { value: [{ ts: '2026-04-22', headline: 'first wake' }] } },
      },
      recent: [],
      server_version: 'test',
    });
    const self = store.getState().ambient.self;
    expect(self.identity).toBe('I am Hive.');
    expect(self.values).toEqual(['curiosity', 'care']);
    expect(self.personality).toEqual({ warmth: 0.8 });
    expect(self.autobiographical_index).toEqual([{ ts: '2026-04-22', headline: 'first wake' }]);
  });

  it('applyRetained handles the four self topics live', () => {
    const store = createStore();
    store.getState().applyRetained('hive/self/values', { value: ['a', 'b'] });
    expect(store.getState().ambient.self.values).toEqual(['a', 'b']);
  });
});
```

**Step 2 — Run `npx vitest run store.test.ts`. Expected: 7 new tests FAIL.**

**Step 3 — Update `Ambient`:**

```typescript
export type Ambient = {
  modulators: Partial<Record<'cortisol' | 'dopamine' | 'serotonin' | 'norepinephrine' | 'oxytocin' | 'acetylcholine', number>>;
  self: {
    identity?: string;
    values?: unknown;
    personality?: unknown;
    autobiographical_index?: unknown;
    felt_state?: string;
  };
};
```

Remove `developmental_stage` and `age`.

**Step 4 — Extend `State` with dock fields + actions** (seven new fields, seven new action slots):

```typescript
dockTab: 'firehose' | 'topics' | 'metacog';
dockCollapsed: boolean;
dockHeight: number;              // clamped [120, 520]
dockPaused: boolean;
firehoseFilter: string;
expandedRowIds: Set<string>;
pendingEnvelopeKey: string | null;

setDockTab: (tab: 'firehose' | 'topics' | 'metacog') => void;
setDockCollapsed: (b: boolean) => void;
setDockHeight: (n: number) => void;
setDockPaused: (b: boolean) => void;
setFirehoseFilter: (s: string) => void;
toggleRowExpand: (id: string) => void;
setPendingEnvelopeKey: (key: string | null) => void;
```

**Step 5 — Update `extractAmbient` + `applyRetained`** for the four self topics:

```typescript
function extractAmbient(retained: Snapshot['retained']): Ambient {
  const ambient: Ambient = { modulators: {}, self: {} };
  for (const [topic, env] of Object.entries(retained)) {
    const payload = env.payload ?? {};
    const value = (payload as { value?: unknown }).value;
    if (topic.startsWith('hive/modulator/')) {
      const name = topic.slice('hive/modulator/'.length);
      if (!isModulatorName(name)) continue;
      const v = Number(value ?? NaN);
      if (!Number.isNaN(v)) ambient.modulators[name] = v;
    } else if (topic === 'hive/self/identity') ambient.self.identity = String(value ?? '');
    else if (topic === 'hive/self/values') ambient.self.values = value;
    else if (topic === 'hive/self/personality') ambient.self.personality = value;
    else if (topic === 'hive/self/autobiographical_index') ambient.self.autobiographical_index = value;
    else if (topic === 'hive/interoception/felt_state') ambient.self.felt_state = String(value ?? '');
  }
  return ambient;
}
```

Update `applyRetained` similarly — including the live paths for the three new self topics + identity.

**Step 6 — Add dock defaults + action implementations in the factory:**

```typescript
dockTab: 'firehose',
dockCollapsed: false,
dockHeight: 220,
dockPaused: false,
firehoseFilter: '',
expandedRowIds: new Set<string>(),
pendingEnvelopeKey: null,

setDockTab: (tab) => set({ dockTab: tab, expandedRowIds: new Set() }),
setDockCollapsed: (b) => set({ dockCollapsed: b }),
setDockHeight: (n) => set({ dockHeight: Math.max(120, Math.min(520, n)) }),
setDockPaused: (b) => set({ dockPaused: b }),
setFirehoseFilter: (s) => set({ firehoseFilter: s }),
toggleRowExpand: (id) => {
  const next = new Set(get().expandedRowIds);
  if (next.has(id)) next.delete(id); else next.add(id);
  set({ expandedRowIds: next });
},
setPendingEnvelopeKey: (key) => set({ pendingEnvelopeKey: key }),
```

**Step 7 — `SelfPanel.tsx` follow-up.** Plan offers two options; **I'm recommending a third (strictly cleaner) option**:

- **Option A (plan):** `@ts-expect-error` on lines 10-11.
- **Option B (plan):** delete `SelfPanel.tsx` + remove import from `Hud.tsx` now.
- **Option C (my recommendation):** keep `SelfPanel.tsx`, but **delete its two dead JSX fragments** (lines 10-11: the `developmental_stage` and `age` badges). Leave identity + felt_state rendering. Task 9 still owns full replacement with `SelfState.tsx`.

Rationale for C: (a) no `@ts-expect-error` suppressions left in the codebase, (b) no temporary HUD regression between Task 2 and Task 9, (c) the file is going to be deleted in Task 9 anyway, and (d) the two dead badges were already showing `"unknown"`/`"—"` to users — removing them actually cleans up the UI slightly.

**Take option C unless you find a reason it won't work.** Document the call in `observatory/memory/decisions.md` (continuing the existing numbering — check the last entry number first).

If you take option A, the `@ts-expect-error` comments must reference Task 9 by name: `// @ts-expect-error deleted field; scheduled for deletion in Task 9`.

**Step 8 — Run tests + typecheck + ruff:**

```
cd observatory/web-src && npx vitest run && npx tsc -b
```

Expected: all green. Full frontend suite should be `84 + 7 = 91` passing tests.

**Step 9 — Commit** (one commit for the whole task):

```bash
git add observatory/web-src/src/store.ts observatory/web-src/src/store.test.ts observatory/web-src/src/hud/SelfPanel.tsx observatory/memory/decisions.md
git commit -m "$(cat <<'EOF'
observatory: store — dock + pendingEnvelopeKey + self-state topics (v3 task 2)

Adds six dock fields (dockTab/Collapsed/Height/Paused + firehoseFilter
+ expandedRowIds) + pendingEnvelopeKey + actions. Replaces dead
developmental_stage/age handling (topics dropped in 155854d) with
values/personality/autobiographical_index off the four hive/self/*
topics. Clamps dockHeight to [120, 520]. Clears expandedRowIds on
tab switch.

SelfPanel.tsx trimmed to identity + felt_state only; Task 9 replaces
it with SelfState.tsx.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Existing-contract surface (already in the codebase)

**`observatory/web-src/src/store.ts`** (current full file read):
- `RegionStats`, `RegionMeta`, `Envelope` types unchanged by this task.
- Current `Ambient` has `self: { identity?; developmental_stage?; age?; felt_state? }` — you remove `developmental_stage` + `age`, add `values` + `personality` + `autobiographical_index`.
- Current `State` has `applySnapshot`, `applyRegionDelta`, `applyAdjacency`, `applyRetained`, `pushEnvelope`, `select`, `cycle`, plus backing data (`regions`, `envelopes`, `envelopesReceivedTotal`, `adjacency`, `ambient`, `selectedRegion`).
- `RING_CAP = 5000`. `pushEnvelope` caps at RING_CAP while monotonically bumping `envelopesReceivedTotal`.
- `MODULATOR_NAMES` + `isModulatorName` exported; don't duplicate.
- `useStore` at bottom of file is module-level (`createStore()` called once).
- Factory uses `(set, get) => ({ ... })` pattern.

**`observatory/web-src/src/store.test.ts`** patterns:
- `describe('X', () => { it('...', () => { ... }) })` blocks.
- `createStore()` factory called per-test (not `useStore`) — isolation.
- `getState()` to read/write.
- Existing tests: 11 including selection + cycle. After this task: 18 (11 + 5 dock + 2 self-state).

**`observatory/web-src/src/hud/SelfPanel.tsx`** (current contents):

```tsx
import { useStore } from '../store';

export function SelfPanel() {
  const self = useStore((s) => s.ambient.self);
  return (
    <div className="p-3 bg-hive-panel/80 backdrop-blur rounded-md max-w-xs">
      <div className="text-[10px] tracking-widest opacity-60 uppercase">Self</div>
      <div className="text-sm leading-snug line-clamp-2">{self.identity ?? '—'}</div>
      <div className="flex gap-2 mt-1 text-xs">
        <span className="px-1.5 py-0.5 bg-white/10 rounded">{self.developmental_stage ?? 'unknown'}</span>
        <span className="px-1.5 py-0.5 bg-white/10 rounded">age {self.age ?? '—'}</span>
        <span className="px-1.5 py-0.5 bg-white/10 rounded">{self.felt_state ?? '—'}</span>
      </div>
    </div>
  );
}
```

Option C: delete the `.flex.gap-2.mt-1.text-xs` wrapper div's first two spans (developmental_stage + age). Keep felt_state. The identity line on top is unchanged. Or simplify further: collapse the badges row to just felt_state, or delete the whole row entirely if felt_state rarely surfaces in practice.

**`observatory/web-src/src/hud/Hud.tsx`** currently mounts `<SelfPanel />`, `<Modulators />`, `<Counters />` — do NOT touch this file in Task 2 (Task 9 restructures it).

## Gotchas

- **`vitest.config.ts` has `globals: false`** (per v2 Task 13/14 decisions) — imports like `describe`/`it`/`expect` come from `'vitest'`. The existing test file already imports them; your new blocks slot into the same file.
- **`Set<string>` immutability:** `toggleRowExpand` must construct a new Set via `new Set(get().expandedRowIds)` before mutating, then `set(...)`. Otherwise zustand subscribers will not fire (referential equality). The plan's Step 6 code has this right — do not simplify.
- **`Math.max(120, Math.min(520, n))` clamp order:** the plan writes max-of-min. This is correct for `[120, 520]` clamping (n below 120 → 120; n above 520 → min→520 → max(120,520)=520). Don't flip.
- **`extractAmbient`:** the `const value = (payload as { value?: unknown }).value;` line is a cast, not a type-assertion — `payload` is already typed `Record<string, unknown>` but `.value` extraction benefits from the narrow type.
- **`applyRetained`:** unlike `extractAmbient`, `applyRetained` receives a single `(topic, payload)` — do not forget to update *it* with the new self-topic branches.

## Verification gates (must all pass before commit)

```
cd observatory/web-src && npx vitest run
cd observatory/web-src && npx tsc -b
cd ../.. && .venv/Scripts/python.exe -m ruff check observatory/    # observatory/ has no TS ruff rules but runs clean; keep baseline
```

Expected: **91 frontend tests passing** (was 84), ruff clean.

## Hard rules

- Do NOT touch `region_template/`, `glia/`, `regions/`, `bus/`, `shared/`.
- Do NOT push.
- TDD: tests FIRST, observe red, THEN implement.
- If a spec-vs-plan conflict surfaces that isn't covered above, STOP with `NEEDS_CONTEXT`.

## Report format

1. Status, commit SHA, files touched
2. Test delta (before/after counts)
3. Step 7 option taken (A/B/C) + rationale
4. Any drift from this brief
5. Any concerns
