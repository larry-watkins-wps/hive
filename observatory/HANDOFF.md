# Observatory — Session Handoff

*Last updated: 2026-04-20 (session 2, mid-session checkpoint 2)*

**Canonical resume prompt:** `continue observatory v1`

---

## State snapshot

| Milestone | Status | Notes |
|---|---|---|
| Brainstorm | ✅ Complete | 2026-04-20 — design approved |
| Spec written | ✅ Complete | `observatory/docs/specs/2026-04-20-observatory-design.md` |
| Plan written | ✅ Complete | `observatory/docs/plans/2026-04-20-observatory-plan.md` (16 tasks, ~3247 lines) |
| v1 Task 1 — scaffolding + ring buffer | ✅ Complete | Commits `3896f64` + `491a36a` (review-fix: `ConfigError` + docstring) |
| v1 Task 2 — retained cache + region registry | ✅ Complete | Commits `fb6b9e8` + `1978fc5` (review-fix: real glia schema + heartbeat robustness) |
| v1 Task 3 — adjacency + decimator | ✅ Complete | Commits `01ccebd` + `e260f6c` (review-fix: window anchor + drop-count semantics) |
| v1 Task 4 — MQTT subscriber | ✅ Complete | Commits `af892da` + `a1d9536` (review-fix: MQTT wildcard regex + fault tolerance + source-None + heartbeat guards) |
| v1 Task 5 — REST `/api/health` + `/api/regions` | ✅ Complete | Commit `9fa2c63` (no review-fix needed) |
| v1 Task 6 — WebSocket hub + fan-out | ✅ Complete | Commits `1eec20d` + `a55ea81` (review-fix: `decimated` message + delta loop exception guard + `put_nowait`). Caught latent `_Client` hashability bug in plan code. |
| v1 Task 7 — service assembly + CLI + Dockerfile | ⏳ Next | |
| v1 Task 8 — component e2e (testcontainers) | ⏳ Pending | |
| v1 Tasks 9–16 — frontend | ⏳ Pending | |
| v2 implementation | ⏳ Pending | |
| v3 implementation | ⏳ Pending | |

## Suite + lint snapshot

- `python -m pytest observatory/tests/unit/ -q` → **57 passed** (ring buffer 5 + config 4 + retained cache 4 + region registry 7 + adjacency 4 + decimator 7 + MQTT subscriber 16 + api 2 + ws 8)
- `python -m ruff check observatory/` → clean

Smoke-verified against production `glia/regions_registry.yaml`: 19 regions load correctly with `layer` → `role` mapping.

## What's done (session 2)

Executed Tasks 1–3 with `superpowers:subagent-driven-development` discipline: fresh implementer per task, two-stage review (spec-compliance + code-quality) after each, review-fix commit on top of each task's landing commit. Per-task implementer prompts stored under `observatory/prompts/`. Non-obvious calls logged in `observatory/memory/decisions.md` (14 entries).

Notable substantive deviation from plan: Task 2's YAML parser was reconciled to the real `glia/regions_registry.yaml` schema (`regions:` as dict keyed by name with `layer`/`required_capabilities`, not the plan's fictional list of `{name, role, llm_model}`). Spec §6.5 authorises this read and spec wins over plan prose per the authority ordering in `observatory/CLAUDE.md`. Would otherwise have silently returned empty registry at Tasks 7/8.

## What's next

**Task 7: service assembly + CLI entry + Dockerfile.** Put the pieces together: FastAPI app factory with `lifespan` hook that connects `aiomqtt`, starts the ConnectionHub delta loop, drains on shutdown. `python -m observatory` boots it. Multi-stage Dockerfile bundles the (still-unbuilt) frontend into the image.

- Plan: search `### Task 7:` in `observatory/docs/plans/2026-04-20-observatory-plan.md` (~line 1569).
- Expected outputs: `observatory/service.py` + `observatory/__main__.py` + `observatory/Dockerfile` (and possibly a small unit test for `_parse_mqtt_url` or `build_app` assembly).
- Gotchas to carry forward:
  - `aiomqtt` version pin must stay compatible with `region_template/mqtt_client.py` (top-level CLAUDE.md).
  - Windows needs `WindowsSelectorEventLoopPolicy` for aiomqtt (`add_reader`/`add_writer`) — component tests in Task 8 will need `tests/component/conftest.py` to force it (precedent exists at the repo root).
  - `ConnectionHub.stop()` cancels but does not await — the lifespan should `await asyncio.wait_for(hub._delta_task, timeout=…)` for clean shutdown if we want to avoid a CancelledError trace.
  - Service wiring will monkey-patch `subscriber.dispatch` to also fan out to the WS hub (plan's Step 1 pattern). Confirm this doesn't regress any of the subscriber tests — they test the unwrapped `dispatch()` directly.

## Follow-ups / open threads

- **Plan-code drift:** Plan's verbatim code blocks repeatedly fail ruff (UP037, UP035, PLR2004, B007, I001) and sometimes spec fidelity (Task 2 YAML schema). The authoring pattern is working — fix-loop catches them — but a v1.1 pass over the plan to update these blocks to match what actually shipped would save future implementers the re-discovery cost. Tracked in `observatory/memory/decisions.md` entries 9–11.
- **`RegionMeta.llm_model` is always empty** against production YAML (the real schema doesn't carry per-region model). Revisit when/if a region-level LLM identity is needed for the HUD — likely via `capabilities` or a separate model-routing policy read.
- **Decimator priority hooks (`_LOW_PRIORITY_PREFIXES`, `_is_low_priority`)** are unused in v1 by design — wiring a v1.1 priority-aware drop is a one-line change at `should_keep`'s over-budget branch.

## Changelog

| Date | Change |
|---|---|
| 2026-04-20 | Initial handoff — spec + CLAUDE.md + HANDOFF.md created. |
| 2026-04-20 | Session 2: Tasks 1–3 complete + review-fixes; 31 unit tests passing; next is Task 4 (MQTT subscriber). |
| 2026-04-20 | Session 2 checkpoint 2: Tasks 4–6 complete + review-fixes; 57 unit tests passing; next is Task 7 (service assembly). Notable catches: real `glia/regions_registry.yaml` schema reconciled (Task 2), production envelope wrapper shape handled (Task 4), MQTT wildcard regex correctness fixed (Task 4), `decimated` WS message added to match spec §5.3 (Task 6). |
