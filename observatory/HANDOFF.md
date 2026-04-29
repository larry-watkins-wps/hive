# Observatory — Session Handoff

*Last updated: 2026-04-29 (session 8 — v4 session 1: backend + proposals landed)*

**Canonical resume prompt:** `continue observatory v4 — session 2`

---

## State snapshot

| Milestone | Status | Notes |
|---|---|---|
| v1 — SHIPPED | ✅ | All 16 tasks landed across sessions 2–3. See prior snapshot in git history. |
| v2 brainstorm | ✅ Complete | 2026-04-21 — visual-companion mockups (layout A, keyboard A, handler-tree-only, reactive threads, name-always/stats-on-hover labels, fuzzy orbs) |
| v2 spec written | ✅ Complete | `observatory/docs/specs/2026-04-21-observatory-v2-design.md` · commit `9cd4677` |
| v2 plan written | ✅ Complete | `observatory/docs/plans/2026-04-21-observatory-v2-plan.md` (15 tasks, 3209 lines) · commit `1143258` |
| v2 Task 1 — sandbox foundation (SandboxError, HandlerEntry, RegionReader skeleton, read_prompt, config) | ✅ Complete | `3fde4f7` + review-fix `28b751c` |
| v2 Task 2 — read_stm + read_subscriptions + 7 boundary tests + `_deny` helper | ✅ Complete | `b9c971a` + review-fix `e1c2c74` |
| v2 Task 3 — read_config (recursive redaction) + list_handlers (Path.walk follow_symlinks=false) | ✅ Complete | `90852d5` + review-fix `53f92a9` |
| v2 Task 4 — 5 REST routes + flat `{error,message}` body + Cache-Control no-store on all | ✅ Complete | `66394e3` + review-fix `da6624f` |
| v2 Task 5 — component e2e extension (seeded regions, /config redaction + /handlers tree over real broker) | ✅ Complete | `1bbed83` + review-fix `b026b3d` |
| **v2 backend — complete, 92 unit + 2 component tests passing** | ✅ | |
| v2 Task 6 — frontend store: selectedRegion + select + cycle | ✅ Complete | `6ea8939` (no review-fix) |
| v2 Task 7 — REST wrappers (5 fetchers) + useRegionFetch hook + jsdom env | ✅ Complete | `b501fec` (no review-fix) |
| v2 Task 8 — OrbitControls → drei CameraControls + dim plumbing + camera-reset event | ✅ Complete | `f6653a1` + review-fixes `bdf652d`, `bf8377f` |
| v2 Task 9 — FuzzyOrbs (5-mesh additive-glow groups) + glowTexture + deletes Regions.tsx | ✅ Complete | `cce9149` + review-fix `f03493d` |
| v2 Task 10 — Labels (CSS2DRenderer, name always / stats on hover, hover raycaster) | ✅ Complete | `528ee1c` + review-fix `955d75f` |
| v2 Task 11 — Edges (reactive adjacency threads) + Sparks EDGE_PULSE bump | ✅ Complete | `59ccaaa` + review-fix `de5ec6c` |
| v2 Task 12 — Inspector shell + useInspectorKeys + Header/Stats/ModulatorBath/Subscriptions/Handlers sections | ✅ Complete | `8002732` + review-fix `1fc7a1f` (slide-out animation + Stats dedup + shutdown badge) |
| v2 Task 13 — Prompt + STM + JsonTree sections | ✅ Complete | `10b90c0` + review-fix `a98a39e` (skip first-render refetch + JsonTree escaping) |
| v2 Task 14 — Messages section (filter + auto-scroll + row expand) | ✅ Complete | `6a8df79` (no review-fix; APPROVED with Suggestions only) |
| v2 Task 15 — integration + verification + HANDOFF closure | ✅ Complete | this commit |
| **v2 — SHIPPED** | ✅ | |
| v3 brainstorm | ✅ Complete | 2026-04-22 — visual-companion mockups (layout A bottom dock, collapsible/resizable, 3D scene primary, click-region-popup) |
| v3 spec written | ✅ Complete | `observatory/docs/specs/2026-04-22-observatory-v3-design.md` · commit `7d5762e` |
| v3 plan written | ✅ Complete | `observatory/docs/plans/2026-04-22-observatory-v3-plan.md` (11 tasks) · commit `7813c92` |
| v3 Task 1 — /appendix route | ✅ Complete | `a2da75f` + review-fix `ac3f76a` (spec §9.2 404 body; str \| None + `appendix_missing` kind + `SandboxError.reason`) |
| v3 Task 2 — store dock + self-retained | ✅ Complete | `5c6124d` + doc-fix `bc7bc7a` (dock state + pendingEnvelopeKey + 4 hive/self/* topics; SelfPanel Option-C trim) |
| v3 Task 3 — REST + hook + parseAppendix | ✅ Complete | `5d22c27` (no review-fix; APPROVED with 3 Suggestions) |
| v3 Task 4 — dock shell + keys + persistence | ✅ Complete | `00920ba` + review-fix `a547771` (subscribeWithSelector middleware + selector-scoped subscribe) |
| v3 Task 5 — Firehose tab + kindTag | ✅ Complete | `150c634` + review-fix `76a69e4` (single-line row + h-[22px] + 18ch ellipsis + JSON undefined guard + expand test) |
| v3 Task 6 — Topics tab + useTopicStats | ✅ Complete | `8a45ba7` + review-fix `09e3e50` (10-s buckets per spec §6.1 + kind column removal + sort/expand tests) |
| v3 Task 7 — Metacognition tab + badge | ✅ Complete | `8e32ed0` + review-fix `29c3f27` (useMemo rows filter) |
| v3 Task 8 — inspector Appendix section + Prompt relabel | ✅ Complete | `e9e2892` + review-fix `00c419d` (N entries count in summary label) |
| v3 Task 9 — HUD SystemMetrics + SelfState replacement | ✅ Complete | `7d7a03a` + review-fix `b46c795` (tab "Autobio"→"Index" + tooltip status field + autobio newest-first sort + Modulators mt-2 cleanup) |
| v3 Task 10 — Messages JsonTree expand + pendingEnvelopeKey | ✅ Complete | `abd8556` + review-fix `f12221d` (pendingEnvelopeKey mount race — filtered in dep array) |
| v3 Task 11 — integration + verification + HANDOFF closure | ✅ Complete | this commit (component E2E /appendix test + HANDOFF bump) |
| **v3 — SHIPPED** | ✅ | 11 tasks + 9 review-fix commits + 1 doc-fix + 1 ship commit |
| v4 spec written | ✅ Complete | `observatory/docs/specs/2026-04-29-observatory-v4-chat-design.md` · commit `5144d97` (sensory bridge + floating overlay) |
| v4 plan written | ✅ Complete | `observatory/docs/plans/2026-04-29-observatory-v4-plan.md` (13 tasks) · commit `2d37be7` |
| v4 Task 1 — sensory module skeleton + Settings chat fields | ✅ Complete | `370db6f` (no review-fix; APPROVED both stages with Suggestions) |
| v4 Task 2 — SensoryPublisher (aiomqtt + allowlist + lifecycle) | ✅ Complete | `473dd30` (no review-fix; APPROVED both stages with Suggestions) |
| v4 Task 3 — POST /sensory/text/in route + service.py wiring | ✅ Complete | `cef8728` (no review-fix; APPROVED both stages — pre-approved JSONResponse drift for stand-alone test contract; module-level Depends singletons for B008) |
| v4 Task 4 — component test: POST → real broker round-trip | ✅ Complete | `f4f3558` (no review-fix; APPROVED both stages; full component suite 4 passed; round-trip verified < 500 ms over real testcontainers `eclipse-mosquitto:2`) |
| v4 Task 5 — code-change proposal artifacts (assoc_cortex sub + broca payload) | ✅ Complete | `1c0084b` — two inert YAML payloads under `observatory/docs/proposals/`; verbatim from spec §5.1/§5.2; YAML round-trip parsed; review pair skipped (no logic to review) |
| **v4 backend + proposals — complete, 13 unit (sensory) + 1 component (round-trip) tests passing** | ✅ | session 1 of 3 |
| v4 Task 6 — frontend store extension + chat persistence | ⏳ Pending | session 2 |
| v4 Task 7 — frontend api.ts (POST wrapper) | ⏳ Pending | session 2 |
| v4 Task 8 — Transcript + TranscriptTurn | ⏳ Pending | session 2 |
| v4 Task 9 — ChatInput | ⏳ Pending | session 2 |
| v4 Task 10 — ChatOverlay (frame + drag + resize) | ⏳ Pending | session 3 |
| v4 Task 11 — useChatKeys hotkey | ⏳ Pending | session 3 |
| v4 Task 12 — App.tsx mount + production build | ⏳ Pending | session 3 |
| v4 Task 13 — verification + HANDOFF closure (v4 ships) | ⏳ Pending | session 3 |

## Suite + lint snapshot (end of session 8 — v4 session 1)

- `python -m pytest observatory/tests/unit/sensory/ -q` → **15 passed** (Task 1: 4 + Task 2: 4 + Task 3: 7).
- `python -m pytest observatory/tests/unit/ -q` → **133 passed + 2 skipped + 3 failed**. The 3 failures are pre-existing in `observatory/tests/unit/test_mqtt_reconnect.py::TestReconnectLoop` (introduced by `83b0bd3`'s stall watchdog: `_FakeSubscriber` lacks `messages_received_total`); orthogonal to v4 — see decisions.md 2026-04-29.
- `python -m pytest observatory/tests/component/ -m component -v` → **4 passed** (3 existing v1/v2/v3 + 1 new v4 round-trip; full suite 1.57 s end-to-end including broker boot via `eclipse-mosquitto:2`).
- `python -m ruff check observatory/sensory/ observatory/config.py observatory/tests/unit/sensory/ observatory/tests/component/test_end_to_end.py` → **clean**. (`observatory/service.py` carries one pre-existing `F401: RingRecord` import — predates v4; out of scope.)
- Frontend: not modified in session 1; v3 baseline (168 vitest + 1.08 MB JS bundle) unchanged.

## Suite + lint snapshot (end of session 7 — v3 ship)

- `python -m pytest observatory/tests/unit/ -q` → **99 passed + 2 skipped** (+7 v3: 4 reader_appendix + 3 api_appendix)
- `python -m pytest observatory/tests/component/ -m component -v` → **3 passed** (v1 MQTT publish → WS receive + v2 `/config` redaction + `/handlers` tree + v3 `/appendix` happy-path + 404 body via seeded temp regions dir + real broker via testcontainers `eclipse-mosquitto:2`)
- `python -m ruff check observatory/` → clean
- Frontend: `cd observatory/web-src && npx vitest run` → **168 passed** across 25 test files (was 84 pre-v3, +84 new — store 14, ws 3, topicColors 34 (13 topicColor + 18 kindTag + 3 new), rest 16, useRegionFetch 9, FuzzyOrbs 4, Labels 6, Edges 7, Header 3, Stats 4, Inspector 3, Stm 3, Messages 8 (was 3, +5), parseAppendix 6, useRegionAppendix 4, Dock frame 3, useDockPersistence 4, selectRegionFromRow 3, Firehose 6 (4+2), Topics 4 (2+2 sort/expand), useTopicStats 4 (3+1 roll), Metacog 2, SystemMetrics 4, SelfState 4 (3+1 autobio sort), Appendix 4)
- Frontend: `npx tsc -b` → clean; `npm run build` → `observatory/web/index.html` + `assets/index-*.{css,js}` emitted (~1.08 MB JS, 16.4 kB CSS; chunk-size warning pre-existing from v1).

## Next session resume protocol

1. **v4 session 1 (backend + proposals) is complete.** Canonical resume prompt: `continue observatory v4 — session 2`. Session 2 covers Tasks 6–9 (frontend store extension + chat persistence + REST wrapper + Transcript/TranscriptTurn + ChatInput). Session 3 covers Tasks 10–13 (ChatOverlay + hotkey + App.tsx mount + verification/ship).
2. `git log --oneline observatory/` shows the v4 session-1 task commits `370db6f` → `1c0084b` on top of the v3 ship history.
3. **v4 session-2 starting state:**
   - Backend POST `/sensory/text/in` is fully wired (Task 3 commit `cef8728`).
   - SensoryPublisher connects to MQTT in the FastAPI lifespan; allowlist is `frozenset({"hive/external/perception"})`.
   - `Settings` carries `chat_default_speaker` (default `"Larry"`), `chat_publish_qos` (default `1`), `chat_text_max_length` (default `4000`).
   - Component test pins the round-trip < 500 ms against a real `eclipse-mosquitto:2` testcontainer.
   - Two inert proposal YAMLs under `observatory/docs/proposals/` await Larry's cosign before regions react to chat input.
4. **v4 session-2 entry checklist:**
   - Read `observatory/docs/specs/2026-04-29-observatory-v4-chat-design.md` §6 (frontend chat surface) end-to-end. The §6.5 dedupe rule (envelope `id` round-trip) and §6.6 hotkey rules are the trickiest specifications.
   - Read the v4 plan's Tasks 6–9 blocks (lines 1070–2170 of the plan).
   - Run `PYTHONPATH=./src python -m pytest observatory/tests/unit/sensory/ -q` and `python -m pytest observatory/tests/component/ -m component -v` to confirm session-1 contracts are still green.
   - The frontend has not been modified in v4 yet; v3 vitest suite remains 168 passed.
5. **v4 session-1 deferrals (`observatory/memory/decisions.md` 2026-04-29):**
   - JSONResponse drift correction for route 5xx body shape (already applied; documented).
   - B008 module-level Depends hoist (`_PUBLISHER_DEP`/`_SETTINGS_DEP`); applies to future routes.
   - 422 `RequestValidationError` path does not attach `Cache-Control: no-store` globally — no current test asserts it; revisit if a future spec section does.
   - Code-quality reviewer's debuggability suggestions on the Task 4 component test (capture-thread exception forwarding, `pytest.fail` on queue empty, tighten `elapsed` window inside the `with` block) — non-blocking; defer.
6. **v3 post-ship checklist Larry may want to address in v4 or earlier:**
   - **Scene outline ring on Topics row click** — spec §6.1 line 171 / §8 lines 231-233. Deferred from Task 6 (requires scene-level state + FuzzyOrbs outline mesh + 15 s decay timer). Decisions.md entry logs the scope split.
   - **SystemMetrics tooltip `last-hb HH:MM:SS`** — spec §10.1 line 312 references a field that `glia/metrics.py::build_region_health_payload` doesn't currently emit. Either spec amends or glia extends. Decisions.md entry logged.
   - **Identity render as key-value when dict-shaped** — spec §10.2 line 324 "key-value list of payload's top-level string/number fields". Current Hive publishes `{"value": "<text>"}` which the store coerces to a bare string; SelfState renders as paragraph. Object-shaped identity WOULD render as key-value correctly via the existing object branch.
   - **§5.3 kind-tag color column** — spec table lists colors for all 17 prefixes as if they were badge backgrounds, but the Firehose badge uses a fixed neutral background (`bg-[rgba(255,255,255,.05)]`). Task 5 review arbitrated this as a spec ambiguity pending Larry's call on whether the color column is scene palette (current interpretation) or badge backgrounds (would need a second coloring pass).
4. **Visual-E2E punch list** — deferred to Larry's human-loop review:
   - Dock: collapse/expand via backtick, drag-resize with clamp, localStorage round-trip.
   - Firehose: filter regex + substring, pause snapshot, row expand JsonTree.
   - Topics: sort by rate desc, sparkline rolls every 10 s, row expand into recent 5, click picks most-recent publisher.
   - Metacog: left-border kind coloring, badge severity (red/amber/grey) at 1 Hz, click-through sets pendingEnvelopeKey → Messages scroll + expand.
   - Appendix: entries newest-first, 360 px max-height, empty state on fresh regions, reload button.
   - HUD: SystemMetrics renders from retained topics, region-health heatmap colors correct, SelfState tab switching, tabs hide missing data with empty-state copy.
   - Messages: chevron expand, pendingEnvelopeKey scrolls + expands the target row, auto-scroll-to-bottom still works for new envelopes, follow-tail yields to pendingKey scroll.
5. Authoritative references:
   - v4 spec: [observatory/docs/specs/2026-04-29-observatory-v4-chat-design.md](docs/specs/2026-04-29-observatory-v4-chat-design.md)
   - v4 plan: [observatory/docs/plans/2026-04-29-observatory-v4-plan.md](docs/plans/2026-04-29-observatory-v4-plan.md)
   - v3 spec: [observatory/docs/specs/2026-04-22-observatory-v3-design.md](docs/specs/2026-04-22-observatory-v3-design.md)
   - v3 plan: [observatory/docs/plans/2026-04-22-observatory-v3-plan.md](docs/plans/2026-04-22-observatory-v3-plan.md)
   - Project CLAUDE.md: [observatory/CLAUDE.md](CLAUDE.md)

## v1 legacy suite snapshot (session 3 baseline, unchanged)

- `python -m pytest observatory/tests/unit/ -q` → 67 passed
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

### v2 Task 12 review-fix (session 5 — reviews were deferred from session 4)

- **Spec-review Important §1** — Inspector slide-out had nothing to animate. Children were gated on `open` and unmounted synchronously on deselect, so the 300 ms `translate-x-full` transition ran against an already-empty panel. Added a `displayName` state held for 300 ms via `useEffect` + timer so the panel slides out with content still visible.
- **Code-review Important §1** — `useStatsHistory` subscribed to the whole store, firing on every `pushEnvelope` tick. Sparkline was sampling envelope rate instead of heartbeat rate. Fixed with tail-compare dedup (identical `queue_depth`/`stm_bytes`/`tokens_lifetime` returns prior ref so React bails out).
- **Suggestion** — `PhaseBadge` gained a `shutdown` branch (dim red) to match the v1 scene label enumeration.
- **Suggestion** — `fmtBytes` lifted to `inspector/format.ts`; `Stats` + `Handlers` now import the shared helper instead of diverging (`16kB` vs `12.3 kB`).
- **Regression tests** — `Inspector.test.tsx` (3 fake-timer-based tests) pins the slide-out window; `Stats.test.tsx` (4 tests) pins the dedup + change paths.

### v2 Task 13 substantive fixes vs. the plan (session 5)

- **Drift (test imports)** — `vitest.config.ts` has `globals: false`; plan's `Stm.test.tsx` used `beforeEach` without importing it. Added `beforeEach` + `afterEach` + `cleanup` to the imports to match the house pattern.
- **Drift (reload button)** — Plan's reload button only did `e.preventDefault()`. Added `e.stopPropagation()` to match `Handlers.tsx` convention, avoiding the "one click reloads then collapses the section" bug.
- **Drift (size label)** — Used `fmtBytes(data.length)` instead of plan's inline `(data.length/1024).toFixed(1) + ' kB'` for consistency with `Handlers` + `Stats`.
- **Drift (JsonTree cast)** — `JsonValue` exported as a named type from `JsonTree.tsx`; `Stm.tsx` casts `data as JsonValue` at the single call site rather than widening `JsonTree` to `unknown`.
- **Drift (404 handling)** — Backend 404 on missing `prompt.md` surfaces as red "Failed:" rather than the "No `prompt.md` in this region." empty-state copy. Acceptable — empty-state copy fires on `!error && !data`, which is correct for an empty-file case.
- **Review-fix 1 (Important)** — Auto-refetch `useEffect` fired on mount because `stats` was already populated by the store, so `reload()` kicked a second fetch back-to-back with `useRegionFetch`'s name-change mount fetch. Added `firstRef` sentinel to skip the mount tick in both `Prompt.tsx` and `Stm.tsx`. Net: one fetch per selection, not two.
- **Review-fix 2 (Important)** — `Stm.test.tsx` used `waitFor + getByText` where `findByText` is idiomatic. Swapped.
- **Review-fix 3 (Suggestion)** — `JsonTree` rendered string values as `<span>"{value}"</span>`, which doesn't escape embedded quotes/backslashes. Replaced with `JSON.stringify(value)` so `{"msg": "she said \"hi\""}` displays correctly.

### v2 Task 14 substantive fixes vs. the plan (session 5)

- **Drift (IMPORTANT, incremental scan)** — Plan's `lastLenRef` + `env.length` gating misses every envelope after the ring caps at `RING_CAP=5000`: once `length` plateaus, `startIdx = last = ringLen` and the scan loop never executes. Same class of bug v1 Counters hit under its own length-plateau, fixed there by adding monotonic `envelopesReceivedTotal` to the store. Task 14 uses the same precedent: `lastTotalRef` gates on `s.envelopesReceivedTotal - lastTotalRef.current`, then reads the last `take = min(delta, ring.length)` envelopes at the tail. Correct under saturation.
- **Drift (IMPORTANT, expand-state key)** — Plan keyed both `expanded: Set<number>` and React row `key=` on the filtered-array index `i`. When new rows land and `.slice(-MAX_ROWS)` drops the oldest, indices shift down — expanded Set now holds stale indices pointing to different envelopes. Swapped both to `` `${e.observed_at}|${e.topic}` `` stable identity.
- **Drift (test cleanup)** — `vitest.config.ts` has `globals: false`, so no auto-cleanup between tests. Rendered DOM from the first test persisted into the second, breaking the direction-count assertion. Added `afterEach(() => cleanup())` mirroring sibling `Stm.test.tsx`.
- **Drift (`if/else`)** — Plan's ternary `n.has(i) ? n.delete(i) : n.add(i)` trips `no-unused-expressions`; rewrote as `if (n.has(id)) n.delete(id); else n.add(id);`.
- **Code-review result** — Two APPROVED rounds: spec-compliance (no violations; `lastLenRef → lastTotalRef` documented as reviewer-approved implementation choice) and code-quality (3 Suggestion-only findings, all non-blocking: seed-vs-subscribe race window note, optional `data-testid` instead of CSS-escape querySelector, optional follow-up if `observed_at|topic` ever collides under sub-second duplicates).

### v2 Task 15 substantive fixes vs. the plan (session 5)

- **No-op for production code.** Task 15 is pure verification + HANDOFF closure; no files under `observatory/web-src/` or `observatory/` backend were modified.
- **Smoke test (Plan Step 4) deferred to Larry's human-loop review** — same pattern as v1 Task 16. The automated suite cannot exercise `<Canvas>` / CameraControls / CSS2DRenderer in jsdom, and running the service against a live broker requires Larry's workstation. All v2 backend contracts are pinned by the 92-unit + 2-component suite; inspector sections are pinned by the 84-test frontend vitest suite.

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
| 2026-04-22 | Session 5 ships v2. Opened with the deferred Task 12 reviews (review-fix `1fc7a1f`): slide-out animation via a 300 ms `displayName` hold, `useStatsHistory` tail-compare dedup so sparklines sample heartbeats not envelopes, `shutdown` phase badge branch, shared `fmtBytes` helper. Then Tasks 13 → 14 → 15 with subagent-driven-development: fresh implementer per task, two-stage review (spec + code-quality) after each. Task 13 (`10b90c0` + review-fix `a98a39e`): Prompt + STM sections with auto-refetch on phase/last_error_ts, plus in-repo `JsonTree` recursive renderer; review-fix skipped the first-render double-fetch and swapped string rendering to `JSON.stringify` for escape-safety. Task 14 (`6a8df79`, no review-fix — APPROVED with Suggestions only): Messages section with monotonic `envelopesReceivedTotal`-gated incremental scan (fixes plan's length-plateau race, same class as v1 Counters'), stable `observed_at\|topic` expand-state keys, auto-scroll follow-tail within 40 px. Task 15 (this commit): HANDOFF bump only; no code changes. Suite grew to 92 unit + 2 component Python + 84 frontend vitest (was 78 pre-session-5). Canonical resume prompt pivoted to v3. |
| 2026-04-22 | Session 6: v3 scoping. Brainstormed real-time-visibility MVP with Larry (visual companion mockups for layout; picked bottom-dock A with collapsible/resizable, 3D primary, click-region-popup). Audited Hive's MQTT surface — confirmed all v3 needs are already on the wire (cognitive/sensory/motor/metacog/self/modulator/etc. + retained metrics + heartbeat); no Hive-side publish changes required. Found post-v2 staleness: `ecd8a94` made `prompt.md` immutable with `memory/appendices/rolling.md` as the rolling appendix, and `155854d` dropped `hive/self/developmental_stage` + `hive/self/age` (both still referenced by current SelfPanel). Wrote v3 spec (`7d5762e`, 477 lines) — six-item MVP: bottom dock (Firehose + Topics + Metacog tabs), inspector Appendix section, HUD SystemMetrics + expanded SelfState, full-envelope JsonTree in Messages, unified dock-row→scene-focus→popup interaction. Wrote v3 plan (`7813c92`, 11 tasks, ~2950 lines). Next session: execute via subagent-driven-development. Canonical resume prompt: `continue observatory v3 implementation`. |
| 2026-04-22 | Session 7 ships v3. Executed all 11 tasks via `superpowers:subagent-driven-development`: fresh implementer per task, two-stage review after each (spec-compliance `general-purpose` + code-quality `superpowers:code-reviewer`), fix-loop on anything Important+. Total: 11 task commits + 9 review-fix commits + 1 doc-fix + this ship commit. Suite grew from 92 unit + 2 component + 84 frontend → 99 unit + 3 component + 168 frontend. Ruff + tsc clean throughout; production build emits 1.08 MB JS bundle. Significant arbitrations along the way: Task 1 spec §9.2 literal 404 body (`appendix_missing`) won over plan's reuse of `_error_detail`; Task 6 10-s sparkline buckets won over plan's 1-tick-per-bucket code; Task 9 SystemMetrics `region_health.per_region` schema reconciled against `glia/metrics.py` actual shape `{status, consecutive_misses, uptime_s}` rather than plan's bare-string fixture; Task 10 pendingEnvelopeKey mount race fixed by adding `filtered` to the consumption effect's deps. Larry course-corrected once early in session ("where there is confusion or ambiguity you should be asking me") — subsequent arbitration of spec-vs-plan conflicts surfaced to him explicitly. All 10 implementer prompts + this Task 11 prompt-of-record stored at `observatory/prompts/v3-task-NN-<slug>.md`. Decisions.md entries appended through session. Canonical resume prompt pivoted to `continue observatory v4` — v4 not yet scoped. |
| 2026-04-29 | Session 8 — v4 session 1: backend + proposals landed. Executed Tasks 1–5 via `superpowers:subagent-driven-development`: fresh implementer per task, two-stage review (spec-compliance `general-purpose` + code-quality `superpowers:code-reviewer`) on Tasks 1–4. Task 5 (two inert YAML proposal artifacts) committed directly without the review pair — the content is verbatim from spec §5.1/§5.2 and has no logic. Total session-8 commits: 5 task commits, no review-fix commits, no doc-fix commits. Every review-pair came back APPROVED on first pass; suggestions deferred to decisions.md. Significant arbitrations: Task 3 pre-approved JSONResponse drift (route returns `JSONResponse` directly for 5xx so the route's bare-FastAPI() unit-test fixture sees the flat `{error, message}` body shape regardless of the wider app's exception handler — without this, the plan-verbatim `raise HTTPException(detail={...})` would yield `{detail: {...}}` and break `body["error"]` assertions); Task 3 module-level `_PUBLISHER_DEP`/`_SETTINGS_DEP` Depends singletons to dodge ruff B008 cleanly (matches FastAPI DI semantics, B008-clean). Pre-existing 3 `test_mqtt_reconnect.py::TestReconnectLoop` failures (introduced by `83b0bd3`'s stall watchdog `_FakeSubscriber` gap) confirmed orthogonal to v4 — flagged for a follow-up fix. Component test verified round-trip < 500 ms over real `eclipse-mosquitto:2` testcontainer. Suite snapshot: sensory unit 15 passed (4 + 4 + 7), full unit 133 passed + 2 skipped + 3 pre-existing failed, component 4 passed (3 prior + 1 new v4), ruff clean on v4 paths, frontend untouched. All 4 implementer prompts (Tasks 1–4) stored at `observatory/prompts/v4-task-NN-<slug>.md`. Decisions.md entries appended (4 new). Next: `continue observatory v4 — session 2` covers Tasks 6–9 (frontend store + chat persistence + REST wrapper + Transcript/TranscriptTurn + ChatInput). |
