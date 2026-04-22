# Observatory v3 — Task 9 implementer prompt

One task, end-to-end. `superpowers:test-driven-development`. Report status + SHA.

**Working directory:** `C:\repos\hive`. **Node:** `cd observatory/web-src && npx vitest run && npx tsc -b`.

---

## Task

Build HUD tiles: `<SystemMetrics />` (retained hive/system/metrics/*) + `<SelfState />` (4-tab replacement for SelfPanel). Extend store with a raw `retained: Record<string, unknown>` map. Delete `SelfPanel.tsx`.

### Authoritative references

- **Spec §10** (lines 294–331): SystemMetrics tile + SelfState tile.
- **Spec §3** (lines 43–61): topic surface confirming hive/system/metrics/{compute,tokens,region_health} are retained.
- **Plan Task 9:** `observatory/docs/plans/2026-04-22-observatory-v3-plan.md` lines 2408–2741.

---

## Plan Task 9 — verbatim (with drifts below)

### Files
- Create: `observatory/web-src/src/hud/SystemMetrics.tsx`
- Create: `observatory/web-src/src/hud/SystemMetrics.test.tsx`
- Create: `observatory/web-src/src/hud/SelfState.tsx`
- Create: `observatory/web-src/src/hud/SelfState.test.tsx`
- Delete: `observatory/web-src/src/hud/SelfPanel.tsx`
- Modify: `observatory/web-src/src/hud/Hud.tsx`
- Modify: `observatory/web-src/src/store.ts`
- Modify: `observatory/web-src/src/store.test.ts`

### Contract

**`retained: Record<string, unknown>`:** raw retained-payload map keyed by topic. `applySnapshot` unwraps `retained[topic].payload` into the map; `applyRetained(topic, payload)` sets `retained[topic] = payload`. Used by SystemMetrics to read the three `hive/system/metrics/*` payloads directly.

**SystemMetrics reads:**
- `hive/system/metrics/compute` → `{total_cpu_pct, total_mem_mb, per_region}` — compute aggregate.
- `hive/system/metrics/tokens` → `{total_input_tokens, total_output_tokens, per_region}`.
- `hive/system/metrics/region_health` → `{summary, regions_up, regions_degraded, regions_down, per_region: {<name>: {status, consecutive_misses, uptime_s}}}`.

See **Drift A** below — the plan's test fixture has the wrong `per_region` schema.

**Layout:** SelfState > SystemMetrics > Modulators > Counters top-to-bottom (spec §10.1 line 314 puts Metrics "below Self tile and above v1 Counters").

### Steps (see plan 2428–2740)

See plan for the 10-step TDD walk (tests → store → SystemMetrics impl → SelfState impl → Hud restructure → delete SelfPanel).

---

## Drifts you MUST correct

### Drift A — `region_health.per_region` schema mismatch

**Plan's test fixture** (line 2504-2508):
```typescript
'hive/system/metrics/region_health': {
  per_region: { pfc: 'alive', amygdala: 'stale', acc: 'dead' },
}
```

**Actual Hive schema** (`glia/metrics.py:221-235`):
```python
per_region[name] = {
    "status": rec.last_status,         # e.g. "wake", "sleep", "dead" (LWT)
    "consecutive_misses": rec.consecutive_misses,
    "uptime_s": rec.uptime_s,
}
```

The plan assumes each `per_region[name]` value is a bare status string. Reality: each is an OBJECT `{status, consecutive_misses, uptime_s}`. And `status` is a raw phase string (`"wake"`, `"sleep"`, `"bootstrap"`, `"shutdown"`) plus `"dead"` on LWT, NOT the `alive|stale|dead|unknown` vocabulary spec §10.1 defines.

**Fix:**

1. **Derive color from per-region entry:**

```typescript
type HealthEntry = { status?: string; consecutive_misses?: number; uptime_s?: number };
type HealthPayload = {
  summary?: string;
  regions_up?: number;
  regions_degraded?: number;
  regions_down?: number;
  per_region?: Record<string, HealthEntry>;
};

type Liveness = 'alive' | 'stale' | 'dead' | 'unknown';

function livenessOf(entry: HealthEntry | undefined): Liveness {
  if (!entry) return 'unknown';
  if (entry.status === 'dead') return 'dead';
  if ((entry.consecutive_misses ?? 0) > 0) return 'stale';
  return 'alive';
}

const HEALTH_COLOR: Record<Liveness, string> = {
  alive: '#85d19a',
  stale: '#d6b85a',
  dead: '#d66a6a',
  unknown: 'rgba(136,140,152,.35)',
};
```

2. **Rendering loop:**

```tsx
const regions = Object.entries(health?.per_region ?? {});
// ...
{regions.map(([name, entry]) => {
  const live = livenessOf(entry);
  return (
    <div
      key={name}
      data-testid="health-cell"
      title={`${name} · ${live}`}
      style={{
        width: 10,
        height: 10,
        background: HEALTH_COLOR[live],
      }}
    />
  );
})}
```

3. **Update test fixture** to use the real schema:

```typescript
it('renders heatmap cells from region_health', () => {
  useStore.setState({ retained: { 'hive/system/metrics/region_health': {
    per_region: {
      pfc: { status: 'wake', consecutive_misses: 0, uptime_s: 100 },      // alive
      amygdala: { status: 'wake', consecutive_misses: 2, uptime_s: 50 },  // stale
      acc: { status: 'dead', consecutive_misses: 0, uptime_s: 0 },        // dead
    },
  } } });
  const { container } = render(<SystemMetrics />);
  expect(container.querySelectorAll('[data-testid="health-cell"]').length).toBe(3);
});
```

Log this drift in `decisions.md` — flag for plan author that the plan's `per_region` test fixture contradicts the actual glia/metrics.py schema.

### Drift B — Hud.tsx restructure preserves HUD behavior

Plan Step 8 replaces the current Hud.tsx wholesale:

```tsx
// Plan's proposed structure:
<div className="fixed top-3 left-3 flex flex-col gap-2 z-20">
  <SelfState />
  <SystemMetrics />
  <Modulators />
  <Counters />
</div>
```

**Current `Hud.tsx`:**
```tsx
<>
  <div className="absolute top-3 left-3 pointer-events-none">
    <SelfPanel />
    <Modulators />
  </div>
  <div className="absolute bottom-3 left-3 pointer-events-none">
    <Counters />
  </div>
</>
```

Key differences:
- Plan moves Counters to top-left (under Modulators). Spec §10.1 line 314 doesn't prescribe Counters placement in v3, only says SystemMetrics is "above the v1 Counters".
- Plan drops `pointer-events-none`. SelfState has clickable tabs; without pointer events, clicks would fail. So the new container **needs** `pointer-events-auto` on interactive descendants or the container must enable pointer events.

**Fix:** stack top-left with pointer-events controlled per-child:

```tsx
<div className="absolute top-3 left-3 flex flex-col gap-2 z-20 pointer-events-none [&>*]:pointer-events-auto">
  <SelfState />
  <SystemMetrics />
  <Modulators />
  <Counters />
</div>
```

The `[&>*]:pointer-events-auto` Tailwind arbitrary variant enables pointer events on direct children (Tailwind 3.3+ supports this syntax). This preserves scene click-through in the gaps between tiles while allowing clicks/hovers inside each tile.

If `[&>*]:pointer-events-auto` doesn't work in the project's Tailwind config, fall back to adding `pointer-events-auto` on each tile's outer div directly. Verify with `grep -n "[&>" observatory/web-src/src/` for existing usage — if none, use the explicit per-child approach.

Verify the existing Counters / Modulators tiles DON'T already set `pointer-events-none` on themselves. If they do, leave them alone and just ensure their containers have pointer-events-auto.

### Drift C — `extractAmbient` 2-arg signature

Plan's Step 2 diff shows:
```typescript
applySnapshot: (s) => set({
  regions: s.regions,
  envelopes: s.recent,
  envelopesReceivedTotal: s.recent.length,
  ambient: extractAmbient(s.retained),
  retained: Object.fromEntries(...),
}),
```

`extractAmbient(s.retained)` is current signature from Task 2. Preserve. The Object.fromEntries unwrap maps each retained entry's `payload` field (the inner MQTT payload) into the flat `retained[topic]` shape.

### Drift D — `applyRetained` — update `retained` map too

Plan's Step 2 comment `// existing ambient update body …` must not be dropped. Current `applyRetained` branches on topic prefix to populate `ambient`. After the existing body, add:

```typescript
set({ retained: { ...get().retained, [topic]: payload } });
```

The `...get().ambient` update in the existing body already calls `set({ ambient })` once; you now need TWO `set(...)` calls — one for ambient, one for retained. Or combine into one `set({ ambient: ..., retained: ... })` for atomicity. Prefer the single-set approach for transactional consistency:

```typescript
applyRetained: (topic, payload) => {
  const ambient = { ...get().ambient, modulators: { ...get().ambient.modulators }, self: { ...get().ambient.self } };
  const value = (payload as { value?: unknown }).value;
  if (topic.startsWith('hive/modulator/')) {
    const name = topic.slice('hive/modulator/'.length);
    if (isModulatorName(name)) {
      ambient.modulators[name] = Number(value ?? 0);
    }
  } else if (topic === 'hive/self/identity') ambient.self.identity = String(value ?? '');
  else if (topic === 'hive/self/values') ambient.self.values = value;
  else if (topic === 'hive/self/personality') ambient.self.personality = value;
  else if (topic === 'hive/self/autobiographical_index') ambient.self.autobiographical_index = value;
  else if (topic === 'hive/interoception/felt_state') ambient.self.felt_state = String(value ?? '');
  set({
    ambient,
    retained: { ...get().retained, [topic]: payload },
  });
},
```

Now EVERY retained topic — modulator, self, metrics, whatever — ends up in the `retained` map. The `return` early-exit for unknown modulator names is removed so those topics still land in the raw retained map even if `ambient.modulators` rejects them.

Actually wait — the current code has `if (!isModulatorName(name)) return;` which early-exits. After Drift D, we DON'T want to early-exit — unknown modulator names should still end up in `retained` even if they can't be classified into `ambient.modulators`. Restructure the branch:

```typescript
if (topic.startsWith('hive/modulator/')) {
  const name = topic.slice('hive/modulator/'.length);
  if (isModulatorName(name)) {
    ambient.modulators[name] = Number(value ?? 0);
  }
  // still fall through to set the retained map below
}
```

(Tests should still pass — existing modulator tests check `ambient.modulators` doesn't contain unknown names, not that unknown names are absent from everywhere.)

### Drift E — SelfState empty-state per-tab

Plan's Step 7 `renderBody` returns the empty state when `v === undefined || v === '' || v === null`. Preserve. Test `it('empty state per tab', ...)` asserts the copy matches `/No data yet — mPFC hasn't published\./i`.

---

## Existing-contract surface

**`observatory/web-src/src/store.ts`** (post Task 2):
- `Ambient.self: { identity?, values?, personality?, autobiographical_index?, felt_state? }`.
- `extractAmbient(retained)` — already handles the four self topics.
- `applySnapshot({regions, retained, recent, server_version})` — populates regions, envelopes, envelopesReceivedTotal, ambient.
- `applyRetained(topic, payload)` — updates ambient.modulators + self fields.

**Spec §10.1 lines 306-311** (Health color vocabulary):
- `alive` → `#85d19a`
- `stale` → `#d6b85a` (heartbeat missed)
- `dead` → `#d66a6a`
- `unknown` → `rgba(136,140,152,.35)`

**Spec §10.2 lines 317-331** (SelfState tabs):
- Identity / Values / Personality / Index (autobiographical_index)
- Missing topic → tab shows "No data yet — mPFC hasn't published."

**`observatory/web-src/src/hud/SelfPanel.tsx`** — currently renders `identity` + `felt_state` (trimmed in Task 2 Drift C). Delete this file in Step 8.

**`observatory/web-src/src/hud/Modulators.tsx`** + **`Counters.tsx`** — existing tiles; preserve. Their container in Hud.tsx moves under the new top-left stack.

## Gotchas

- **Vitest `globals: false`** — import `describe/it/expect` from `'vitest'`.
- **`useStore.setState({retained: ...})`** in tests — partial state update; other fields preserved. Reset in `afterEach`.
- **`Object.fromEntries(Object.entries(...).map(...))`** pattern is standard for unwrapping envelope payload on applySnapshot — preserve the `?? null` fallback so a malformed retained entry becomes null, not undefined.
- **Tailwind arbitrary variants** `[&>*]:pointer-events-auto` — verify Tailwind version supports it (3.3+). If not, apply `pointer-events-auto` to each tile.
- **`HEALTH_COLOR[live]` — live is `Liveness` (union of 4 strings), so `Record<Liveness, string>` is exhaustively type-safe.
- **`SelfState` `v === ''` check** — for `identity` (string), empty-string is a "no data" signal; for `values`/`personality`/`autobiographical_index` (unknown), the string check never fires.
- **`SelfState` test** uses `afterEach cleanup + resets ambient to empty`. Self tabs read `ambient.self.*` directly via selector.
- **Autobio entries** — array of `{ts, headline}`; slice at 20, show "N more…" footer if longer.

## Verification gates

```
cd observatory/web-src && npx vitest run && npx tsc -b
cd ../.. && .venv/Scripts/python.exe -m ruff check observatory/
```

Expected: **156 → 165 frontend tests** (+1 store retained + 4 SystemMetrics + 3 SelfState + 1 SelfPanel delete effect). tsc clean, ruff clean.

Actually, SelfPanel deletion won't change test count (SelfPanel had no tests). So **+8 = 164 tests**.

## Hard rules

- Do NOT touch region_template/, glia/, regions/, bus/, shared/.
- Do NOT break existing Modulators/Counters/Hud behavior.
- Do NOT push.
- TDD: tests first, red, then green.
- If spec/plan conflict surfaces beyond A-E, stop with NEEDS_CONTEXT.

## Commit HEREDOC

```bash
git rm observatory/web-src/src/hud/SelfPanel.tsx
git add observatory/web-src/src/hud/ observatory/web-src/src/store.ts observatory/web-src/src/store.test.ts observatory/memory/decisions.md
git commit -m "$(cat <<'EOF'
observatory: HUD — SystemMetrics tile + SelfState replacement (v3 task 9)

Adds a raw retained: Record<string, unknown> map to the store (populated
by applySnapshot's payload-unwrap and applyRetained every call). New
SystemMetrics tile reads retained hive/system/metrics/{compute, tokens,
region_health} — CPU/Mem + token totals + 14-cell liveness heatmap
(alive/stale/dead/unknown) derived from per_region.status +
consecutive_misses. New SelfState tile replaces SelfPanel with four
tabs (Identity / Values / Personality / Autobio) reading the four
hive/self/* retained payloads from ambient.self. Hud.tsx stacks
Self > Metrics > Modulators > Counters top-left with per-child
pointer-events-auto so scene click-through stays intact between tiles.
SelfPanel.tsx deleted.

per_region schema aligned to glia/metrics.py::build_region_health_payload
actual shape ({status, consecutive_misses, uptime_s} per region, not
a bare status string as the plan's test fixture assumed); liveness
derived in observatory since status carries the LifecyclePhase raw
value + "dead" on LWT.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

## Report format

1. Status / SHA / files touched
2. Test delta (before/after; 156 → 164 expected)
3. Drift handling (A/B/C/D/E)
4. Other drift
5. Concerns
