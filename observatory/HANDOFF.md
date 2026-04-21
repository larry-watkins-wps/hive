# Observatory — Session Handoff

*Last updated: 2026-04-21 (session 3, Task 9 complete)*

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
| v1 Task 10 — WebSocket client + REST client + zustand store | ⏳ Next | |
| v1 Tasks 11–16 — frontend scene + HUD + integration | ⏳ Pending | |
| v2 implementation | ⏳ Pending | |
| v3 implementation | ⏳ Pending | |

## Suite + lint snapshot

- `python -m pytest observatory/tests/unit/ -q` → **67 passed** (ring buffer 5 + config 4 + retained cache 4 + region registry 7 + adjacency 4 + decimator 7 + MQTT subscriber 16 + api 2 + ws 8 + service 10)
- `python -m pytest observatory/tests/component/ -m component -v` → **1 passed** (requires Docker Desktop; `eclipse-mosquitto:2` via testcontainers; real MQTT publish → WS receive verified)
- `python -m ruff check observatory/` → clean
- Smoke test: `python -c "from observatory.config import Settings; from observatory.service import build_app; build_app(Settings())"` → `ok`
- Smoke-verified against production `glia/regions_registry.yaml`: 19 regions load correctly (`layer` → `role` mapping).
- Frontend: `cd observatory/web-src && npm run build` → `observatory/web/index.html` + `assets/index-*.{js,css}` emitted in ~800 ms. No vitest suite yet (arrives in Task 10).

## What's done (session 3)

Executed **Task 9** (frontend scaffolding) with `superpowers:subagent-driven-development` discipline: fresh implementer, two-stage review (spec-compliance + code-quality), review-fix commit. Implementer prompt stored at `observatory/prompts/task-09-frontend-scaffolding.md`. Non-obvious calls logged in `observatory/memory/decisions.md` (entries 46–51).

**Session 3 totals: 1 task commit (`8b6be24`) + 1 review-fix commit (`fc0ce94`) + HANDOFF bump.**

Substantive fixes vs. the plan (all logged in `decisions.md`):
- **Drift A** — Plan's `package.json` devDep `@types/d3-force-3d@^3.0.10` doesn't exist on npm (DefinitelyTyped never published it; `d3-force-3d` ships no own types). `npm install` hard-failed with E404. **Fix:** removed that devDep. Task 10+ will need an ambient-module declaration (`declare module 'd3-force-3d';`) in `src/types.d.ts` when `d3-force-3d` is actually imported.
- **Drift B** — Plan omitted `@types/node`, causing ~60 `TS2307`/`TS2580` errors from vite's `index.d.ts` references to `node:http`/`Buffer`/`NodeJS`. **Fix:** added `@types/node@^20` (matches Dockerfile's `node:20-alpine` builder).
- **Drift C** — Plan's `tsconfig.json` (no `noEmit`) + `tsconfig.node.json` (`composite: true`) emit `.js`/`.d.ts`/`.tsbuildinfo` residue next to sources on every build. **Fix:** added `"noEmit": true` to `tsconfig.json` (Vite-starter default) + five additive patterns to `observatory/.gitignore` (`*.tsbuildinfo`, `web-src/{vite,tailwind}.config.{js,d.ts}`).
- **Review-fix** — `vite.config.ts` dev-server proxy changed `localhost:8765` → `127.0.0.1:8765` (matches commit-message intent, avoids Windows IPv6-first resolver gotcha when FastAPI binds to `127.0.0.1`).

### Prior session (session 2) substantive fixes vs. the plan

- **Task 2** — real `glia/regions_registry.yaml` schema (dict keyed by name with `layer`/`required_capabilities`) reconciled; plan's list-of-dicts format would have silently returned empty.
- **Task 3** — `Decimator._window_start` anchored to first event (was `0.0` default, caused phantom first window); `drop_count()` split into `drops_in_current_window()` + `total_dropped()`.
- **Task 4** — `_matches` replaced `fnmatch` with proper MQTT regex (`+` is single-level, not cross-segment); `load_subscription_map` fault-tolerant; production envelope `payload.data` unwrap in heartbeat branch; source=None handled.
- **Task 6** — caught latent `_Client` hashability bug (dataclass generates `__eq__` → `__hash__ = None`); added `decimated` WS message per spec §5.3; `_delta_loop` exception guard + non-blocking `put_nowait` so slow clients can't stall others.
- **Task 7** — MQTT task done-callback surfaces broker failures; non-loopback warning via structlog.
- **Task 8** — hand-rolled mosquitto config (testcontainers' default collides on eclipse-mosquitto:2); `retain=True` publish eliminates subscribe/publish race.

## What's next

**Task 10: WebSocket client + REST client + zustand store.** First task with real frontend logic — introduces `observatory/web-src/src/store.ts` (zustand), `src/api/ws.ts` (WebSocket client wrapping `/ws`), `src/api/rest.ts` (fetch wrapper for `/api/health` + `/api/regions`), `vitest.config.ts`, and per-module test files. TDD cycle: write failing test → make pass → refactor.

- Plan: search `### Task 10:` in `observatory/docs/plans/2026-04-20-observatory-plan.md` (~line 2102).
- Expected outputs: `observatory/web-src/src/store.ts`, `src/api/ws.ts`, `src/api/rest.ts`, `vitest.config.ts`, and their test files.
- Gotchas to carry forward:
  - **`d3-force-3d` has no type definitions.** When `store.ts` or later tasks import `d3-force-3d`, create `observatory/web-src/src/types.d.ts` with `declare module 'd3-force-3d';` (drift A in Task 9 removed the phantom `@types/d3-force-3d` devDep).
  - Dev-server proxy targets `127.0.0.1:8765` (Windows IPv6 safe). When a test spins a local server to drive `ws.ts`, prefer `127.0.0.1` over `localhost`.
  - TypeScript is strict: `noUnusedLocals` + `noUnusedParameters`. Name unused callback params `_arg`.
  - The backend `/ws` protocol lives in `observatory/ws.py` (snapshot, `envelope`, `region_delta`, `adjacency`, `decimated` message types — spec §5.3). Wire the client to parse all five.
  - `tsconfig.node.json` already includes `vitest.config.ts` in its `include` list (plan-verbatim forward-reference — will finally be real when Task 10 creates the file).

## Follow-ups / open threads

- **Plan-code drift** (17+ documented deviations in `decisions.md`): Plan's verbatim code blocks repeatedly fail ruff (UP037, UP035, PLR2004, B007, I001), sometimes have correctness bugs (fnmatch MQTT wildcards, `_Client` hashability, YAML schema), and — new in Task 9 — omit the `@types/node` devDep required by Vite 5, include a phantom `@types/d3-force-3d` package, and miss the `noEmit: true` compiler option needed to suppress `tsc -b` source-dir emit residue. Fix-loop catches them consistently, but a v1.1 plan-prose pass could save future implementers the re-discovery cost.
- **`d3-force-3d` typing.** Task 9 removed the phantom `@types/d3-force-3d` devDep. Task 10+ must add `declare module 'd3-force-3d';` in `src/types.d.ts` on first import. If upstream DefinitelyTyped publishes types later, swap the ambient-module declaration for the real package.
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
