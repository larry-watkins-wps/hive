# Observatory — Session Handoff

*Last updated: 2026-04-21 (session 3, Tasks 9 + 10 + 11 complete)*

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
| v1 Task 12 — Region rendering (phase color + halo + size + ring) | ⏳ Next | |
| v1 Tasks 13–16 — sparks + HUD + retain/ambient surfacing + integration | ⏳ Pending | |
| v2 implementation | ⏳ Pending | |
| v3 implementation | ⏳ Pending | |

## Suite + lint snapshot

- `python -m pytest observatory/tests/unit/ -q` → **67 passed** (ring buffer 5 + config 4 + retained cache 4 + region registry 7 + adjacency 4 + decimator 7 + MQTT subscriber 16 + api 2 + ws 8 + service 10)
- `python -m pytest observatory/tests/component/ -m component -v` → **1 passed** (requires Docker Desktop; `eclipse-mosquitto:2` via testcontainers; real MQTT publish → WS receive verified)
- `python -m ruff check observatory/` → clean
- Smoke test: `python -c "from observatory.config import Settings; from observatory.service import build_app; build_app(Settings())"` → `ok`
- Smoke-verified against production `glia/regions_registry.yaml`: 19 regions load correctly (`layer` → `role` mapping).
- Frontend: `cd observatory/web-src && npm run build` → `observatory/web/index.html` + `assets/index-*.{js,css}` emitted in ~800 ms.
- Frontend: `cd observatory/web-src && npm run test` → **8 passed** (5 store + 3 ws). Typecheck via `npx tsc -b` clean.
- Frontend: `cd observatory/web-src && npm run build` → `observatory/web/` emitted; bundle ~991 kB (three.js + drei + fiber + d3-force-3d); chunk-size warning expected, Task 16 polish.

## What's done (session 3)

Executed **Tasks 9 + 10 + 11** with `superpowers:subagent-driven-development` discipline: fresh implementer per task, two-stage review (spec-compliance + code-quality) after each, review-fix commit on top of each. Implementer prompts stored under `observatory/prompts/` (`task-09-frontend-scaffolding.md`, `task-10-ws-rest-store.md`, `task-11-scene-force-graph.md`). Non-obvious calls logged in `observatory/memory/decisions.md` (entries 46–62).

**Session 3 totals: 3 task commits (`8b6be24`, `4cd41aa`, `b188dcd`) + 3 review-fix commits (`fc0ce94`, `efb8397`, `d614a48`) + HANDOFF bumps.**

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

### Prior session (session 2) substantive fixes vs. the plan

- **Task 2** — real `glia/regions_registry.yaml` schema (dict keyed by name with `layer`/`required_capabilities`) reconciled; plan's list-of-dicts format would have silently returned empty.
- **Task 3** — `Decimator._window_start` anchored to first event (was `0.0` default, caused phantom first window); `drop_count()` split into `drops_in_current_window()` + `total_dropped()`.
- **Task 4** — `_matches` replaced `fnmatch` with proper MQTT regex (`+` is single-level, not cross-segment); `load_subscription_map` fault-tolerant; production envelope `payload.data` unwrap in heartbeat branch; source=None handled.
- **Task 6** — caught latent `_Client` hashability bug (dataclass generates `__eq__` → `__hash__ = None`); added `decimated` WS message per spec §5.3; `_delta_loop` exception guard + non-blocking `put_nowait` so slow clients can't stall others.
- **Task 7** — MQTT task done-callback surfaces broker failures; non-loopback warning via structlog.
- **Task 8** — hand-rolled mosquitto config (testcontainers' default collides on eclipse-mosquitto:2); `retain=True` publish eliminates subscribe/publish race.

## What's next

**Task 12: Region rendering — phase color + halo + size + ring.** Replaces Task 11's placeholder cubes with real region meshes: base sphere colored by `stats.phase`, emissive halo scaling with rolling token burn rate, slight size scaling from queue depth, and a thin torus for handler count.

- Plan: search `### Task 12:` in `observatory/docs/plans/2026-04-20-observatory-plan.md` (~line 2534).
- **Critical:** Task 12 is where `useFrame` (or an imperative ref-based position sync) has to land so cubes/meshes actually track the d3-force-3d simulation per frame. See decision entry 58 (Task 11 `useFrame` observation). The Task 11 fix-loop already ensured `useForceGraph` keeps a single long-lived sim across renders, so Task 12 can safely subscribe to tick updates.
- Gotchas to carry forward:
  - Delete the placeholder-cube block in `Scene.tsx` (lines 12–23 region). The plan's `Scene.tsx` comment `// (Remove this block when Task 12 lands.)` is the marker.
  - `regions` identity is now stable across unrelated renders (Task 11 review-fix #2 depends on it). Don't destructure in ways that force new references.
  - `stats.phase` is a `string` on the store — Task 12 will want a typed mapping from phase → color (spec §4.2 has the palette).
  - `@react-three/fiber`'s JSX augmentation resolved first-try in Task 11; no `compilerOptions.types` workaround needed.
  - `d3-force-3d` shim is minimum-typed — if Task 12 imports `forceCollide` (to stop spheres overlapping) or `forceCenter`, re-add the declaration to `types.d.ts` with the same pattern (generic returning `any`).
  - If Task 12 adds component-level tests, switch `vitest.config.ts` to `environment: 'jsdom'` and add `@testing-library/react` + `jsdom` devDeps (don't do this preemptively — only when a test actually needs DOM globals).

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
