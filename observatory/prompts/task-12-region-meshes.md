# Implementer prompt — Observatory v1, Task 12: Region meshes (phase color + halo + size + ring)

## Context

You are a fresh implementer subagent executing **Task 12** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–11 shipped with review-fixes. Backend suite: **67 unit + 1 component** passing, ruff clean. Frontend: **8 tests** passing (5 store + 3 ws), `tsc -b` + `vite build` clean. HEAD is `5316f94`.

Task 12 is the **first per-frame animation code** — introduces `useFrame` (which Task 11's decisions entry 58 flagged as deferred). It replaces Task 11's placeholder cubes with real region meshes: base sphere colored by `stats.phase`, emissive halo whose opacity tracks a rolling token-burn estimate, slight size scaling from `queue_depth`, and a thin torus whose segment count reflects `handler_count`.

## Authoritative documents (read first)

- **Plan (Task 12):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 12:` at line 2534 (spans to line 2657). Complete code blocks verbatim.
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Spec (phase palette + visual mapping):** `observatory/docs/specs/2026-04-20-observatory-design.md` §4.2 — phase-to-color mapping, halo semantics, handler-ring torus.
- **Task 11 existing state (CRITICAL — DO NOT REVERT):**
  - `observatory/web-src/src/scene/Scene.tsx` has `const names = useMemo(() => Object.keys(regions).sort(), [regions]);` — this is Task 11's review-fix, NOT what the Task 12 plan shows verbatim. Preserve it. See §1 below.
  - `observatory/web-src/src/scene/useForceGraph.ts` is a single long-lived sim now — no rebuilds on render. Task 12 can safely subscribe per frame.
  - `observatory/web-src/src/types.d.ts` has a minimum-typed `d3-force-3d` shim. Task 12 doesn't need to modify it unless it imports new d3-force-3d symbols (it doesn't, per the plan).
- **Store contract:** `observatory/web-src/src/store.ts` — `RegionStats` has `phase`, `queue_depth`, `tokens_lifetime`, `handler_count` (among others).
- **Prior decisions log:** `observatory/memory/decisions.md` — entries 57–62 are Task 11. Pay attention to entries 58 (useFrame deferral) and 60 (sim stability review-fix).

## Your scope

Execute plan Steps 1–4, in order:

1. Create `observatory/web-src/src/scene/Regions.tsx` (verbatim from plan — except see §2 below about the `useStore((s) => Object.keys(s.regions))` selector).
2. Modify `observatory/web-src/src/scene/Scene.tsx` — replace the placeholder-cube block with `<Regions nodesRef={nodes} />`. **BUT preserve the `useMemo` for `names`** (see §1).
3. Visual verification — see §5 below; substitute build-based verification.
4. Commit with plan Step 4 HEREDOC verbatim.

You are NOT doing Task 13 (sparks). Stop at Task 12.

## Critical concerns & pre-approved guidance

### 1. Scene.tsx `names` memoization — DO NOT REVERT Task 11's review-fix

The Task 12 plan's Step 2 code block shows:

```tsx
const regions = useStore((s) => s.regions);
const adjacency = useStore((s) => s.adjacency);
const names = Object.keys(regions);            // ← plan verbatim
const nodes = useForceGraph(names, adjacency);
```

Current `Scene.tsx` on `main` (post Task 11 review-fix) reads:

```tsx
const names = useMemo(() => Object.keys(regions).sort(), [regions]);
```

**Keep the memoized version. Do NOT revert to plan's unmemoized `Object.keys(regions)`.** Task 11's review-fix (decision entry 60) exists precisely because the unmemoized version caused the d3 simulation to tear down on every render — which is the latent perf bug Task 12's live-data flow would manifest. Reverting undoes that fix.

**Pre-approved full Scene.tsx content** (plan Step 2 verbatim EXCEPT the `names` line and the added `useMemo` import):

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

Log the deviation from plan-verbatim as a drift entry in `decisions.md` citing entry 60.

### 2. `Regions.tsx` selector — same class of bug

Plan's `Regions.tsx` Step 1 has:

```tsx
const names = useStore((s) => Object.keys(s.regions));
```

This selector allocates a new array every zustand read. zustand's default equality check is `Object.is`, so this component re-renders on EVERY store update — even envelope pushes that don't touch `regions`. Under Task 13+ with live envelopes at ~50–100 msg/s, that's 50–100 re-renders/sec of a ~14-region list, each triggering `useMemo` recomputation.

**Pre-approved fix:** replicate Scene.tsx's pattern — select the stable `regions` slice, then memoize the keys:

```tsx
const regions = useStore((s) => s.regions);
const names = useMemo(() => Object.keys(regions).sort(), [regions]);
```

`useMemo` is already imported per the plan. No new import. Behavior: zustand re-renders `Regions` only when the `regions` reference changes (which happens when the registry changes, not on envelope pushes). The memoized `names` is then stable until `regions` changes — matching Scene.tsx's pattern and making the downstream `useMemo` for `nodes` stable too.

Log as a review-fix-style drift in `decisions.md`.

### 3. `useFrame` semantics

Task 12 is the first `useFrame` usage. `useFrame((_, dt) => { ... })` runs **every frame** (~60 Hz). Keep the body cheap:
- Avoid allocations per frame if possible. The plan's `new Color(PHASE_COLOR[...])` allocates a new `Color` every frame per region — that's ~14 × 60 = ~840 allocations/sec. Not catastrophic but worth flagging as a Task 16 polish opportunity (can be cached in a `useMemo` keyed on phase). Do NOT optimize in Task 12 — leave it plan-verbatim.
- `meshRef.current.material.color.lerp(col, Math.min(1, dt * 3))` mutates the material's color toward the target. The `dt * 3` makes the lerp reach ~99% within ~1.5s of a phase change. Good.
- `meshRef.current.scale.setScalar(scale)` — mutates scale in place; no allocation. Good.

### 4. `useRef<any>(null)` — intentional looseness

The plan uses `useRef<any>(null)` for `meshRef`, `haloRef`, `tokensRef`, `burnRef`. Under strict mode this is accepted. Do NOT tighten to `useRef<Mesh>(null)` or similar — three.js ref types are fiddly and the plan deliberately keeps them loose. Revisit in a Task 16 polish pass.

However `tokensRef` / `burnRef` are `useRef<number>(...)` per the plan — NOT `any`. Keep those typed.

### 5. Verification — no browser available

Step 3's visual verification (spheres appear, phase colors, halo brightens, handler ring visible) requires a real browser. Substitute:

```bash
cd observatory/web-src
npx tsc -b                     # typecheck
npm run build                  # vite build
npm run test                   # 8/8 passing unchanged (no new tests in Task 12)
```

If those pass, the scene compiles and React rendering type-checks. Real visual verification deferred to Larry.

### 6. No new tests

Task 12 doesn't add tests per the plan. The `useFrame` callback is hard to unit-test without a full three.js renderer. Don't preemptively add component tests — Task 16 handles frontend CI. Existing 8 tests must remain green (store + ws untouched).

### 7. Deleting the placeholder cubes

The plan's Step 2 replaces the placeholder `{Array.from(nodes.current.values()).map(...)}` block from Task 11's Scene.tsx with `<Regions nodesRef={nodes} />`. Delete the block cleanly — don't leave the `// Stub: render a tiny cube ...` / `// (Remove this block when Task 12 lands.)` comment.

### 8. `<Regions>` prop typing

Plan: `({ nodesRef }: { nodesRef: React.MutableRefObject<Map<string, ForceNode>> })`. Matches what `useForceGraph` returns (`React.MutableRefObject<Map<string, ForceNode>>` via `useRef<Map<string, ForceNode>>(new Map())`). Type-checks.

React 19 deprecates `MutableRefObject` in favor of `RefObject` (which is now mutable), but we're on React 18 per Task 9 pins. Don't change.

### 9. Commit discipline

One commit for Task 12 per Principle XII. Stage only:
- `observatory/web-src/src/scene/Regions.tsx`
- `observatory/web-src/src/scene/Scene.tsx`
- `observatory/memory/decisions.md`
- `observatory/prompts/task-12-region-meshes.md` (THIS file)

Do NOT stage:
- `observatory/web/` (gitignored build output).
- Any Python files.

Use the plan's Step 4 HEREDOC verbatim:

```
observatory: region meshes — phase color, halo, size, handler ring (task 12)

Each region renders as a sphere (color from stats.phase), a
translucent halo whose opacity tracks a 500-tok/sec rolling burn
estimate, and a thin torus whose segment count matches handler_count.
Queue depth nudges sphere scale up to 1.3x.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Stage explicitly (NOT `git add -A`):

```
git add observatory/web-src/src/scene/Regions.tsx \
        observatory/web-src/src/scene/Scene.tsx \
        observatory/memory/decisions.md \
        observatory/prompts/task-12-region-meshes.md
```

## Verification gate — MUST pass before commit

```bash
cd observatory/web-src
npx tsc -b                                                  # clean
npm run build                                               # vite build succeeds
npm run test                                                # 8/8 passed

# From repo root, optional:
cd /c/repos/hive
.venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q    # 67 passed
.venv/Scripts/python.exe -m ruff check observatory/              # clean
```

If any fail, DO NOT commit — diagnose first.

## What you'll deliver back

1. Confirmation each plan step 1–4 was executed (noting the two plan-vs-existing deviations in Scene.tsx and Regions.tsx).
2. `npx tsc -b` output (empty = success).
3. `npm run build` output (bundle sizes; warn-sizes are expected).
4. `npm run test` output (8/8 unchanged).
5. Any plan-code drift beyond the two §1/§2 pre-approved fixes.
6. Commit SHA.
7. Follow-up threads (e.g., `new Color` per-frame allocation, any other perf concerns you noticed).

Do NOT summarize away unexpected events. Surface them.
