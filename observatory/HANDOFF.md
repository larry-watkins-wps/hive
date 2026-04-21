# Observatory — Session Handoff

*Last updated: 2026-04-20 (session 2)*

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
| v1 Task 4 — MQTT subscriber | ⏳ Next |  |
| v1 Tasks 5–8 — REST / WS / service / e2e | ⏳ Pending | |
| v1 Tasks 9–16 — frontend | ⏳ Pending | |
| v2 implementation | ⏳ Pending | |
| v3 implementation | ⏳ Pending | |

## Suite + lint snapshot

- `python -m pytest observatory/tests/unit/ -q` → **31 passed** (ring buffer 5 + config 4 + retained cache 4 + region registry 7 + adjacency 4 + decimator 7)
- `python -m ruff check observatory/` → clean

Smoke-verified against production `glia/regions_registry.yaml`: 19 regions load correctly with `layer` → `role` mapping.

## What's done (session 2)

Executed Tasks 1–3 with `superpowers:subagent-driven-development` discipline: fresh implementer per task, two-stage review (spec-compliance + code-quality) after each, review-fix commit on top of each task's landing commit. Per-task implementer prompts stored under `observatory/prompts/`. Non-obvious calls logged in `observatory/memory/decisions.md` (14 entries).

Notable substantive deviation from plan: Task 2's YAML parser was reconciled to the real `glia/regions_registry.yaml` schema (`regions:` as dict keyed by name with `layer`/`required_capabilities`, not the plan's fictional list of `{name, role, llm_model}`). Spec §6.5 authorises this read and spec wins over plan prose per the authority ordering in `observatory/CLAUDE.md`. Would otherwise have silently returned empty registry at Tasks 7/8.

## What's next

**Task 4: MQTT subscriber.** Wire `aiomqtt` to the ring buffer, retained cache, region registry, and adjacency matrix. Parse Hive envelope JSON; infer destinations from `regions/<name>/subscriptions.yaml` snapshots at startup.

- Plan: search `### Task 4:` in `observatory/docs/plans/2026-04-20-observatory-plan.md` (~line 888).
- Expected outputs: `observatory/mqtt_subscriber.py` + `observatory/tests/unit/test_mqtt_subscriber.py`.
- Gotchas to carry forward:
  - `aiomqtt` version pin must stay compatible with `region_template/mqtt_client.py` (top-level CLAUDE.md).
  - Windows needs `WindowsSelectorEventLoopPolicy` for aiomqtt (`add_reader`/`add_writer`) — component tests will hit this in Task 8.
  - `time.monotonic()` is the clock the Decimator and Adjacency expect (anchored per review-fix).

## Follow-ups / open threads

- **Plan-code drift:** Plan's verbatim code blocks repeatedly fail ruff (UP037, UP035, PLR2004, B007, I001) and sometimes spec fidelity (Task 2 YAML schema). The authoring pattern is working — fix-loop catches them — but a v1.1 pass over the plan to update these blocks to match what actually shipped would save future implementers the re-discovery cost. Tracked in `observatory/memory/decisions.md` entries 9–11.
- **`RegionMeta.llm_model` is always empty** against production YAML (the real schema doesn't carry per-region model). Revisit when/if a region-level LLM identity is needed for the HUD — likely via `capabilities` or a separate model-routing policy read.
- **Decimator priority hooks (`_LOW_PRIORITY_PREFIXES`, `_is_low_priority`)** are unused in v1 by design — wiring a v1.1 priority-aware drop is a one-line change at `should_keep`'s over-budget branch.

## Changelog

| Date | Change |
|---|---|
| 2026-04-20 | Initial handoff — spec + CLAUDE.md + HANDOFF.md created. |
| 2026-04-20 | Session 2: Tasks 1–3 complete + review-fixes; 31 unit tests passing; next is Task 4 (MQTT subscriber). |
