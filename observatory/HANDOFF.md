# Observatory — Session Handoff

*Last updated: 2026-04-21 (session 3 — v1 SHIPPED, all 16 tasks complete)*

**Canonical resume prompt:** `continue observatory v1`

---

## State snapshot

| Milestone | Status | Notes |
|---|---|---|
| Brainstorm | ✅ Complete | 2026-04-20 — design approved |
| Spec written | ✅ Complete | `observatory/docs/specs/2026-04-20-observatory-design.md` |
| Plan written | ✅ Complete | `observatory/docs/plans/2026-04-20-observatory-plan.md` (16 tasks, ~3247 lines) |
| v1 Task 1 — scaffolding + ring buffer | ✅ Complete | Commits `3896f64` + `491a36a` |
| v1 Task 2 — retained cache + region registry | ✅ Complete | Commits `fb6b9e8` + `1978fc5` |
| v1 Task 3 — adjacency + decimator | ✅ Complete | Commits `01ccebd` + `e260f6c` |
| v1 Task 4 — MQTT subscriber | ✅ Complete | Commits `af892da` + `a1d9536` |
| v1 Task 5 — REST `/api/health` + `/api/regions` | ✅ Complete | Commit `9fa2c63` |
| v1 Task 6 — WebSocket hub + fan-out | ✅ Complete | Commits `1eec20d` + `a55ea81` |
| v1 Task 7 — service assembly + CLI + Dockerfile | ✅ Complete | Commits `35f07a6` + `aeeb1d6` |
| v1 Task 8 — component e2e (testcontainers) | ✅ Complete | Commits `7805de0` + `fad225c` |
| **v1 backend — complete, end-to-end verified against real broker** | ✅ | |
| v1 Task 9 — frontend scaffolding (Vite + React + TS + Tailwind) | ✅ Complete | Commits `8b6be24` + `fc0ce94` |
| v1 Task 10 — WebSocket client + REST client + zustand store | ✅ Complete | Commits `4cd41aa` + `efb8397` |
| v1 Task 11 — Scene shell + force graph hook | ✅ Complete | Commits `b188dcd` + `d614a48` |
| v1 Task 12 — Region rendering (phase color + halo + size + ring) | ✅ Complete | Commits `eddc34c` + `aae715a` |
| v1 Task 13 — Sparks (traveling particles on edges) | ✅ Complete | Commits `bac42b4` + `8e40701` |
| v1 Task 14 — Modulator fog + rhythm pulse | ✅ Complete | Commits `f3d3e14` + `7eb7fd9` |
| v1 Task 15 — HUD (self panel + modulators + counters) | ✅ Complete | Commits `79fcb4b` + `44f7c44` |
| v1 Task 16 — Integration + polish | ✅ Complete | Commit `3f4b28f` |
| **v1 — SHIPPED** | ✅ | All 16 tasks landed across sessions 2–3. |
| v2 implementation | ⏳ Pending | |
| v3 implementation | ⏳ Pending | |

## Suite + lint snapshot

- `python -m pytest observatory/tests/unit/ -q` → **67 passed** (ring buffer 5 + config 4 + retained cache 4 + region registry 7 + adjacency 4 + decimator 7 + MQTT subscriber 16 + api 2 + ws 8 + service 10)
- `python -m pytest observatory/tests/component/ -m component -v` → **1 passed** (requires Docker Desktop; `eclipse-mosquitto:2` via testcontainers; real MQTT publish → WS receive verified)
- `python -m ruff check observatory/` → clean
- Smoke test: `python -c "from observatory.config import Settings; from observatory.service import build_app; build_app(Settings())"` → `ok`
- Smoke-verified against production `glia/regions_registry.yaml`: 19 regions load correctly (`layer` → `role` mapping).
- Frontend: `cd observatory/web-src && npm run build` → `observatory/web/index.html` + `assets/index-*.{js,css}` emitted in ~800 ms.
- Frontend: `cd observatory/web-src && npm run test` → **22 passed** (6 store + 3 ws + 13 topicColors). Typecheck via `npx tsc -b` clean.
- Frontend: `cd observatory/web-src && npm run build` → `observatory/web/` emitted; bundle ~991 kB (three.js + drei + fiber + d3-force-3d); chunk-size warning expected, Task 16 polish.

## What's done (session 3)

Executed **Tasks 9–16** with `superpowers:subagent-driven-development` discipline: fresh implementer per task, two-stage review (spec-compliance + code-quality) after each (Tasks 9–15), review-fix commit on top of each. Task 16 was verification + HANDOFF closure with no production code changes. Implementer prompts stored under `observatory/prompts/`. Non-obvious calls logged in `observatory/memory/decisions.md` (entries 46–87).

**Session 3 totals: 8 task commits + 7 review-fix commits + HANDOFF bumps.**

### Task 16 — v1 ships

Verification-only task. Ran the full automated suite (67 Python unit + 1 component via real broker + 22 frontend vitest + ruff clean), produced the production bundle, and smoke-tested the FastAPI static mount end-to-end via `curl`. Visual E2E (phase colors, halos, sparks, gauges) is **deferred to Larry's human-loop review** — this environment has no GUI browser. Smoke test results captured:

- `npm run build` → `observatory/web/index.html` (0.43 kB) + `assets/index-R8JuebiC.css` (7.76 kB) + `assets/index-C4B-WPRx.js` (998.04 kB; gzip 278.83 kB) in 3.38 s.
- `curl http://127.0.0.1:8765/api/health` → `{"status":"ok","version":"0.1.0"}`.
- `curl http://127.0.0.1:8765/` → `<!doctype html><html lang="en">…` (Vite-built index.html served from the FastAPI static mount).

Smoke test **also surfaced a Windows-dev-only latent bug** in `observatory/service.py::_on_mqtt_task_done`: under `python -m observatory` the default `ProactorEventLoop` makes aiomqtt's `add_reader`/`add_writer` raise `NotImplementedError`, the MQTT task crashes, and the done-callback's `log.error(..., exc_info=exc)` then trips `UnicodeEncodeError` in structlog's ConsoleRenderer against Windows cp1252 stdout. **HTTP server keeps serving** (both smoke `curl` calls returned 200 OK after the callback crash); Linux/Docker deploy path is unaffected (no Proactor loop there). Logged as v1.1 follow-ups in decisions.md entry 87.

### Task 9 substantive fixes vs. the plan

- **Drift A** — Plan's `package.json` devDep `@types/d3-force-3d@^3.0.10` doesn't exist on npm (DefinitelyTyped never published it; `d3-force-3d` ships no own types). `npm install` hard-failed with E404. **Fix:** removed that devDep. Task 11+ will need an ambient-module declaration (`declare module 'd3-force-3d';`) in `src/types.d.ts` when `d3-force-3d` is actually imported.
- **Drift B** — Plan omitted `@types/node`, causing ~60 `TS2307`/`TS2580` errors from vite's `index.d.ts` references to `node:http`/`Buffer`/`NodeJS`. **Fix:** added `@types/node@^20` (matches Dockerfile's `node:20-alpine` builder).
- **Drift C** — Plan's `tsconfig.json` (no `noEmit`) + `tsconfig.node.json` (`composite: true`) emit `.js`/`.d.ts`/`.tsbuildinfo` residue next to sources on every build. **Fix:** added `"noEmit": true` to `tsconfig.json` (Vite-starter default) + five additive patterns to `observatory/.gitignore` (`*.tsbuildinfo`, `web-src/{vite,tailwind}.config.{js,d.ts}`).
- **Review-fix** — `vite.config.ts` dev-server proxy changed `localhost:8765` → `127.0.0.1:8765` (matches commit-message intent, avoids Windows IPv6-first resolver gotcha when FastAPI binds to `127.0.0.1`).

### Task 10 substantive fixes vs. the plan

- **Drift** — Prompt's verification gate said `npx tsc -b --noEmit`, but Task 9's `noEmit: true` on the root tsconfig + `composite: true` on `tsconfig.node.json` makes `-b --noEmit` fail with `TS6310`. Verified via `npx tsc -b` alone (what `npm run build` actually runs) — clean.
- **Drift** — `tsc -b` now also emits `vitest.config.js` / `vitest.config.d.ts` residue (same class as Task 9's `vite.config.*` residue). `observatory/.gitignore` extended with two more patterns.
- **Review-fix 1** — `ws.ts` reconnect race: cleanup did not clear the pending `setTimeout(open)` so a fresh socket could spawn against a forgotten store after stop. Now captures timer id, clears on cleanup, and re-checks `stopped` at the top of `open()`. Also clamps `retry` variable itself (was clamping only the delay).
- **Review-fix 2** — `extractAmbient` / `applyRetained` dropped the unsafe `as keyof Ambient['modulators']` cast in favor of a `MODULATOR_NAMES` tuple + `isModulatorName` type guard. Unknown modulator names no longer pollute the ambient map. Two regression tests.
- **Review-fix 3** — `rest.ts` error messages now include method, path, status, and statusText for debuggability.

### Task 11 substantive fixes vs. the plan

- **Drift** — `useForceGraph.ts` is the first `d3-force-3d` import. Task 9 had removed the phantom `@types/d3-force-3d` devDep; this task had to create `observatory/web-src/src/types.d.ts`. A bare `declare module 'd3-force-3d';` failed under `strict` because the plan's verbatim code uses typed generic calls (`forceSimulation<ForceNode>(...)`, `forceX<ForceNode>(...)`, `forceLink<ForceNode, ForceLink>(...)`). **Fix:** minimum-typed shim — each imported symbol declared as a generic function returning `any`, and `forceLink<N>()` returns a narrow `ForceLinkChainable<N>` interface so the plan's `.id((d) => d.id)` callback type-checks.
- **Observation** — Plan Step 4 says "cubes gently settle" but `Scene.tsx` has no `useFrame`, so cubes render at their seed positions and don't animate. Task 12+ introduces the per-frame driver. Logged as known mismatch; not fixed here.
- **Review-fix 1** — `useForceGraph` rebuilt the entire d3-force-3d simulation on every render (sim effect dep on `[nodes]` which derived from unstable `names`). Latent perf bug under Task 12+ live traffic. Split into three effects: `[]` builds sim once, `[namesKey]` (stable sorted join) syncs `.nodes(...)` + restarts alpha, `[adjacency]` attaches link force + restarts alpha.
- **Review-fix 2** — `Scene.tsx` now memoizes `names` via `useMemo(() => Object.keys(regions).sort(), [regions])` so its reference is stable when regions identity is stable.
- **Review-fix 3** — Trimmed unused `forceCenter`, `forceCollide`, `forceRadial` from `types.d.ts` (dead declarations in a type-only file are still drift surface).
- **Review-fix 4** — `App.tsx` now documents strict-mode safety: double mount/unmount in dev is absorbed by Task 10's `ws.ts` reconnect guard.

### Task 12 substantive fixes vs. the plan

- **Drift (Scene.tsx)** — Plan's Step 2 Scene.tsx predated Task 11's review-fix memoization. Preserved `useMemo(() => Object.keys(regions).sort(), [regions])` rather than reverting to plan's unmemoized `Object.keys(regions)`.
- **Drift (Regions.tsx)** — Plan's `useStore((s) => Object.keys(s.regions))` allocates a fresh array per read, causing `Regions` to re-render on every store update. Replicated Scene.tsx's pattern: `useStore((s) => s.regions)` + `useMemo(...)`.
- **Review-fix 1 (Critical)** — Torus mesh had no ref, so its position prop was only re-evaluated on React re-render. `useForceGraph` mutates `node.x/y/z` in place without re-rendering, so the torus was stuck while base+halo drifted. Added `torusRef` and mirrored the position-set in `useFrame`.
- **Review-fix 2 (Important)** — `PHASE_COLOR` only covered `sleep|wake|processing|unknown`, but backend `LifecyclePhase` StrEnum emits `bootstrap|wake|sleep|shutdown`. Added `bootstrap` (dim blue-green) and `shutdown` (desaturated red); kept `processing` for a future `llm_in_flight`-derived signal.
- **Review-fix 3 (Important)** — Per-frame `new Color(...)` allocated ~840 instances/sec. Hoisted a module-level `PHASE_COLOR_CACHE` pre-constructed once; `useFrame` now looks up cached Color instances. `.lerp` mutates the target material's color, not the source, so sharing cached colors is safe.

### Task 13 substantive fixes vs. the plan

- **Drift (Sparks.tsx)** — Plan's `new Color(topicColor(e.topic))` per envelope would allocate 50–300 Color instances/sec under live traffic. Added `topicColorObject()` + module-level `COLOR_CACHE` in `topicColors.ts`; Sparks.tsx looks up cached Color instances instead of allocating. Same pattern as Task 12's `PHASE_COLOR_CACHE`.
- **Drift (Sparks.tsx)** — Plan imports `useEffect` but never uses it (would fail `noUnusedLocals` under strict mode). Removed the import. Also removed the unused `dt` parameter from `useFrame((state, dt) => ...)` for the same reason.
- **Review-fix 1 (Important)** — `topicColorObject` returns cached shared Color instances; a future caller mutating them (`.multiplyScalar`, `.lerp`) would corrupt every other spark of that branch. Added JSDoc DO-NOT-MUTATE contract.
- **Review-fix 2 (Suggestion)** — Inline comments in `Sparks.tsx` documenting the freshness-priority cap (`Math.min(newCount, 100)`) and the spawn-time-position snapshot tradeoff (sparks may miss moving targets during settle).
- **Review-fix 3 (Suggestion)** — Added empty-string and uppercase-prefix tests to `topicColors.test.ts` pinning the case-sensitivity contract (13 topicColors tests total).

### Task 14 substantive fixes vs. the plan

- **Drift (Fog.tsx)** — Plan's `new Color(0.03, 0.03, 0.07)` + `bg.clone()` per frame allocated ~120 Color instances/sec. Hoisted base RGB to module constants + single `targetRef` mutated in place (same pattern as Tasks 12/13 caches).
- **Drift (Rhythm.tsx)** — Plan's `useStore((s) => s.envelopes)` reactive subscription re-rendered on every envelope push (~50–100 Hz). Replaced with `useStore.getState()` inside `useFrame` (same pattern as Task 13's Sparks).
- **Drift (Scene.tsx)** — Third time plan code block reverts Task 11's `useMemo` memoization. Preserved.
- **Review-fix 1 (Important)** — `RhythmPulse` never decayed — pulse continued forever once a rhythm topic arrived. Added `ts: performance.now()` capture + `RHYTHM_STALE_MS = 5000` fallback to flat ambient once stale.
- **Review-fix 2 (Important)** — `envelopes.slice(-20)` window hid rhythm under bursts ≥20 non-rhythm envelopes/frame. Replaced with incremental `lastLenRef`-based scan of only-new envelopes (Task 13 Sparks pattern).
- **Review-fix 3 (Suggestion)** — Fog.tsx `Object.entries(mods)` replaced with module-level `MOD_ENTRIES` tuple array; zero allocations per frame.
- **Review-fix 4 (Suggestion)** — `scene.background = target` moved to first-frame only (aliases by reference); inline comment explaining Fog's copy-semantics vs. background's alias-semantics.

### Task 15 substantive fixes vs. the plan

- **Drift (Counters.tsx)** — Plan compared `performance.now()/1000` (browser monotonic, origin = page load) against `observed_at` (Python `time.monotonic()`, origin = Python process start). Cross-process clock-origin mismatch produces garbage rate. Replaced with a monotonic-counter sample ring.
- **Drift (Counters.tsx)** — Plan's `useEffect([envelopes])` re-created the `setInterval` on every envelope push. Fixed to `useEffect([])` with `useStore.getState()` inside the interval.
- **Drift (App.tsx)** — Preserved Task 11's strict-mode-safety comment that plan Step 5 omitted.
- **Review-fix 1 (Important)** — Counters Msg/s read 0.0 during the busiest periods once `envelopes.length` plateaued at `RING_CAP=5000`. Added `envelopesReceivedTotal: number` to the store (monotonic, incremented in `pushEnvelope`, seeded from `s.recent.length` in `applySnapshot`). Counters samples the monotonic counter instead. Regression test pins the contract across RING_CAP (22 frontend tests now).
- **Review-fix 2 (Important)** — Replaced `(a, r: any) => ...` with `(a, r: RegionMeta) => ...` in Counters' reducer. Compile-time guard on `tokens_lifetime` rename.
- **Review-fix 3 (Suggestion)** — Dedup: exported `MODULATOR_NAMES` + `ModulatorName` type from the store; `Modulators.tsx` imports them instead of maintaining a duplicate local `ORDER` tuple.

### Prior session (session 2) substantive fixes vs. the plan

- **Task 2** — real `glia/regions_registry.yaml` schema (dict keyed by name with `layer`/`required_capabilities`) reconciled; plan's list-of-dicts format would have silently returned empty.
- **Task 3** — `Decimator._window_start` anchored to first event (was `0.0` default, caused phantom first window); `drop_count()` split into `drops_in_current_window()` + `total_dropped()`.
- **Task 4** — `_matches` replaced `fnmatch` with proper MQTT regex (`+` is single-level, not cross-segment); `load_subscription_map` fault-tolerant; production envelope `payload.data` unwrap in heartbeat branch; source=None handled.
- **Task 6** — caught latent `_Client` hashability bug (dataclass generates `__eq__` → `__hash__ = None`); added `decimated` WS message per spec §5.3; `_delta_loop` exception guard + non-blocking `put_nowait` so slow clients can't stall others.
- **Task 7** — MQTT task done-callback surfaces broker failures; non-loopback warning via structlog.
- **Task 8** — hand-rolled mosquitto config (testcontainers' default collides on eclipse-mosquitto:2); `retain=True` publish eliminates subscribe/publish race.

## What's next

**v1 is complete and shipped.** All 16 tasks landed with `superpowers:subagent-driven-development` discipline across sessions 2 (backend) and 3 (frontend). Canonical resume prompt for the next phase: `continue observatory v2`.

**Prereq for v2:** short brainstorming session per plan §Self-Review — spec §5.1 (region inspector details) needs refinement around panel layout, keyboard shortcuts, and handler-source deferrals before `writing-plans` runs.

### Visual-E2E punch list — deferred to Larry

Plan Step 3 requires a real browser + live Hive broker. The Task 16 implementer environment had neither. Once you're at a workstation with both:

1. `cd observatory/web-src && npm run build && cd ../..`
2. Start Hive regions (or publish test envelopes to your broker manually).
3. `OBSERVATORY_MQTT_URL=mqtt://<your-broker>:1883 .venv/Scripts/python.exe -m observatory`
4. Open `http://127.0.0.1:8765` in a browser and confirm:
   - Force-directed scene renders; 14 region spheres settle into positions.
   - Sphere **base colors** shift with lifecycle phase (bootstrap/wake/sleep/shutdown).
   - **Halos** brighten during LLM activity (`llm_in_flight` or token-rate surges).
   - **Sparks** travel along adjacency edges with topic-branch colors.
   - **Modulator gauges** update as regions publish `hive/modulator/*`.
   - **Self panel** reflects `hive/self/*` retained state.
   - **Bottom strip counters** tick (Msg/s, region count, token total).
5. Note any visual regressions in a new HANDOFF changelog entry and decide whether they're v1.1 polish or v2 scope.

## Follow-ups / open threads

- **Plan-code drift** (25+ documented deviations in `decisions.md`): Plan's verbatim code blocks repeatedly fail ruff (UP037, UP035, PLR2004, B007, I001), sometimes have correctness bugs (fnmatch MQTT wildcards, `_Client` hashability, YAML schema), and on the frontend side — omit the `@types/node` devDep required by Vite 5, include a phantom `@types/d3-force-3d` package, miss `noEmit: true` needed to suppress `tsc -b` residue, mis-suggest `npx tsc -b --noEmit` as a verification gate (incompatible with `composite: true` refs), and in Task 11 add a latent perf bug (sim rebuilt on every render due to unstable `names` reference — fixed in review). Fix-loop catches them consistently, but a v1.1 plan-prose pass could save future implementers the re-discovery cost.
- **`d3-force-3d` typing lives at `observatory/web-src/src/types.d.ts`** — minimum-typed ambient shim. Swap for a real DefinitelyTyped package if one ever ships. Task 12+ additions go in the same file with the same pattern.
- **`useFrame` deferred to Task 12.** Task 11's static cube field doesn't animate; decision entry 58 is the breadcrumb.
- **`ws.ts` reconnect-race regression test.** Task 10 fixed the race but did not add a test (needs `WebSocket` mock + fake timers — larger than a review-fix). Fold into Task 16 CI wiring.
- **`rest.ts` error test.** Same class — needs `vi.stubGlobal('fetch', ...)`. Fold into Task 16.
- **npm audit** — 4 moderate warnings in the Task 9 install (all transitive). Deferred until Task 16 final polish / CI setup.
- **`RegionMeta.llm_model` is always empty** against production YAML (real schema has no per-region model). Revisit when/if the HUD needs to display model identity.
- **Decimator priority hooks** (`_LOW_PRIORITY_PREFIXES`, `_is_low_priority`) are unused in v1 by design — wiring v1.1 priority-aware drops is a one-line change at `should_keep`'s over-budget branch.
- **Task 8 hang risk** — `ws.receive_json()` blocks forever if the delta loop dies AND the envelope never arrives. Mitigated by Task 6's `_delta_loop` exception guard; proper test-level timeout deferred to Task 9 CI wiring where `pytest-timeout` could be added as a project dep.
- **TLS for mqtts://** — `mqtts://` URLs parse correctly but `aiomqtt.Client` is constructed without TLS. Currently logs `observatory.mqtts_scheme_no_tls` warning. Full TLS wiring (tls_params, CA bundle, cert pinning) is a v1.1 follow-up.
- **Mosquitto default config upstream PR** — testcontainers[mqtt]'s default config collides on eclipse-mosquitto:2; consider filing a PR upstream with a fix. Our workaround is a hand-rolled minimal config in `observatory/tests/component/test_end_to_end.py`.

## Changelog

| Date | Change |
|---|---|
| 2026-04-20 | Initial handoff — spec + CLAUDE.md + HANDOFF.md created. |
| 2026-04-20 | Session 2: Tasks 1–3 complete + review-fixes; 31 unit tests passing; next is Task 4 (MQTT subscriber). |
| 2026-04-20 | Session 2 checkpoint 2: Tasks 4–6 complete + review-fixes; 57 unit tests passing; next is Task 7 (service assembly). |
| 2026-04-20 | Session 2 v1-backend-complete: Tasks 7–8 complete + review-fixes; 67 unit + 1 component test passing; end-to-end MQTT publish → WS receive verified against a real `eclipse-mosquitto:2` broker. Next is Task 9 (frontend scaffolding). |
| 2026-04-21 | Session 3: Task 9 complete + review-fix. Vite 5 + React 18 + TypeScript 5 + Tailwind 3 scaffolded under `observatory/web-src/`; `npm run build` produces `observatory/web/index.html` + assets in ~800 ms. Three plan-code drifts resolved (@types/d3-force-3d phantom, @types/node omission, tsconfig noEmit residue). Python suite still 67 unit + 1 component passing, ruff clean. Next is Task 10 (WS client + REST client + zustand store). |
| 2026-04-21 | Session 3 continued: Task 10 complete + review-fix. Zustand store + WS client (5 message types, auto-reconnect) + REST wrappers. TDD discipline: red-phase for both `store.test.ts` and `ws.test.ts` captured. 8 frontend tests passing (5 store + 3 ws). Review-fix addressed 3 Important findings: WS reconnect race on stop, unsafe modulator name cast (now type-guarded), opaque REST error messages. Python suite still 67 unit + 1 component passing. Next is Task 11 (scene shell + force graph — first `d3-force-3d` import; create `src/types.d.ts`). |
| 2026-04-21 | Session 3 continued: Task 11 complete + review-fix. `<Canvas>` + orbit controls + lights + `useForceGraph` hook. First `d3-force-3d` import — `src/types.d.ts` seeded with minimum-typed shim. Review-fix addressed 2 Important findings: sim rebuilt on every render (unstable `names` → sim-build effect churn) — split into stable single-build + sync-on-namesKey. Also: trim unused shim declarations, strict-mode safety comment in `App.tsx`. Python suite still 67 unit + 1 component passing; 8 frontend tests green; `tsc -b` + `vite build` clean. Next is Task 12 (region meshes + `useFrame`). |
| 2026-04-21 | Session 3 continued: Task 12 complete + review-fix. Region meshes (base sphere + halo + handler torus) with `useFrame`-driven color/halo/scale. First `useFrame` usage in the project. Pre-approved plan deviations: preserved Task 11's `useMemo` in Scene.tsx and applied the same pattern to Regions.tsx (plan's `useStore((s) => Object.keys(s.regions))` would cause re-renders on every envelope push). Review-fix addressed 1 Critical + 2 Important: torus stationary (no ref), `PHASE_COLOR` missing `bootstrap`/`shutdown` (backend emits these), and per-frame `new Color()` allocation hoisted to module-level cache. Python suite still 67 unit + 1 component passing; 8 frontend tests green. Next is Task 13 (sparks — traveling particles on edges). |
| 2026-04-21 | Session 3 continued: Task 13 complete + review-fix. Traveling sparks via `InstancedMesh` (cap 2000, 800 ms lifetime) colored by topic-prefix mapper (pure, unit-tested, TDD red-phase captured). First InstancedMesh use in the project. Pre-approved drifts: added `topicColorObject()` + module-level `COLOR_CACHE` to avoid ~50–300 `new Color()` allocations/sec under live traffic (same pattern as Task 12's `PHASE_COLOR_CACHE`); removed plan's dead `useEffect` import + unused `dt` param. Review-fix addressed 1 Important: JSDoc DO-NOT-MUTATE on cached Color return. Plus two suggestion-level comment additions and two test additions (empty-string, case-sensitivity). 21 frontend tests (was 8); Python suite 67 unit + 1 component untouched. Next is Task 14 (modulator fog + rhythm pulse). |
| 2026-04-21 | Session 3 continued: Task 14 complete + review-fix. Scene-wide ambient channels: `ModulatorFog` tints scene.fog + scene.background from weighted modulator values; `RhythmPulse` modulates ambient-light intensity at perceptually-scaled gamma/beta/theta tempo. Pre-approved drifts: Fog.tsx hoisted BG constants + reusable targetRef (no per-frame Color alloc); Rhythm.tsx uses `useStore.getState()` non-reactively; Scene.tsx `useMemo` preserved (3rd time plan reverts it). Review-fix addressed 2 Important: rhythm pulse now decays after 5s staleness; scan window replaced with incremental lastLenRef-based scan (same as Sparks). Plus Fog's MOD_ENTRIES tuple table + scene.background moved to first-frame-only. 21 frontend tests unchanged; Python suite 67 unit + 1 component untouched. Next is Task 15 (HUD — self panel + modulators + counters). |
| 2026-04-21 | Session 3 continued: Task 15 complete + review-fix. HUD (SelfPanel / Modulators / Counters) rendered as DOM overlay above `<Canvas>` via Tailwind. Pre-approved drifts: Counters.tsx avoids cross-process clock-origin bug (plan compared `performance.now()/1000` to server-side `observed_at` = `time.monotonic()`) + `useEffect([])` instead of `[envelopes]`; App.tsx preserves Task 11's strict-mode comment. Review-fix addressed 2 Important + 1 Suggestion: added `envelopesReceivedTotal` monotonic counter to the store so Counters no longer reads 0.0 msg/s when the envelope ring plateaus at RING_CAP; typed Counters reducer accumulator as `RegionMeta` (was `any`); exported `MODULATOR_NAMES` from the store + deduped `Modulators.tsx`. 22 frontend tests (was 21, +1 regression); Python suite 67 unit + 1 component untouched. Next is Task 16 (final integration + production build + static mount smoke test). |
| 2026-04-21 | Session 3 complete: Task 16 ships v1. All 16 tasks + review-fixes landed. Total session-3 commits: 8 task commits + 7 review-fix commits + HANDOFF bumps. Canonical resume prompt pivoted to v2. |
