# Implementer prompt — Observatory v1, Task 10: WebSocket client + REST client + zustand store

## Context

You are a fresh implementer subagent executing **Task 10** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–9 shipped with review-fixes. Backend suite is **67 unit + 1 component** passing, ruff clean. Frontend scaffolding landed in Task 9 (`8b6be24` + review-fix `fc0ce94`, HANDOFF `92bf3fa`). HEAD is `92bf3fa`.

Task 10 is the **first real frontend logic** — introduces the zustand store (`src/store.ts`), the WebSocket client (`src/api/ws.ts`), the REST client (`src/api/rest.ts`), a `vitest.config.ts`, and co-located tests. This is the glue that Tasks 11–16 build the 3D scene + HUD on top of.

## Authoritative documents (read first)

- **Plan (Task 10):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 10:` at line 2102 (spans to line 2390). Complete code blocks verbatim.
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Spec:** `observatory/docs/specs/2026-04-20-observatory-design.md` §5 — the WebSocket protocol (five message types: `snapshot`, `envelope`, `region_delta`, `adjacency`, `decimated`).
- **Backend reference for WS protocol:** `observatory/ws.py` — authoritative source of the server-side message shapes. The client must parse all five types. `decimated` is ignored for v1 (hook for future "lagging" badge per plan comment).
- **Backend reference for REST:** `observatory/api.py` — `/api/health` returns `{status, version}`; `/api/regions` returns `{regions: Record<str, RegionMeta>}`.
- **Existing frontend scaffolding (don't disturb):** `observatory/web-src/{package.json, vite.config.ts, tsconfig.json, tsconfig.node.json, tailwind.config.ts, postcss.config.js, index.html, src/{main.tsx, App.tsx, index.css}}`.
- **Prior decisions log:** `observatory/memory/decisions.md` — entries 46–51 are Task 9; review for context on Tailwind/Vite pinning and drift patterns to expect.

## Your scope

Execute plan Steps 1–8, in order, **following TDD** (Step 2 writes failing test BEFORE Step 3 implementation):

1. Create `observatory/web-src/vitest.config.ts` (verbatim).
2. Write `observatory/web-src/src/store.test.ts` (verbatim) — should fail.
3. Implement `observatory/web-src/src/store.ts` (verbatim) — Step 2 tests should now pass.
4. Write `observatory/web-src/src/api/ws.test.ts` (verbatim) — should fail (file doesn't exist yet).
5. Implement `observatory/web-src/src/api/ws.ts` (verbatim) — Step 4 tests should now pass.
6. Implement `observatory/web-src/src/api/rest.ts` (verbatim).
7. Run `npm run test` from `observatory/web-src/` — all tests pass.
8. Commit with the plan's Step 8 HEREDOC verbatim.

You are NOT doing Task 11 (scene + force graph). Stop at Task 10.

## Critical concerns & pre-approved guidance

### 1. TDD discipline (rigid)

This is the first Task using `superpowers:test-driven-development`. Strict sequence:
- Step 2: write `store.test.ts` and **actually run** `npm run test` to see it fail (expected: `Cannot find module './store'` or similar). Capture the failure mode in your report.
- Step 3: implement `store.ts`, run again, all store tests pass.
- Step 4: write `ws.test.ts`, run, fail.
- Step 5: implement `ws.ts`, run, pass.
- Do NOT write Step 3 before Step 2 runs. Do NOT skip the red phase.

### 2. TypeScript strict mode — watch for these

`tsconfig.json` has `strict: true`, `noUnusedLocals: true`, `noUnusedParameters: true`. The plan's verbatim code should type-check because:
- `store.ts` uses `as any` in test-only locations, and its production code has explicit types throughout.
- `ws.ts` uses `StoreApi<any>` / `UseBoundStore<StoreApi<any>>` by design (store type is generic to both tests and real store).

Known plan-code drift risks to watch:
- **`extractAmbient`** casts `topic.slice('hive/modulator/'.length) as keyof Ambient['modulators']` — the cast is unsafe but deliberate; TypeScript accepts it. Don't "improve" by narrowing.
- **`applyRetained`**'s scope only handles `hive/modulator/*` — self/felt_state updates via live retained are deferred to a future task; plan snapshot extraction handles all of them. Don't expand.
- **`WebSocket`, `location`, `setTimeout`, `console`** in `ws.ts` require DOM lib types. `tsconfig.json` already has `"lib": ["ES2022", "DOM", "DOM.Iterable"]`. Only the test runs at Node runtime, and tests don't call `connect()` — just `handleServerMessage()`. Pure function, no globals touched.

If you hit a legitimate type error the plan doesn't anticipate, FIX minimally and log in `decisions.md`. Do not `// @ts-ignore`.

### 3. Vitest environment — why `node` works

`vitest.config.ts` sets `environment: 'node'`. This means NO DOM globals (`window`, `location`, `document`, `WebSocket`). Tests here don't need them — both test files exercise pure functions (`handleServerMessage`, store actions). **Do NOT switch to `jsdom`** for Task 10. Tasks 11+ may need jsdom when testing React components; that's a later call.

Node 20.x provides global `WebSocket` (stable since 22.0.0; flagged on 20). Since tests never instantiate `WebSocket`, neither behavior matters. If vitest emits a warning about `WebSocket` being undefined during module-eval of `ws.ts`, report it — but don't fix without guidance.

### 4. `vi.spyOn(s.getState(), 'applySnapshot')` caveat

The store.test.ts test for `ws.ts` snapshot routing uses `vi.spyOn(s.getState(), 'applySnapshot')`, then calls `handleServerMessage(s, { type: 'snapshot', ... })`.

For this to work: `store.getState()` inside `handleServerMessage` must return the SAME state object reference whose `applySnapshot` is the spy. zustand's `getState()` returns the current state by reference until a mutation occurs. Since no mutation has happened between the spy and the `handleServerMessage` call, the spy is live. Accept the plan's spy pattern as-is.

If the spy doesn't fire (possible if zustand freezes state or returns a new object on each `getState()`), that's a real drift. Fix options:
- Check `applySnapshot` was called by asserting on state (e.g., `expect(s.getState().regions).toEqual(...)` instead of `expect(spy).toHaveBeenCalled()`).
- Log the drift in `decisions.md`.

Try the plan verbatim first.

### 5. `StoreApi<any>` / `UseBoundStore<StoreApi<any>>`

Plan deliberately types the store as `any` in `ws.ts` to avoid circular imports between `store.ts` (which defines `State`) and `ws.ts` (which would need to reference `State`). This is an intentional looseness — do NOT tighten it in this task. Tightening may come when Task 12+ introduces a shared `types.ts`.

### 6. Ring cap = 5000

Plan's `RING_CAP = 5000`. The third store test asserts that after 5100 pushes, `envelopes.length === 5000`. Verify `pushEnvelope` uses `splice(0, next.length - RING_CAP)` to drop the oldest — that's what the plan says. Don't change to `slice` (would leak memory via repeated reallocs) or `shift()` (O(n) per call).

### 7. Tests must not touch backend

Do NOT run backend Python tests during Task 10. Verification for this task is `npm run test` only. Backend is untouched by Task 10 diff; the 67 unit + 1 component tests remain green by construction. If you want to double-check at the very end, run `.venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q` (Windows; the `.venv/` at repo root has pytest installed — plain `python -m pytest` fails because system Python 3.12 lacks pytest).

### 8. Commit discipline

One commit for Task 10 per Principle XII. Stage only:
- `observatory/web-src/vitest.config.ts`
- `observatory/web-src/src/store.ts`
- `observatory/web-src/src/store.test.ts`
- `observatory/web-src/src/api/ws.ts`
- `observatory/web-src/src/api/ws.test.ts`
- `observatory/web-src/src/api/rest.ts`
- Any `observatory/memory/decisions.md` updates (if drift happened).

Do NOT stage:
- `observatory/web/` (gitignored build output; will regenerate on next build — no need to rebuild for Task 10).
- `observatory/web-src/node_modules/` (gitignored).
- Anything outside `observatory/`.

Use the plan's Step 8 HEREDOC verbatim:

```
observatory: zustand store + WS/REST clients (task 10)

State: regions, envelopes (ring cap 5000), adjacency, ambient
(modulators + self from retained topics). WS client parses server
messages and routes to store actions with auto-reconnect.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Stage explicitly (NOT `git add -A`): `git add observatory/web-src/src/store.ts observatory/web-src/src/store.test.ts observatory/web-src/src/api/ observatory/web-src/vitest.config.ts observatory/memory/decisions.md`.

## Verification gate — MUST pass before commit

```bash
cd observatory/web-src
npm run test          # all vitest tests pass
npx tsc -b --noEmit   # typechecks (the tsc -b is what `npm run build` does first)
```

(The second command confirms strict TypeScript acceptance without triggering a full vite build — faster feedback than `npm run build`.)

If either fails, diagnose first, do NOT commit.

## What you'll deliver back

A short written report covering:
1. TDD evidence — the exact failure output for Step 2's red-phase run of `store.test.ts` and Step 4's red-phase run of `ws.test.ts`.
2. Final `npm run test` output (pass count per file, total).
3. `npx tsc -b --noEmit` output (should be empty/clean).
4. Any plan-code drift encountered and how you resolved it.
5. The commit SHA you landed.
6. Any follow-up threads worth logging.

Do NOT summarize away unexpected events — surface them. The spec-compliance reviewer will cross-check.
