# Implementer prompt — Observatory v1, Task 13: Sparks (traveling particles on edges)

## Context

You are a fresh implementer subagent executing **Task 13** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–12 shipped with review-fixes. Backend suite: **67 unit + 1 component** passing, ruff clean. Frontend: **8 tests** passing (5 store + 3 ws), `tsc -b` + `vite build` clean. HEAD is `5888544`.

Task 13 introduces the **spark system** — one `InstancedMesh` of up to 2000 particles that travel from source to destination regions whenever envelopes arrive. Topic prefix → color via a pure unit-tested mapper (TDD). This is the first use of `three.js` instanced rendering in the project and the first spark subscribed to the envelope ring.

## Authoritative documents (read first)

- **Plan (Task 13):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 13:` at line 2661 (spans to line 2824). Complete code blocks verbatim.
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Spec (visual lexicon):** `observatory/docs/specs/2026-04-20-observatory-design.md` §4.4 — spark visual semantics (color by topic branch, lifetime, travel).
- **Task 12 cache pattern to replicate:** `observatory/web-src/src/scene/Regions.tsx` lines ~15–17 — `PHASE_COLOR_CACHE` pre-built once at module load. See §1 below.
- **Envelope ring on store:** `observatory/web-src/src/store.ts` — `envelopes: Envelope[]` (5000-cap). `source_region: string | null`, `destinations: string[]`.
- **Node positions:** `observatory/web-src/src/scene/useForceGraph.ts` — returns `React.MutableRefObject<Map<string, ForceNode>>`. `ForceNode` has `x, y, z` mutated in place by d3.
- **Prior decisions log:** `observatory/memory/decisions.md` — entries 57–67 cover Tasks 11–12; entry 66 is the `PHASE_COLOR_CACHE` template.

## Your scope

Execute plan Steps 1–6, in order, with **TDD discipline** on the topic-color mapper:

1. Write `observatory/web-src/src/scene/topicColors.test.ts` (verbatim from plan) — must fail because `topicColors.ts` doesn't exist yet.
2. Implement `observatory/web-src/src/scene/topicColors.ts` (verbatim from plan) — test should now pass.
3. Run `cd observatory/web-src && npm run test` — assert 8 prior + 10 new topicColors tests = 18 pass.
4. Implement `observatory/web-src/src/scene/Sparks.tsx` — **see §1 for the one pre-approved drift fix** (cache Color objects). Rest verbatim.
5. Modify `observatory/web-src/src/scene/Scene.tsx` to include `<Sparks nodesRef={nodes} />` inside the `<Canvas>` after `<Regions>`. Plan Step 5 doesn't show the verbatim file — use your judgement but KEEP the existing `useMemo` memoization from Task 11/12.
6. Commit with plan Step 6 HEREDOC verbatim.

You are NOT doing Task 14 (modulator fog + rhythm pulse). Stop at Task 13.

## Critical concerns & pre-approved guidance

### 1. Drift fix — Cache Color objects per topic branch (PHASE_COLOR_CACHE pattern)

Plan Step 4 line 2761:

```tsx
const color = new Color(topicColor(e.topic));
```

allocates a new `Color` for **every envelope destination** — at 50–100 envelopes/sec × ~1–3 destinations, that's 50–300 `Color` instances/sec, plus matching GC. Task 12 decision entry 67 established the pattern for exactly this case: pre-build a module-level cache once, look up at runtime.

**Pre-approved replacement:** replace the allocation with a lookup into a pre-built module-level `TOPIC_COLOR_CACHE`. Since `topicColor()` returns one of 10 possible strings (9 prefixes + 1 fallback), the cache has 10 entries. Build it in `topicColors.ts` alongside the mapper — both files should live in the same module so the cache and mapper stay in sync:

In `topicColors.ts`, ADD a second export `topicColorObject(topic)` that returns a cached `Color` instance:

```typescript
import { Color } from 'three';

const PREFIXES: Array<[string, string]> = [ /* ... verbatim ... */ ];
const FALLBACK = '#666666';

export function topicColor(topic: string): string {
  for (const [prefix, color] of PREFIXES) {
    if (topic.startsWith(prefix)) return color;
  }
  return FALLBACK;
}

const COLOR_CACHE: Record<string, Color> = Object.fromEntries(
  [...PREFIXES.map(([, hex]) => hex), FALLBACK].map((hex) => [hex, new Color(hex)]),
);

export function topicColorObject(topic: string): Color {
  return COLOR_CACHE[topicColor(topic)];
}
```

Then `Sparks.tsx` imports `topicColorObject` alongside `topicColor` and uses `color: topicColorObject(e.topic)` instead of `new Color(topicColor(e.topic))`.

**Do NOT modify `topicColors.test.ts`** — the existing 10 test cases still pass because `topicColor` (string version) is unchanged. Optionally add ONE new test asserting `topicColorObject` returns the same Color instance for the same topic (identity check proves caching works):

```typescript
import { topicColor, topicColorObject } from './topicColors';

it('topicColorObject returns cached Color instances', () => {
  const a = topicColorObject('hive/cognitive/a');
  const b = topicColorObject('hive/cognitive/b');
  expect(a).toBe(b); // same instance because both map to '#e8e8e8'
  expect(a.getHexString()).toBe('e8e8e8');
});
```

Log both changes in `decisions.md` as a Task 13 review-fix-style drift (same pattern as Task 12 entry 67).

### 2. Verify `MeshBasicMaterial` handles `setColorAt` on an `InstancedMesh`

three.js `InstancedMesh.setColorAt(i, color)` lazily allocates `instanceColor` on first call, and `MeshBasicMaterial` auto-uses it when present (three.js ≥0.140). We're on `three@0.163`. No additional material flags needed. The plan's `<meshBasicMaterial />` with no props should work.

If colors don't render correctly during build/typecheck (unlikely, this is runtime), flag it — don't add `vertexColors={true}` preemptively.

### 3. `<instancedMesh args={[undefined as any, undefined as any, MAX_SPARKS]}>`

The `undefined as any` casts are standard R3F for instanced meshes: geometry + material are provided as child elements (`<sphereGeometry>`, `<meshBasicMaterial>`). Don't "fix" the casts — keep them verbatim.

### 4. TypeScript strict — `InstancedMesh` type

Plan uses `useRef<InstancedMesh>(null)`. This differs from Task 12's `useRef<any>(null)` pattern — it's tighter. Keep it. This gives type safety on `.setMatrixAt`, `.setColorAt`, `.instanceMatrix`, `.instanceColor`, `.count`. If typecheck fails because of `.instanceColor` nullable (three.js may mark it `InstancedBufferAttribute | null`), the plan's `if (meshRef.current.instanceColor)` guard handles it.

### 5. Envelope-ring subscription semantics

Plan's approach: `useStore.getState()` (non-reactive) + `envs.length - lastLenRef.current` to detect new envelopes + `envs.slice(...)` with a `Math.min(newCount, 100)` cap to avoid emitting 5000 sparks if the tab was backgrounded.

**This is deliberately non-reactive** — `useFrame` already runs 60 Hz, so subscribing reactively would be redundant. Keep the pattern.

Edge case: if `envs.length` shrinks (impossible in practice — ring only grows-and-caps), `lastLenRef` would desync. Not worth guarding against; the ring only shrinks if the store is reset, which doesn't happen in normal flow.

### 6. Ring overflow: `sparks.current.shift()`

`shift()` is O(n). At 2000 sparks with ~50 msg/sec * ~2 destinations = ~100 sparks/sec spawn rate, and 800 ms lifetime = ~80 live sparks typical. Overflow is unlikely. Keep `.shift()` per plan.

### 7. `sparks.current.filter(...)` every frame

The plan rebuilds the sparks array every frame even if nothing expired. At typical ~80 live sparks, that's trivial. Keep verbatim.

### 8. `meshRef.current.count = i`

This tells three.js to only render the first `i` instances. Essential — without it, all 2000 slots would render (stale data or origin). Plan handles it; keep.

### 9. `new Matrix4()` + `new Vector3()` at top of useFrame

Two allocations per frame (not per-spark). Negligible. Plan keeps them local; keep verbatim.

### 10. Scene.tsx edit — keep Task 11/12 memoization intact

Current `Scene.tsx`:

```tsx
import { useMemo } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useStore } from '../store';
import { useForceGraph } from './useForceGraph';
import { Regions } from './Regions';

export function Scene() {
  const regions = useStore((s) => s.regions);
  const adjacency = useStore((s) => s.adjacency);
  const names = useMemo(() => Object.keys(regions).sort(), [regions]);
  const nodes = useForceGraph(names, adjacency);
  return (
    <Canvas camera={{ position: [0, 0, 12], fov: 55 }} style={{ background: '#080814' }}>
      <ambientLight intensity={0.35} />
      <directionalLight position={[10, 10, 5]} intensity={0.6} />
      <Regions nodesRef={nodes} />
      <OrbitControls />
    </Canvas>
  );
}
```

Add `<Sparks nodesRef={nodes} />` after `<Regions nodesRef={nodes} />`, plus the import. NO other changes.

### 11. Commit discipline

One commit for Task 13 per Principle XII. Stage only:
- `observatory/web-src/src/scene/topicColors.ts`
- `observatory/web-src/src/scene/topicColors.test.ts`
- `observatory/web-src/src/scene/Sparks.tsx`
- `observatory/web-src/src/scene/Scene.tsx`
- `observatory/memory/decisions.md`
- `observatory/prompts/task-13-sparks.md`

Do NOT stage:
- `observatory/web/` (gitignored).
- Any Python files.

Use the plan's Step 6 HEREDOC verbatim:

```
observatory: traveling sparks on edges (task 13)

Instanced-mesh particles (cap 2000) lerp from source region to each
destination inferred in the envelope, colored by topic-branch prefix.
Lifetime 800 ms. Color table unit-tested; scene fan-out tested
manually against live broker traffic.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Stage explicitly (NOT `git add -A`):

```
git add observatory/web-src/src/scene/Sparks.tsx \
        observatory/web-src/src/scene/topicColors.ts \
        observatory/web-src/src/scene/topicColors.test.ts \
        observatory/web-src/src/scene/Scene.tsx \
        observatory/memory/decisions.md \
        observatory/prompts/task-13-sparks.md
```

## Verification gate — MUST pass before commit

```bash
cd observatory/web-src
npx tsc -b                                                  # clean
npm run build                                               # vite build succeeds
npm run test                                                # 18 passed (8 prior + 10 topicColors + 1 optional cache test)

# Optional from repo root:
cd /c/repos/hive
.venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q   # 67 passed
.venv/Scripts/python.exe -m ruff check observatory/             # clean
```

If any fail, DO NOT commit — diagnose first.

## What you'll deliver back

1. TDD evidence — exact failure output for Step 1's red-phase run of `topicColors.test.ts`.
2. Final `npm run test` output (count of passing tests).
3. `npx tsc -b` output (empty = success).
4. `npm run build` output (bundle sizes; chunk-size warning expected).
5. Confirmation the `TOPIC_COLOR_CACHE` drift (§1) was applied.
6. Any plan-code drift beyond §1 you encountered and how you resolved it.
7. Commit SHA.
8. Follow-up threads worth logging.

Do NOT summarize away unexpected events. Surface them.
