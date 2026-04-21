# Hive — Session Handoff

**Last updated:** 2026-04-20 (Phase 6 COMPLETE — Bootstrap CLI)
**Current phase:** Phase 6 (Bootstrap CLI) ✅; Phase 7 (Observability) or Phase 8 (14 regions) next
**Repo path:** `C:/repos/hive/`

This document is the **source of truth for session-to-session continuity.** Any Claude Code session working on Hive should begin by reading this file in full, then proceed according to the current phase.

---

## Quick reference

| Phase | Status | Artifact location |
|---|---|---|
| 1. Brainstorming | ✅ Complete | `docs/principles.md`, `docs/architecture.md`, `docs/starter_prompts/` |
| 2. Design Spec | ✅ Complete (2026-04-19) | `docs/superpowers/specs/2026-04-19-hive-v0-design.md` (4,792 lines) |
| 3. Implementation Plan | ✅ Complete (2026-04-19) | `docs/superpowers/plans/2026-04-19-hive-v0-plan.md` (3 review iterations) |
| 4. Implementation | ⏳ **Next** | `region_template/`, `regions/`, `glia/`, `bus/`, `shared/` (code) |

---

## Phase 1: Brainstorming — COMPLETE

### What was established

Through iterative design dialogue, the brainstorming phase produced:

**16 guiding principles** (see `docs/principles.md`):
- I: Biology is the Tiebreaker
- II: MQTT is the Nervous System
- III: Regions are Sovereign
- IV: Modality Isolation
- V: Private Memory
- VI: DNA vs. Gene Expression
- VII: One Template, Many Differentiated Regions
- VIII: Always-On, Always-Thinking
- IX: Wake and Sleep Cycles
- X: Capability Honesty
- XI: LLM-Agnostic Substrate
- XII: Every Change is Committed
- XIII: Emergence Over Orchestration
- XIV: Chaos is a Feature
- XV: Bootstrap Minimally, Then Let Go
- XVI: Signal Types Match Biology

**Architecture** (see `docs/architecture.md`) — 13 mermaid diagrams covering:
1. System-level architecture
2. Repository structure
3. Single-region internals
4. MQTT topic schema (full catalog)
5. User input → response flow
6. Sensory input flow (audio example)
7. Motor output flow (speech example)
8. Sleep cycle state diagram
9. Self-modification flow ("implement hearing")
10. Cross-modal association flow
11. Neurogenesis (ACC deliberating + glia executing)
12. Safety & enforcement layers (7-layer defense)
13. Message envelope spec
14. Modulator flow, rhythm coordination, interoception grounding, habit formation, self-state evolution, cross-region encoding

**14 starter prompts** (see `docs/starter_prompts/`) — one per v0 region, self-sufficient (all 16 principles embedded), stage-aware (regions read `hive/self/developmental_stage` rather than hard-coding), and self-evolution-enabled (each has a detailed protocol for editing itself during sleep).

### Key architectural decisions made

- MQTT is the only inter-region communication channel
- Glia (infrastructure) is separate from cognitive regions — no LLM, no cognition
- Anterior Cingulate Cortex (ACC) is the metacognitive gate for spawns and code changes
- mPFC holds global self; other regions read retained `hive/self/*` topics
- Insula handles interoception of computational body (tokens, compute, region health)
- Basal ganglia handles habit formation via dopamine reinforcement
- Modality isolation is absolute; ACLs enforce at broker level
- Three signal types: messages, modulators (retained), rhythms (broadcast)
- Hive is a "teenager analog" at v0 — all regions present, minimal handlers, empty memory

### Git log of Phase 1 (16 commits)

```
5b930ff Initial Hive design: 16 principles + architecture for 14-region v0
5c9fb5b Add starter_prompts directory and README
da53501 Add starter prompt: medial_prefrontal_cortex (mPFC)
25ea7df Add starter prompt: prefrontal_cortex (PFC)
85193ae Add starter prompt: hippocampus
b16549b Add starter prompt: anterior_cingulate (ACC)
ed66f06 Add starter prompt: thalamus
7c7b951 Add starter prompt: association_cortex
8976c0d Add starter prompt: insula
3ad2f34 Add starter prompt: basal_ganglia
c6a738f Add starter prompt: motor_cortex
866377d Add starter prompt: broca_area
99283df Add starter prompt: visual_cortex
1f0f3be Add starter prompt: auditory_cortex
76676c3 Add starter prompt: amygdala
2bff019 Add starter prompt: vta
```

---

## Phase 2: Design Spec — NEXT

### Goal

Write a full implementation-ready spec at `docs/superpowers/specs/2026-04-19-hive-v0-design.md`. This translates brainstorming artifacts into concrete API signatures, schemas, behaviors, and testing strategies sufficient for implementation.

### Prompt for Phase 2

Paste the following into a new Claude Code session:

---

```
You are continuing work on the Hive project at C:/repos/hive/.

Hive is a distributed LLM-based system modeled on the human brain. Each
brain region is a standalone Python process that communicates with
other regions exclusively over MQTT. The brainstorming phase is
complete and committed to the repo.

## Start here

Read these files in order before doing anything else:

1. docs/HANDOFF.md — full session context and your task
2. docs/principles.md — 16 constitutional principles
3. docs/architecture.md — system architecture with 13 mermaid diagrams
4. docs/starter_prompts/README.md — inventory of 14 v0 regions

Spot-check 2–3 starter prompts to understand the style:
- docs/starter_prompts/medial_prefrontal_cortex.md
- docs/starter_prompts/amygdala.md
- docs/starter_prompts/motor_cortex.md

## Your task

Write the full design spec at:
docs/superpowers/specs/2026-04-19-hive-v0-design.md

The spec must cover EVERY topic in the "Spec coverage" section of
docs/HANDOFF.md (Phase 2). Treat that list as the required outline.

## Process

1. DO NOT re-brainstorm the design. The design is approved and
   committed. If you find a gap or contradiction, flag it clearly in
   the spec under an "Open Questions" section — do not change existing
   decisions without surfacing why.

2. Use the superpowers:brainstorming skill's spec-writing phase or
   write directly — whichever produces a better spec. The skill's
   terminal state is invoking writing-plans; you will reach that
   terminal state, but it is the END of this session, not the start.

3. Present the spec to the user section-by-section for approval as you
   write (the brainstorming skill's standard pattern). Scale each
   section to its complexity.

4. After the spec is approved by the user, run the spec review loop:
   dispatch the spec-document-reviewer subagent; fix any issues;
   re-dispatch; repeat until approved (max 3 iterations — if the
   third fails, surface to the user).

5. Commit the spec to git.

6. Update docs/HANDOFF.md to reflect:
   - Phase 2 complete with date
   - Phase 3 (Implementation Plan) is now next
   - Add any architectural clarifications or gaps that emerged during
     spec writing

7. Report back to the user with: (a) summary of the spec, (b) any gaps
   or concerns surfaced, (c) readiness for implementation planning.

## What the spec must cover

REQUIRED outline (every item must be addressed):

### A. Core runtime (region_template/)
- Python API for the RegionRuntime class (signatures, method behavior)
- Region lifecycle: bootstrap → wake → sleep → restart
- Event loop structure and heartbeat cadence
- Wake/sleep state machine with transition triggers
- Self-modification tool interfaces:
  - edit_prompt, edit_subscriptions, edit_handlers
  - write_memory (STM and LTM)
  - commit_changes (per-region git)
  - request_restart
  - spawn_new_region (only mPFC/ACC can call; framework enforces)

### B. MQTT layer
- Full topic catalog with ACL rules per region (mosquitto.conf + acl.conf format)
- Message envelope JSON schema
- Retained vs. non-retained conventions
- Broker setup (mosquitto or equivalent)
- Connection lifecycle: connect, reconnect, Last Will Testament
- QoS levels per topic category

### C. LLM adapter (LiteLLM integration)
- Provider abstraction (Anthropic, OpenAI, Ollama, etc.)
- Per-region config.yaml for LLM selection
- Capability enforcement (self_modify, tool_use, vision, etc.)
- Token budget tracking per region and global
- Error handling on LLM failures (retry, fallback, surface)
- Prompt caching strategy where applicable

### D. Memory system
- STM structure (JSON schema for stm.json)
- LTM structure (file layout in memory/ltm/)
- Indexing/retrieval API (regions query each other's memory via MQTT)
- Consolidation protocol (STM → LTM during sleep, coordinated by hippocampus)
- Per-region git integration for rollback
- Memory queries: how does one region ask another for relevant memory?

### E. Glia (infrastructure)
- Process launcher interface (launch one region)
- Heartbeat monitoring (cadence, failure detection threshold)
- Auto-restart policy (crash loops, back-off)
- ACL mediation: how glia applies broker config changes
- Rollback on boot failure (automatic git revert)
- System metrics publishing (hive/system/metrics/*)

### F. Configuration
- config.yaml schema for each region (all fields, defaults, validation)
- Regional anatomy registry (list of known region types)
- Environment variables, secrets management (API keys)

### G. Bootstrap
- `hive up` command sequence: start broker → apply ACLs → launch regions → verify health
- Graceful shutdown ordering
- Development mode (single region, in-process broker, no ACL)
- First-boot behavior (mPFC publishes initial self-state; others read it)

### H. Observability
- Logging strategy (per-region logs, structured, aggregation path)
- Metrics exposed per region (token usage, compute, errors, heartbeats)
- Debug tooling (inspect live modulator state, attention focus, etc.)
- Trace IDs via message envelope correlation_id

### I. Testing strategy
- Unit tests for region_template/ components (mockable LLM, mockable MQTT)
- Integration tests with real broker + minimal regions
- E2E test harness (smoke test with 3 regions + scripted MQTT traffic)
- What to mock vs. what to run real
- How to test self-modification cycles

### J. Safety & recovery
- Error handling when a region crashes mid-operation
- Recovery when mPFC is unreachable (fallback self-state defaults)
- Poison-message handling (malformed envelopes)
- Rate limiting / cost caps per region and globally
- Pre-restart verification after self-modification

### K. Developer ergonomics
- Run one region locally for iteration
- Inspect MQTT traffic (tool suggestions)
- Test a self-modification cycle
- IDE / editor setup notes

## Deliverables

- docs/superpowers/specs/2026-04-19-hive-v0-design.md (committed)
- Updated docs/HANDOFF.md
- Summary report to user

Total expected length: ~3000–6000 lines of spec, depending on depth.
Spec review loop may reduce or restructure.
```

---

### Spec coverage checklist (reference only — prompt above contains the authoritative version)

The spec must address every item in section A through K of the prompt above. Nothing in that list is optional.

---

## Phase 3: Implementation Plan — PENDING

### Goal

Convert the approved spec into an executable plan at `docs/superpowers/plans/2026-04-19-hive-v0-plan.md`. Plans are typically consumed by superpowers:executing-plans or superpowers:subagent-driven-development.

### Prompt for Phase 3

Paste the following into a new Claude Code session (after Phase 2 is complete):

---

```
You are continuing work on the Hive project at C:/repos/hive/.

The design spec is complete. Your task this session: write the
implementation plan.

## Start here

Read these files in order:

1. docs/HANDOFF.md — full context and your task
2. docs/superpowers/specs/2026-04-19-hive-v0-design.md — the approved spec
3. docs/principles.md, docs/architecture.md — for principles compliance

Spot-check starter prompts as needed for region-specific details.

## Your task

Use the superpowers:writing-plans skill.

Write the implementation plan at:
docs/superpowers/plans/2026-04-19-hive-v0-plan.md

The plan should:

- Break the spec into executable tasks with clear dependencies
- Group tasks for efficient parallelization (14 regions are largely
  independent once infrastructure is in place)
- Identify which tasks can be dispatched to subagents vs. which need
  main-session work
- Specify test strategy per task
- Include verification steps

## Suggested task grouping

1. Infrastructure (sequential, main session):
   - Repo scaffold (region_template/, bus/, glia/, shared/, etc.)
   - MQTT broker config + ACL templates
   - Message envelope library
   - Shared test utilities

2. Core runtime (sequential, main session — critical path):
   - region_template/runtime.py
   - region_template/mqtt_client.py
   - region_template/llm_adapter.py
   - region_template/memory.py
   - region_template/self_modify.py
   - region_template/sleep.py
   - region_template/capability.py

3. Glia (sequential, main session):
   - glia/launcher.py
   - glia/heartbeat_monitor.py
   - glia/acl_manager.py
   - glia/rollback.py
   - glia/registry.py

4. Regions (PARALLEL, dispatched agents — one per region):
   - regions/<name>/ for each of 14 regions
   - Each task: copy starter prompt, write config.yaml, init empty
     handlers/, init per-region git, verify region boots and passes
     heartbeat test

5. Bootstrap & observability (sequential, main session):
   - hive_bootstrap/ entry point
   - Logging + metrics aggregation
   - Dev-mode utilities

6. Integration & E2E tests (sequential, main session):
   - 3-region smoke test
   - Full 14-region boot verification
   - Self-modification cycle test

## Process

1. Do NOT re-spec. The spec is approved.
2. Use writing-plans skill; present phase-by-phase for user approval.
3. Commit the plan. Update docs/HANDOFF.md.
4. Report readiness to begin implementation.
```

---

## Phase 4: Implementation — IN PROGRESS (branch `impl/v0`)

### Status as of 2026-04-19 (Phase 3 Wave A complete)

| Phase | Status | Notes |
|---|---|---|
| 0. Foundation (3 tasks) | ✅ | `pyproject.toml`, `.gitignore`, `.env.example`, `scripts/bootstrap_env.sh`, `scripts/make_passwd.sh` |
| 1. Shared library (5 tasks) | ✅ | `shared/envelope_schema.json`, `shared/message_envelope.py` (39 tests), `shared/topics.py` (55 tests), `shared/metric_schemas.json` |
| 2. MQTT layer / bus (4 tasks) | ✅ | `bus/topic_schema.md`, `bus/mosquitto.conf`, `bus/acl_templates/_base.j2` + 14 per-region + `_new_region_stub.j2` |
| 3. Runtime DNA (17 tasks) | ✅ **Complete (17/17)** | All waves done. 508 unit tests + 6 component tests (real mosquitto via testcontainers). Ruff clean. |
| 4. Region Docker image | ✅ | `region_template/Dockerfile` (commit `f79c91a`). Builds `hive-region:v0` from `python:3.11-slim-bookworm@sha256:9c6f908…`. `docker run --rm hive-region:v0 --help` prints usage. |
| 5. Glia (12 tasks) | ✅ | All 12 tasks done: registry, launcher, heartbeat monitor, ACL manager, rollback, codechange executor, spawn executor, metrics aggregator, supervisor, `__main__`, 6 bridges. `docker build -t hive-glia:v0 -f glia/Dockerfile .` succeeds. |
| 6. Bootstrap CLI (2 tasks) | ✅ | `docker-compose.yaml` + `tools/hive_cli.py` (typer CLI: up/down/status/logs + --dev/--no-docker). 702 tests total (691 unit + 11 integration). |
| 7. Observability tools (4 tasks) | ⏳ | |
| 8. Region scaffolding × 14 | ⏳ | PARALLEL-OK |
| 9. Integration + smoke + self-mod tests | ⏳ | |
| 10. Docs + HANDOFF | ⏳ | |

**Phase 3 progress (17/17 tasks done — all waves):**

| Task | File | Status | Commits |
|---|---|---|---|
| 3.1 | `region_template/pyproject.toml` + `__init__.py` | ✅ A | `924b289` |
| 3.2 | `region_template/types.py` (+ tests) | ✅ A | `acdcfd6` impl, `3079852` lint fix, `bd77a61` spec §A.4.1 StrEnum update |
| 3.3 | `region_template/errors.py` (+ tests) | ✅ A | `1ec03d9` impl, `f57cd8b` review fixes |
| 3.4 | `region_template/logging_setup.py` (+ tests) | ✅ A | `f218d1f` impl, `1d664e3` review fixes |
| 3.5 | `region_template/config_loader.py` + schema + defaults | ✅ B | `7db78ae` impl, `a1680c3` review fixes |
| 3.6 | `region_template/capability.py` (+ tests) | ✅ B | `d008cc0` |
| 3.7 | `region_template/mqtt_client.py` + fake + component tests | ✅ C | `7779a1e` impl, `159abbc` review fixes (2 Critical + 6 Important) |
| 3.8 | LLM adapter stack (5 files) | ✅ C | `d416e06` impl, `2292df8` spec fixes (budget order + stream cost), `15abb86` quality fixes (LlmError.kind + litellm pin + zero-budget guard) |
| 3.9 | `region_template/memory.py` (+ tests) | ✅ B | `0363189` impl, `6d6b752` review fixes |
| 3.10 | `region_template/git_tools.py` (+ tests) | ✅ B | `0907408` |
| 3.11 | `region_template/self_modify.py` | ✅ C | `99e347e` impl, `a8759fe` LTM metadata kwargs, `7aeff26` Windows CRLF + tmp leak + protocol type |
| 3.12 | `region_template/handlers_loader.py` | ✅ C | `ea5527b` |
| 3.13 | `region_template/heartbeat.py` (+ tests) | ✅ B | `cdf9e08` |
| 3.14 | `region_template/sleep.py` + review prompt | ✅ C | `f94d365` impl, `718d664` short-reason fallback, `2130fd4` dirty-tree + schema braces + pycache |
| 3.15 | `region_template/runtime.py` (integrator) | ✅ C | `c4eab08` impl, `a0e03d2` ON_HEARTBEAT + SLEEP unsub + triggers, `33e8a47` broadcast/shutdown WAKE + error-path tests |
| 3.16 | `region_template/__main__.py` + entry component test | ✅ C | `c9365ec` |
| 3.17 | `region_template/litellm.config.yaml` (defaults.yaml landed in 3.5) | ✅ C | `782e354` |

**Plus** `35b2863 spec: §D.5.7/§D.10/§F.10 align with implementation` — the Wave-B-flagged spec deviations patched at start of Wave C. And `2af2df0 tests: ruff lint cleanup for shared-phase tests` from Wave A.

**Git state:** `impl/v0` has 48 commits total ahead of origin (18 new in Wave C, 30 from Waves A+B). **508 unit tests + 6 component tests passing** (full region_template + 3 MQTT component tests + 3 region-entry component tests against real eclipse-mosquitto:2 via testcontainers). `ruff check region_template/ tests/` clean. **Push to origin on next handoff.**

---

## Phase 5 — Glia — COMPLETE (2026-04-20)

All 12 tasks landed on `main`. 23 commits on top of Phase 4's HEAD. **691 unit tests passing**. `ruff check region_template/ glia/ tests/` clean. `docker build -t hive-glia:v0 -f glia/Dockerfile .` succeeds.

**Per-task status:**

| Task | File | Status | Commits |
|---|---|---|---|
| 5.1 | `glia/pyproject.toml` + `Dockerfile` + `__init__.py` | ✅ | `e372da8` |
| 5.2 | `glia/registry.py` + `regions_registry.yaml` | ✅ | `90271ff` impl, `ee0a2f2` review fixes |
| 5.3 | `glia/launcher.py` | ✅ | `3c46d54` impl, `6441669` review fixes |
| 5.4 | `glia/heartbeat_monitor.py` | ✅ | `b70db34` impl, `0e55f36` clock fix, `3c58850` review fixes |
| 5.5 | `glia/acl_manager.py` | ✅ | `315a43a` impl, `9e5ff2e` review fixes (Windows CRLF) |
| 5.6 | `glia/rollback.py` | ✅ | `da0b4d4` |
| 5.7 | `glia/codechange_executor.py` | ✅ | `f03ee1c` impl, `701f56b` review fixes (rollback relaunch-all) |
| 5.7a | `glia/spawn_executor.py` | ✅ | `28347d0` impl, `baa4b3c` review fixes (ACL-fail cleanup, cancel cleanup) |
| 5.8 | `glia/metrics.py` | ✅ | `78736b9` impl, `690a260` review fixes (mem cache) |
| 5.9 | `glia/supervisor.py` | ✅ | `0f31ede` impl, `f73faa7` review fixes (fire-and-forget restart) |
| 5.10 | `glia/__main__.py` | ✅ | `8458f0a` — `docker build -t hive-glia:v0` succeeds |
| 5.11 | `glia/bridges/*` (6 bridges) | ✅ | `d9f6de1` impl, `574176d` review fixes (log.warning on degrade) |

**Spec-vs-plan deviations resolved during Phase 5 (implementation follows spec; flagged in module docstrings):**

1. **§F.3 registry YAML**: plan mentioned per-entry `image/env/volumes/restart_policy`; spec §F.3 has `layer/required_capabilities/default_capabilities/singleton/reserved` only. Launcher-oriented fields are computed by `RegionRegistry.docker_spec(name)` helper.
2. **Container naming**: spec §G.7 shows `hive-region-<name>` but plan and registry use `hive-<name>`. Plan wins; documented inline.
3. **§E.5 rollback retry**: plan mentions "up to N=3 times"; spec §E.5 pseudocode is single-shot. Impl is single-shot mechanism; supervisor owns the retry counter via circuit breaker (§E.4).
4. **§E.6 ACL rendering**: spec pseudocode renders `_base.j2` once; the real template contains `{{ region }}` and mosquitto ACLs need `user <name>` per section. Impl renders `_base.j2` per region.
5. **§E.10 codechange sidecar**: spec mentions a short-lived privileged container; v0 uses in-glia `git apply` with RW bind-mount. Documented as v0 reduction.
6. **§E.11 spawn ACL stub**: spec says "parameterized by `initial_subscriptions`"; v0 copies the stub verbatim (region's own cognitive namespace grant only). Document that external-namespace subscriptions need approved code-change to amend the template.
7. **§E.11 `config_loader.serialize`**: helper doesn't exist in codebase; spawn scaffolder uses direct `ruamel.yaml` dump.
8. **§E.3 clock choice**: spec §E.3 says `time.time()` literal; monotonic would be more robust but spec wins. Injectable clock preserved for NTP-resilient callers.
9. **§E.11 launcher naming**: spec uses `launcher.start(name)`; Launcher API is `launch_region(name)`. Same semantics.

**Follow-up items worth tracking (non-blocking):**

- **Docker-events listener** for exit-code-based restart dispatch is not wired. `Supervisor.on_region_exit(region, exit_code)` is implemented and tested but has no docker-events subscriber yet. v0 relies on heartbeat-miss detection (§E.3). Adding the listener is a small `docker.events.listen()` task inside `glia/__main__.py`.
- **Component tests deferred** (all skip-marked with rationales): `test_launcher_docker.py`, `test_spawn_executor.py` (component), `test_supervisor.py` (component). Each needs a real broker + built `hive-region:v0` image + region-config fixture chain. Un-defer together once Phase 8 lands.
- **Bridges not wired** into `glia/__main__.py`. Current implementation treats them as standalone modules with injected publish callables. Wiring is a small follow-up: instantiate `RhythmGenerator` + `InputTextBridge` (the two enabled-by-default bridges) inside `_main()`, start them alongside supervisor, stop in the finally block.
- **Bridge `handle_message` dispatch**: `SpeakerBridge` and `MotorBridge` expose `handle_message(envelope)` but have no MQTT subscription wiring yet. Defer with bridge-wiring follow-up.
- **Image tag rollback (§E.10)**: `_rollback_image` re-tags `hive-region:v0-prev` → `hive-region:v0`. If the previous image was pruned, rollback fails silently. Worth a `docker.images.get()` guard in future.
- **`test_sweep_loop_runs_and_increments_misses`**: deleted during 5.4 review as timing-sensitive. Replace with event-based signaling if we want an actual loop-body test.
- **Registry duplicate-name detection**: removed the dead guard during 5.2 review. `ruamel.yaml typ="safe"` last-wins on duplicates. If we want actual duplicate detection, switch to `typ="rt"`.
- **spawn_executor config.yaml shape**: scaffold writes a minimal subset (region/role/llm/capabilities). The region's own `config_loader.load_config` validates fully on boot. If that rejects the scaffolded config for a missing default, the region will exit 2 → rollback. Monitor when Phase 8 regions spawn their first test.

**Cumulative gotchas (Phase 5 additions):**

- `docker.errors.NotFound` is a subclass of `APIError`. Several glia modules had bugs where `except APIError` accidentally swallowed NotFound cases. Pattern: always catch NotFound explicitly BEFORE `except APIError`.
- `ACL_PATH` / `ACL_TMP_PATH` module constants removed from `glia/acl_manager.py` during 5.5 review — they weren't referenced in production code (bus_dir is injected).
- `os.O_BINARY` pattern required for ACL writes on Windows (same as `self_modify._atomic_write_text`) — mosquitto config rejects CRLF line endings in some builds.
- Docker mem stats include page cache. Real memory pressure: subtract `stats.inactive_file` (cgroups v2) or `stats.cache` (v1). Fixed in 5.8 review.
- `aiomqtt` v2 uses `identifier=` keyword, not v1's `client_id=`.
- `docker.containers.run(..., volumes=...)` keys must use forward slashes on Windows too — Docker daemon is Linux. Use `f"./regions/{name}"` literals, not `Path("./regions") / name` (backslashes on Windows).
- `ruamel.yaml typ="safe"` last-wins on duplicate keys; duplicate detection requires `typ="rt"`.
- Supervisor's restart handlers must be fire-and-forget via `asyncio.create_task` + `_pending_tasks` set; otherwise long backoff delays (up to 300s) stall the routing loop. Same pattern applies to any future long-running task handler.
- Spec §E.5 single-shot rollback; supervisor owns retry budget via §E.4 circuit breaker. Don't conflate.
- Codechange rollback must relaunch ALL partially-rolled regions on old tag, not just the failed-and-subsequent ones.
- `_restart_with_backoff(exit_code=None)` (heartbeat-miss path) counts toward the crash budget. Spec grey-area; documented as conservative choice.

**Spec updates during Phase 3:**
- §A.4.1 — `LifecyclePhase(str, Enum)` → `LifecyclePhase(StrEnum)` (commit `bd77a61`, Larry-approved).
- §D.5.7 / §D.10 — dropped invalid `--allow-empty=never` git flag; git's default behavior matches intent (commit `35b2863`, Larry-approved at start of Wave C).
- §F.10 — merge-ambiguity row rewritten to match §F.5's recursive `_deep_merge` semantics (commit `35b2863`).

**Spec-vs-plan deviations resolved during Wave C (implementation follows spec):**

1. **§A.7.4 `write_memory` split**: plan called it one tool; spec has `write_stm` + `write_ltm`. Impl follows spec. Plan prose should be tightened if/when someone re-reads.
2. **§C.6 caching model**: plan Step-4 prose said "prompt prefix cache, LRU, 10k entries"; spec describes **provider-side** caching via Anthropic `cache_control` markers. `llm_cache.py` injects markers (§C.6), doesn't maintain a local LRU. Document mismatch, follow spec.
3. **§B.9 MQTT v5 session**: spec code block says `clean_session=False` + `ProtocolVersion.V5`; paho-mqtt rejects that combo. Impl uses MQTT v5 equivalent: `clean_start=False` + `SessionExpiryInterval=3600`, matching §B.11's "1 hour" policy. Worth a future spec-edit to §B.9 code block.
4. **§D.5.2 `needs_restart` narrowing**: spec pseudocode returns `committed_restart` whenever `needs_restart=True`; plan Step-1 says "restart only when handlers or subscriptions changed". Impl combines both: `needs_restart AND (handlers_changed OR prompt_changed)`. Acceptable narrowing — an LLM returning needs_restart without concrete changes would be nonsense.
5. **LtmMetadata synthesis in `write_ltm`**: spec §A.7.4 lists minimal signature `(filename, content, reason)`; §D.3.3 requires metadata for indexing. Impl added optional kwargs `topic/importance/tags/emotional_tag` with low-signal defaults; ACC/mPFC can override. Spec §A.7.4 worth updating to show these kwargs.
6. **REQUIRES_CAPABILITY permissiveness** (`handlers_loader`): plan prose said `str`; spec §A.6.1 says `list[str]`. Impl accepts both and coerces bare string → single-element tuple. Superset of spec.
7. **§D.5.6 commit message fields**: spec `CommitResult` shows `files_changed/lines_added/lines_removed`; `GitTools.commit_all` returns only `sha` (minimal v0 surface from Task 3.10). Spec §A.7.5 / §D.5.7 lists the additional fields but they're not wired.
8. **§B.5 retained-flag preservation across MQTT disconnect**: initial impl lost retain intent in the out-queue (reviewer found); fix preserves `(envelope, qos, retain)` tuples through the drain loop.

**Follow-up items worth tracking (non-blocking):**
- `MqttClient` outbound `_out_queue` drain: on in-flight disconnect mid-drain, appendleft works but no outer re-trigger loop (`_reconnect_loop` has already returned). Documented in code.
- `LlmError.cause` — spec §C.8 shows `LlmError(..., cause=e)` but the class doesn't accept `cause=`. Used `raise ... from exc`. Works, but spec code block is misleading.
- Runtime shutdown path has no overall timeout — slow task cancellation during `runtime.shutdown()` could hang the process. Spec §A.4.6 mandates `shutdown_timeout_s` (30s default) with exit 137; not wired through `_main`/`shutdown`.
- `region_template/__main__.py` — Windows platform glue (SelectorEventLoop policy + SIGBREAK handler). Works; adds ~40 lines to keep cross-platform parity.
- Stream-cost via `litellm.cost_per_token` on pinned `litellm==1.54.x`. If version drifts to 1.60+, the signature may change; `>=1.54,<2` pin mitigates.
- Test coverage gaps noted during reviews (all non-blocking): multi-tool streaming delta accumulation, edge-case sandbox paths with null bytes, `_sleep_grant_event` staleness across sleep cycles, `_subscribed_handler_filters` tracking when `subscribe()` itself raises.

**Known gotchas for future sessions (cumulative):**
- Host Python env lacks `pydantic`, `structlog`, `ruff`, `ruamel.yaml`, `jsonschema`, `pytest-asyncio`, `testcontainers`, `GitPython`, `aiomqtt`, `litellm` on fresh shells. Implementers pip-install on demand. `scripts/bootstrap_env.sh` exists — still unused.
- structlog 25.x hardcodes `warn` → `warning` internally; `region_template/logging_setup.py` installs `_remap_warning_to_warn` processor to satisfy spec §H.1.2's lowercase-`warn` requirement.
- `ConnectionError` in `region_template/errors.py` intentionally shadows the stdlib — always reference fully-qualified or import-alias.
- `LifecyclePhase` is `StrEnum` (Python 3.11+); `str(phase)` returns lowercase.
- `tool_use: "wizard"` must raise `ConfigError` — JSON schema + Pydantic enforce via `Literal["none","basic","advanced"]`.
- Ruff config lives at `C:/repos/hive/pyproject.toml` — package-specific `region_template/pyproject.toml` MUST NOT re-declare tool blocks.
- `MemoryStore`'s STM TTL uses `time.monotonic()` → TTL countdown restarts across process restarts.
- `LlmError(*args, retryable=bool)` — first positional is the kind string; `.kind` property exposes it (added during Wave C review).
- `MemoryStore.stm_size_bytes_sync()` is a lock-free sync helper for the runtime's sleep monitor; `stm_size_bytes()` is async.
- `litellm` pinned to `>=1.54,<2` in `region_template/pyproject.toml` — pre-1.54 has Windows long-path extraction issues; 1.60+ may have `cost_per_token` signature drift.
- Windows-specific: `_atomic_write_text` in `self_modify.py` uses `O_BINARY` to avoid LF→CRLF translation. Component tests under `tests/component/` force `WindowsSelectorEventLoopPolicy` (aiomqtt needs `add_reader`/`add_writer`) and disable testcontainers Ryuk (port 8080 probe fails on Windows Docker Desktop).
- `region_template/__main__.py` on Windows uses `signal.signal(SIGBREAK, …)` + `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` for graceful shutdown; POSIX uses `SIGTERM`/`SIGINT` via `loop.add_signal_handler`.
- `compileall` writes `__pycache__/` into region git repo; sleep sets `PYTHONDONTWRITEBYTECODE=1` AND cleans up pyc files post-check AND `GitTools._ensure_repo` bootstraps a `.gitignore` with `__pycache__/` + `*.pyc`.
- Two stray files at repo root (`=2.6`, `=24`) are pip-install typos — leave them alone.
- **Flat layout ≠ flit:** `shared/pyproject.toml` and `region_template/pyproject.toml` use `flit_core` but the flat layout (`__init__.py` directly beside `pyproject.toml`, no nested module directory) fails flit's module-discovery check. `pip install -e ./shared` raises `ValueError: No file/folder found for module shared`. The Dockerfile (task 4.1) works around this via `PYTHONPATH=/hive` + explicit dep list; `scripts/setup.sh` does the same. A proper installable layout (either subdir reorg or `setuptools` with `package-dir`) is still a future cleanup.
- **Dockerfile (`region_template/Dockerfile`, task 4.1):** base is `python:3.11-slim-bookworm@sha256:9c6f908…`. Adds `git` (required by `git_tools.py` subprocess) and `tini` (signal forwarding + zombie reaping for sleep `compileall` subprocess). Non-root user `hive:1000`. Entry: `tini -- python -m region_template`.

**Execution model:** `superpowers:subagent-driven-development` — fresh implementer subagent per task; spec review (always) + code quality review (for real code; skip for config-only); commit-per-task; checkpoint with user every ~10-15 tasks or at wave boundaries.

### Goal

Implement Hive v0 per the plan. Multi-session; use parallel dispatched agents for the 14-region scaffolding work in Phase 8.

---

## Phase 6 — Bootstrap CLI — COMPLETE (2026-04-20)

Both tasks landed on `main` in a 3-commit slice (impl + review fixes per task). 702 tests passing (691 unit + 11 integration). `ruff check region_template/ glia/ tools/ tests/` clean. `docker compose config` validates.

**Per-task status:**

| Task | File | Status | Commits |
|---|---|---|---|
| 6.1 | `docker-compose.yaml` | ✅ | `1632cba` — exact copy of spec §G.7 (broker + glia services; regions launched at runtime by glia, not compose). Config-only; spec-review only (skipped code-quality review per CLAUDE.md). |
| 6.2 | `tools/hive_cli.py` + `tests/integration/test_hive_cli.py` | ✅ | `e385434` impl, `2ef219f` review fixes. Typer CLI. 11 integration tests (all mocked; no docker daemon required). |

**V0 CLI surface (plan narrowing of spec §E.12):** `up [--dev | --no-docker --region NAME]`, `down [--fast]`, `status`, `logs SERVICE [--tail N] [--no-follow]`. Fuller §E.12 surface (`restart`, `sleep`, `kill`, `acl`, `spawn`, `shell`, `inspect`) deferred.

**Spec-vs-plan deviations carried as follow-ups (non-blocking, flagged by spec review):**

1. **`hive down` skips the §G.3 / §E.13 MQTT broadcast sequence.** Spec prescribes publishing `hive/broadcast/shutdown` with `grace_s=30`, observing heartbeats, THEN `docker stop` per service. V0 collapses that to a single `docker compose down`. Defensible because regions don't exist yet to respond to the broadcast; wire up once Phase 8 regions land. The `--fast` flag (`docker compose down --timeout 1`) is the v0 approximation of the "skip grace" escape hatch.
2. **`hive up` skips §G.1 steps 1/3/4/6/7** (`.env` validation, `bus/acl.conf` render, `bus/passwd` render, region launch in dependency order, heartbeat verification). All of those are glia's responsibility once it's running (§E.1–E.6), so `hive up` is the narrow "start broker and glia; let glia do the rest" shape. Add `.env` validation as a small hardening pass when convenient.
3. **`hive up --no-docker`** launches a local mosquitto binary if present (prefers `bus/mosquitto.conf` via `-c`) and a single `python -m region_template --config regions/<name>/config.yaml` process. Cross-platform signal handling: SIGINT unconditional; SIGTERM POSIX-only; SIGBREAK installed on Windows when available. On launch, a `try/finally` guarantees broker cleanup (`terminate()` → `wait(timeout=5)` → `kill()`).

**Follow-up items worth tracking (non-blocking, from code review):**

- `hive down` should eventually publish `hive/broadcast/shutdown` via an aiomqtt one-shot client before invoking `docker compose down`, per spec §G.3.
- `hive up` should validate `.env` presence and flag missing required keys before invoking `docker compose up -d`, per spec §G.1 step 1.
- `status` parser warns on malformed NDJSON (post-fix) but doesn't distinguish "docker not running" from "no services yet"; could be sharper.
- `logs --follow` default can hang a non-TTY invocation (CI). Test suite covers both branches; no bug, just a footgun.
- `CliRunner` default parity: tests now use `mix_stderr=False` unconditionally; if typer ever drops the kwarg, tests break loudly instead of silently combining streams (intentional).
- `_VALID_LOG_SERVICES` hardcoded to `("broker", "glia")`. Adding a third compose service requires editing the tuple and the validator; consider deriving from compose config in Phase 7.

**Cumulative gotchas (Phase 6 additions):**

- `docker compose ps --format json` emits NDJSON (one object per line) on modern compose; older versions may emit a JSON array. Impl type-checks the parsed payload and handles both shapes.
- `version: "3.9"` at the top of `docker-compose.yaml` is deprecated by compose v2 (emits a warning) but kept per spec §G.7. Will drop when spec §G.7 is revised.
- `$$SYS/#` in the healthcheck is the correct escape for a literal `$` in compose YAML; `$SYS` would be interpolated as an env var.
- `typer 0.23` + `click 8.1` both ship via transitive deps; no new pins required.
- `hive up --no-docker` on Windows: `signal.signal(SIGTERM, ...)` is a no-op for anything other than process-termination-from-console; use `SIGBREAK` instead. SIGINT works on both platforms.
- Integration tests live under `tests/integration/`; the `integration` pytest marker already existed in root `pyproject.toml`. `testpaths = ["tests"]` picks them up automatically, so `python -m pytest tests/unit/` is the correct invocation to run unit-only.

### Prompt for next Phase-7/8 session (Phases 3–6 DONE)

Paste the following into a new Claude Code session:

---

```
You are continuing Hive v0 at C:/repos/hive/ on branch `main`.
Phases 3 (Runtime DNA), 4 (Region Docker image), 5 (Glia), and
6 (Bootstrap CLI) are COMPLETE. Both `hive-region:v0` and
`hive-glia:v0` images build; 691 unit tests + 11 integration
tests pass; ruff clean. Next: Phase 7 (Observability) or
Phase 8 (14-region scaffolding). Larry picks.

## Start here

1. Read `docs/HANDOFF.md` in full. The Phase-3/4/5/6 progress tables are the
   authoritative state snapshot. The "Follow-up items worth tracking"
   sections under each phase list non-blocking cleanup candidates.
2. Confirm git state:
     git fetch origin && git checkout main && git log --oneline -10
   Expected HEAD is `2ef219f cli: hive_cli review fixes` or newer.
3. Confirm environment (assumes `.venv` on Python 3.12 from scripts/setup.sh):
     cd C:/repos/hive && source .venv/Scripts/activate
     python -m pytest tests/unit/ -q                 # 691 passed
     python -m pytest tests/integration/ -q          # 11 passed
     python -m ruff check region_template/ glia/ tools/ tests/
     docker compose config                           # validates
4. Pick the next phase and read its plan section:
     docs/superpowers/plans/2026-04-19-hive-v0-plan.md
   - Phase 7 (Tasks 7.1-7.4): observability — log aggregator, traffic
     inspector, metric dashboards, debug tooling. Small. PARALLEL-OK.
   - Phase 8 (Tasks 8.1-8.14): 14-region scaffolding. **PARALLEL-OK** —
     each region is independent now that glia + CLI exist. Good fit
     for `superpowers:dispatching-parallel-agents`.

## Suggested order (Larry's call)

- **Phase 8 first** — the big push: 14 regions scaffolded in parallel
  dispatches (3-4 at a time per handoff). Each region is independent
  and can be tested against the real `hive-region:v0` + `hive-glia:v0`
  images. `hive up` + `hive status` now exist for smoke-testing. The
  component tests deferred in Phase 5 can be unblocked here.
- **Phase 7 first** — observability is nice-to-have before Phase 8
  regions start behaving strangely. Optional; can defer.

Recommendation: **Phase 8 next** — CLI is landed; compose lets you
smoke-test each region as it lands; Phase 7 is backfillable anytime.

## Execution model — unchanged

`superpowers:subagent-driven-development`:
- Fresh implementer subagent per task.
- Spec-compliance review after each implementer.
- Code-quality review after spec-review passes (skip for config-only).
- Fix loop until both reviews approve.
- One commit per plan task + review-fix commits as needed.
- HEREDOC commit messages with trailer:
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
- Verify `python -m ruff check` clean after each task.

For Phase 8's parallel scaffolding: use
`superpowers:dispatching-parallel-agents` and dispatch 3-4 region
implementers at a time (not all 14 — too much context to review in
parallel). Each implementer gets the region's starter prompt +
capability profile + a minimal test that boots against a fake broker.

## Known gotchas (inherit cumulatively)

See HANDOFF.md's "Cumulative gotchas (Phase 5 additions)" section
plus the Phase-3 "Known gotchas for future sessions" — ~25 items
total spanning env setup, Windows platform nuances, library pins,
docker-SDK quirks (NotFound/APIError, memory cache), aiomqtt v2,
and repo hygiene. The `=2.6` / `=24` stray files at repo root are
still pip-install typos, still left alone.

Spec-vs-plan deviations are catalogued in three sections: Phase-3
Wave C (8 items touching §C/§B/§A.7/§D.5), Phase 5 (9 items touching
§E and §F), and Phase 6 (3 items touching §G.1/§G.3/§E.12 — v0
CLI narrowings). Read all three before the first Phase-7/8
implementer dispatch.

## Deliverable at end of session

- More tasks committed on `main`.
- Unit + component suites passing.
- Ruff clean.
- HANDOFF.md updated with phase completion.
- Clear checkpoint summary for Larry.

## Reminders

- Larry designs before coding; the spec + plan are authoritative.
- Biology is the tiebreaker (P-I).
- Infrastructure does not deliberate; cognition does not execute
  infrastructure. Glia is a mechanism; regions are the cognition.
- Commit-per-task is mandated by Principle XII.
- Auto mode may be active — execute on routine decisions; pause only
  for spec conflicts, risky ops, or Larry's explicit checkpoints.
```

---

## Maintaining this file

Every session that completes significant work must update this HANDOFF.md:

1. Bump `Last updated` to today's date
2. Update `Current phase` in the header
3. Move completed phases to ✅ and add brief summary
4. Update git log section for the current phase
5. Note any architectural clarifications, gaps filled, or new open questions
6. Commit the HANDOFF.md update as part of the session's work

**This file is the contract for future-you (or future-Claude).** Keep it honest.

---

## Open questions / known gaps

As Phase 2 proceeds, add observations here:

- *(none yet — populated during spec writing)*

---

## Appendix: File map

```
C:/repos/hive/
├── README.md                      # Project overview
├── .gitignore
├── docs/
│   ├── HANDOFF.md                 # This file — session continuity
│   ├── principles.md              # 16 constitutional principles
│   ├── architecture.md            # System architecture + 13 mermaid diagrams
│   ├── starter_prompts/           # 14 region starter prompts
│   │   ├── README.md
│   │   ├── medial_prefrontal_cortex.md
│   │   ├── prefrontal_cortex.md
│   │   ├── hippocampus.md
│   │   ├── anterior_cingulate.md
│   │   ├── thalamus.md
│   │   ├── association_cortex.md
│   │   ├── insula.md
│   │   ├── basal_ganglia.md
│   │   ├── motor_cortex.md
│   │   ├── broca_area.md
│   │   ├── visual_cortex.md
│   │   ├── auditory_cortex.md
│   │   ├── amygdala.md
│   │   └── vta.md
│   └── superpowers/
│       ├── specs/
│       │   └── 2026-04-19-hive-v0-design.md   # [to be written in Phase 2]
│       └── plans/
│           └── 2026-04-19-hive-v0-plan.md     # [to be written in Phase 3]
├── region_template/               # [to be written in Phase 4 — DNA]
├── regions/                       # [to be written in Phase 4 — 14 regions]
├── glia/                          # [to be written in Phase 4 — infrastructure]
├── bus/                           # [to be written in Phase 4 — broker config]
└── shared/                        # [to be written in Phase 4 — utilities]
```
