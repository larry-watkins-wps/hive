# Observatory — Session Handoff

*Last updated: 2026-04-20 (session 2, v1 backend complete)*

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
| v1 Task 9 — frontend scaffolding (Vite + React + TS + Tailwind) | ⏳ Next | |
| v1 Tasks 10–16 — frontend scene + HUD + integration | ⏳ Pending | |
| v2 implementation | ⏳ Pending | |
| v3 implementation | ⏳ Pending | |

## Suite + lint snapshot

- `python -m pytest observatory/tests/unit/ -q` → **67 passed** (ring buffer 5 + config 4 + retained cache 4 + region registry 7 + adjacency 4 + decimator 7 + MQTT subscriber 16 + api 2 + ws 8 + service 10)
- `python -m pytest observatory/tests/component/ -m component -v` → **1 passed** (requires Docker Desktop; `eclipse-mosquitto:2` via testcontainers; real MQTT publish → WS receive verified)
- `python -m ruff check observatory/` → clean
- Smoke test: `python -c "from observatory.config import Settings; from observatory.service import build_app; build_app(Settings())"` → `ok`
- Smoke-verified against production `glia/regions_registry.yaml`: 19 regions load correctly (`layer` → `role` mapping).

## What's done (session 2)

Executed all **eight** backend tasks (1–8) with `superpowers:subagent-driven-development` discipline: fresh implementer per task, two-stage review (spec-compliance + code-quality) after each, review-fix commit on top of each task's landing commit. Per-task implementer prompts stored under `observatory/prompts/`. Non-obvious calls logged in `observatory/memory/decisions.md` (40+ entries).

**Total: 16 task commits + 8 review-fix commits + 3 HANDOFF commits = 27 observatory commits this session.**

Notable substantive fixes vs. the plan:
- **Task 2** — real `glia/regions_registry.yaml` schema (dict keyed by name with `layer`/`required_capabilities`) reconciled; plan's list-of-dicts format would have silently returned empty.
- **Task 3** — `Decimator._window_start` anchored to first event (was `0.0` default, caused phantom first window); `drop_count()` split into `drops_in_current_window()` + `total_dropped()`.
- **Task 4** — `_matches` replaced `fnmatch` with proper MQTT regex (`+` is single-level, not cross-segment); `load_subscription_map` fault-tolerant; production envelope `payload.data` unwrap in heartbeat branch; source=None handled.
- **Task 6** — caught latent `_Client` hashability bug (dataclass generates `__eq__` → `__hash__ = None`); added `decimated` WS message per spec §5.3; `_delta_loop` exception guard + non-blocking `put_nowait` so slow clients can't stall others.
- **Task 7** — MQTT task done-callback surfaces broker failures; non-loopback warning via structlog.
- **Task 8** — hand-rolled mosquitto config (testcontainers' default collides on eclipse-mosquitto:2); `retain=True` publish eliminates subscribe/publish race.

## What's next

**Task 9: frontend scaffolding.** Bare Vite + React + TypeScript + Tailwind project in `observatory/web-src/` that builds to `observatory/web/`. Full-viewport `<canvas>` + placeholder HUD rectangle, no scene yet — the goal is to prove the pipeline (vite dev, vite build, FastAPI static mount) works before Task 10+ wire real state management and the 3D scene.

- Plan: search `### Task 9:` in `observatory/docs/plans/2026-04-20-observatory-plan.md` (~line 1895).
- Expected outputs: `observatory/web-src/package.json`, `vite.config.ts`, `tsconfig.json`, `tsconfig.node.json`, `tailwind.config.ts`, `postcss.config.js`, `index.html`, `src/main.tsx`, `src/App.tsx`, `src/index.css`.
- Gotchas to carry forward:
  - This is a **language-stack switch** — TypeScript/React/Vite/Tailwind instead of Python/pytest/ruff. The implementer prompt should lean on frontend conventions, not Python ones.
  - `observatory/Dockerfile` already expects `observatory/web-src/package-lock.json` and built `observatory/web/` — Task 9 makes this materialize.
  - Tasks 10–16 build on Task 9 iteratively (scene, HUD, integration). Keep Task 9 minimal.
  - The existing backend test suite (67 unit + 1 component) must remain green — Task 9 shouldn't touch any Python.

## Follow-ups / open threads

- **Plan-code drift** (14+ documented deviations in `decisions.md`): Plan's verbatim code blocks repeatedly fail ruff (UP037, UP035, PLR2004, B007, I001) and sometimes have correctness bugs (fnmatch MQTT wildcards, `_Client` hashability, YAML schema). Fix-loop catches them consistently, but a v1.1 plan-prose pass could save future implementers the re-discovery cost.
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
