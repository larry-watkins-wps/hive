# Implementer prompt — Observatory v1, Task 11: Scene shell + force graph hook

## Context

You are a fresh implementer subagent executing **Task 11** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–10 shipped with review-fixes. Backend suite is **67 unit + 1 component** passing, ruff clean. Frontend: **8 tests** passing (5 store + 3 ws), `tsc -b` clean. HEAD is `e0bf13d`.

Task 11 is the **first task that introduces React + three.js + d3-force-3d**. It mounts a full-viewport `<Canvas>`, adds orbit controls and lights, and introduces `useForceGraph` — a custom hook that maintains per-region positions via a d3-force-3d simulation. For this task you render placeholder cubes at each node position; Task 12 replaces them with real region meshes.

Task 11 output is **primarily visual scaffolding** — not a unit-testable feature. The plan does not ask for new tests. Do NOT add tests that go beyond the plan; Task 10's frontend test infrastructure stays in place untouched.

## Authoritative documents (read first)

- **Plan (Task 11):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 11:` at line 2394 (spans to line 2531). Complete code blocks verbatim.
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Spec (scene physics):** `observatory/docs/specs/2026-04-20-observatory-design.md` §4 — region placement, perimeter bias for sensory/motor regions, mPFC pinned at origin.
- **Existing store contract:** `observatory/web-src/src/store.ts` — `useStore` (default-bound hook), `regions` map, `adjacency` array.
- **Existing WS client contract:** `observatory/web-src/src/api/ws.ts` — `connect(store)` returns a cleanup function suitable for `useEffect` return.
- **Existing placeholder App:** `observatory/web-src/src/App.tsx` — currently a stub rendered by Task 9 scaffolding. Task 11 replaces it.
- **Prior decisions log:** `observatory/memory/decisions.md` — entries 46–56 are Tasks 9 + 10. Review for drift patterns to expect.

## Your scope

Execute plan Steps 1–5, in order:

1. Create `observatory/web-src/src/scene/useForceGraph.ts` (verbatim from plan).
2. Create `observatory/web-src/src/scene/Scene.tsx` (verbatim).
3. Replace `observatory/web-src/src/App.tsx` (verbatim — NOT appended, fully replaced).
4. Visual verification — see §5 below; you likely **cannot run a real browser check**, so substitute a build-based verification (see below).
5. Commit with plan Step 5 HEREDOC verbatim.

You are NOT doing Task 12 (real region meshes). Keep the placeholder cubes; plan Step 2's code block explicitly commits them with a `Remove this block when Task 12 lands.` comment. Do not delete the cubes.

## Critical concerns & pre-approved guidance

### 1. `d3-force-3d` has no type definitions — THIS TASK MUST FIX IT

Task 9's review-fix removed the phantom `@types/d3-force-3d` devDep. `d3-force-3d` itself ships no `.d.ts`. Task 11's `useForceGraph.ts` is the **first file that imports `d3-force-3d`**. Without an ambient module declaration, `tsc -b` will fail with `TS7016: Could not find a declaration file for module 'd3-force-3d'.`.

**Pre-approved fix:** create `observatory/web-src/src/types.d.ts` with:

```typescript
declare module 'd3-force-3d';
```

Add this to the commit. Log as a Task 11 plan-code drift entry in `decisions.md` (the plan didn't include this file, but Task 9 decision entry 46 explicitly delegated it to "Task 10+ when `d3-force-3d` is actually imported" — and Task 11 is the first import).

If upstream DefinitelyTyped ever publishes types, swap the ambient declaration for the real package. Not today's problem.

### 2. Plan-reality mismatch on "cubes gently settle" — do NOT overfix

The plan's Step 4 says "Confirm cubes appear and gently settle." The plan's `Scene.tsx` does NOT have a `useFrame` hook driving per-frame React re-renders. d3-force-3d mutates node positions in-place via its internal timer, but `<mesh position={[n.x, n.y, n.z]}>` only reads those positions on each React render.

Result: cubes will appear near their seed positions and NOT visibly animate. This is expected for Task 11 — Task 12+ will introduce `useFrame` or an imperative ref-based position sync. DO NOT add `useFrame` proactively to "fix the settle" — that's Task 12's concern and pre-emptive work can diverge the plan.

Log this as an observation in `decisions.md` (not a blocker, just a heads-up for Task 12).

### 3. `useEffect(() => connect(useStore), [])` in App.tsx

`connect()` returns `() => void` (cleanup fn). React's `useEffect` expects either `undefined` or a cleanup fn as return. `connect(useStore)` evaluates to the cleanup, and returning that from the effect arrow is exactly what React wants. Don't "improve" by destructuring or wrapping in `{}` block — that breaks the cleanup return.

React strict-mode will mount + immediately unmount + remount in dev. That means `connect` runs, cleanup runs, connect runs again — producing two WebSocket connections over the effect lifetime. Task 10's review-fix for the reconnect race makes this safe (cleanup clears pending reconnect timer). Expected dev-mode behavior; not a bug.

### 4. TypeScript strict mode — watch for these

`tsconfig.json` has `strict: true`, `noUnusedLocals: true`, `noUnusedParameters: true`. The plan's verbatim code type-checks ONCE `types.d.ts` is in place. Specific strict checks to verify:

- `useForceGraph`'s `forceSimulation<ForceNode>` — the `<ForceNode>` generic threads through `forceX`, `forceY`, `forceZ`, `forceLink`. Good.
- `PERIMETER_BIAS[d.id]?.[0] ?? 0` — optional chain + nullish coalesce. Good.
- `PERIMETER_BIAS[name] ?? [...]` — returns tuple-or-tuple, destructure works.
- `ForceNode` has optional `fx/fy/fz`, set only for `medial_prefrontal_cortex` — good.
- `Array.from(nodes.current.values())` — `Map.values()` returns `MapIterator<ForceNode>`; `Array.from` works.
- `Canvas` + `OrbitControls` + `ambientLight`/`directionalLight`/`mesh`/`boxGeometry`/`meshStandardMaterial` — all from `@react-three/fiber` and three.js JSX namespace. Should type-check given `@types/three` is installed.

If `@react-three/fiber`'s JSX augmentation doesn't resolve in strict mode (sometimes needs a tsconfig `"types"` addition), fix minimally by adding `"@react-three/fiber"` to `compilerOptions.types` in `tsconfig.json`. Log as drift.

### 5. `nodesRef` return shape

The plan returns `nodesRef` (the React ref) from `useForceGraph`, not a snapshot array. `Scene.tsx` does `nodes.current.values()`. This is a deliberate choice so Task 12 can swap to a `useFrame`-driven update without re-exporting. Keep it verbatim. Don't return `nodes` (the memoized array) — that's Task 12's concern.

Note: `useMemo` regenerates `nodes` whenever `names` changes, repopulating the map (preserves existing node identity via `.has(name)` check). Good.

### 6. Verification — you likely can't run a browser

Visual verification in Step 4 is ideal but outside this subagent's tool surface. Substitute:

```bash
cd observatory/web-src
npx tsc -b                  # typecheck (must be clean)
npm run build               # full vite build must succeed
```

If both pass, the scene compiles. The cubes appearing in a real browser is a human-loop check deferred to Larry. Flag in your report that you could NOT do the actual visual check.

DO NOT try to spin up the FastAPI backend + vite dev server + browser check unless you have explicit shell access to do so. The implementer prompt timeout is not worth consuming on that.

### 7. App.tsx is a full REPLACE, not an edit

Plan Step 3 gives a complete new `App.tsx`. Use `Write` (or equivalent full overwrite) — do NOT attempt to patch the existing one. The current content (`<div>...observatory — scaffolding...</div>`) is a Task 9 placeholder and must be replaced entirely.

### 8. Commit discipline

One commit for Task 11 per Principle XII. Stage only:
- `observatory/web-src/src/scene/useForceGraph.ts`
- `observatory/web-src/src/scene/Scene.tsx`
- `observatory/web-src/src/App.tsx`
- `observatory/web-src/src/types.d.ts` (the drift-fix ambient module declaration)
- `observatory/memory/decisions.md` (drift entries)
- `observatory/prompts/task-11-scene-force-graph.md` (THIS file — convention reinstated in Task 9 review-fix)

Do NOT stage:
- `observatory/web/` (gitignored build output).
- Any Python files.

Use the plan's Step 5 HEREDOC verbatim:

```
observatory: scene shell + force graph (task 11)

Full-viewport Canvas with orbit controls, directional + ambient
lighting, and useForceGraph hook that seeds perimeter-biased
positions for sensory/motor regions and pins mPFC at origin.
Placeholder cubes render one per region; Task 12 replaces them
with the real region meshes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Stage explicitly (NOT `git add -A`):

```
git add observatory/web-src/src/scene/ \
        observatory/web-src/src/App.tsx \
        observatory/web-src/src/types.d.ts \
        observatory/memory/decisions.md \
        observatory/prompts/task-11-scene-force-graph.md
```

## Verification gate — MUST pass before commit

```bash
cd observatory/web-src
npx tsc -b                                        # clean typecheck
npm run build                                     # vite build succeeds
npm run test                                      # 8 frontend tests (no regression; task doesn't add tests)

# Optional from repo root — Python suite should be untouched:
cd /c/repos/hive
.venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q   # expect 67 passed
.venv/Scripts/python.exe -m ruff check observatory/             # expect clean
```

If any fails, DO NOT commit — diagnose first.

## What you'll deliver back

A short written report covering:
1. Confirmation each plan step 1–5 was executed.
2. Output of `npx tsc -b` (should be empty/clean).
3. Output of `npm run build` (vite build success + output bundle sizes).
4. Output of `npm run test` (8 passed unchanged).
5. Any plan-code drift encountered and how you resolved it — at minimum the `types.d.ts` ambient declaration for d3-force-3d.
6. The commit SHA you landed.
7. Any follow-up threads worth logging (e.g., the `useFrame` observation from §2, react-three-fiber JSX typing if you hit it).

Do NOT summarize away unexpected events. Surface them.
