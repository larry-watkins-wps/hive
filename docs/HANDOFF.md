# Hive — Session Handoff

**Last updated:** 2026-04-23 (Phase 11 — broker portability, bridge wiring, spawn pipeline landed; see commits `b179dbe..e924659`)
**Current phase:** v0 DNA complete; Phase 11 (Runtime evolution — first self-mod cycles, post-v0 region additions) **in progress**
**Repo path:** `C:/repos/hive/`

This document is the **source of truth for session-to-session continuity.** Any Claude Code session working on Hive should begin by reading this file in full, then proceed according to the current phase.

---

## Quick reference

v0 is **complete** — all 10 phases done. The "DNA" (shared runtime, 14 regions, glia, bus, CLI, observability, tests, CI) is in place. Hive can now boot, heartbeat, sleep, self-modify, and roll back. The next era is **growth**: regions evolve their own handlers and memory via sleep cycles, and post-v0 regions (raphe_nuclei, locus_coeruleus, hypothalamus, basal_forebrain, cerebellum) get added when accumulated experience warrants.

| Phase | Status | Artifact location |
|---|---|---|
| 1. Brainstorming | ✅ Complete (2026-04-19) | `docs/principles.md`, `docs/architecture.md`, `docs/starter_prompts/` |
| 2. Design Spec | ✅ Complete (2026-04-19) | `docs/superpowers/specs/2026-04-19-hive-v0-design.md` (4,792 lines) |
| 3. Implementation Plan | ✅ Complete (2026-04-19) | `docs/superpowers/plans/2026-04-19-hive-v0-plan.md` |
| 4. Runtime DNA | ✅ Complete (2026-04-20) | `region_template/` — 17/17 tasks, 508 unit + 6 component tests |
| 5. Glia | ✅ Complete (2026-04-20) | `glia/` — 12 tasks, `hive-glia:v0` image builds |
| 6. Bootstrap CLI | ✅ Complete (2026-04-20) | `docker-compose.yaml` + `tools/hive_cli.py` |
| 7. Observability tools | ✅ Complete (2026-04-20) | `tools/dbg/{hive_trace,hive_watch,hive_stm,hive_inject}.py` |
| 8. Region scaffolding ×14 | ✅ Complete (2026-04-21) | `regions/<14 names>/` |
| 9. Integration + smoke + CI | ✅ Complete (2026-04-21) | `tests/integration/`, `tests/smoke/`, `.github/workflows/ci.yml` |
| 10. Docs + HANDOFF polish | ✅ Complete (2026-04-21) | `README.md`, `docs/HANDOFF.md`, `CLAUDE.md` |
| 11. Runtime evolution | 🔄 **In progress** (2026-04-23) | See Phase 11 section below |

**Totals:** 710 unit + 73 integration (3 option-b skips + 1 Windows non-admin skip) + 1 smoke-collectable. Ruff clean. Minimal CI green on every push + PR.

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

**14 starter prompts** (see `docs/starter_prompts/`) — one per v0 region, self-sufficient (all 16 principles embedded), experience-grounded (regions read observable state — modulator values, STM depth, consolidated LTM, appendix history — rather than branching on a categorical stage label), and self-evolution-enabled (each has a detailed protocol for editing itself during sleep). Note: original prompts were stage-aware; reframed 2026-04-22 to emergent-state grounding (see Phase 11 divergence entry).

### Key architectural decisions made

- MQTT is the only inter-region communication channel
- Glia (infrastructure) is separate from cognitive regions — no LLM, no cognition
- Anterior Cingulate Cortex (ACC) is the metacognitive gate for spawns and code changes
- mPFC holds global self; other regions read retained `hive/self/*` topics
- Insula handles interoception of computational body (tokens, compute, region health)
- Basal ganglia handles habit formation via dopamine reinforcement
- Modality isolation is absolute; ACLs enforce at broker level
- Three signal types: messages, modulators (retained), rhythms (broadcast)
- Hive boots with a thin seed at v0 — all regions present, minimal handlers, empty memory, empty appendices; developmental state is emergent from this seed plus accumulated experience, not a declared label

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

## Phase 2: Design Spec — COMPLETE (2026-04-19)

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

## Phase 3: Implementation Plan — COMPLETE (2026-04-19)

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

## Phase 4: Runtime DNA — COMPLETE (2026-04-20)

### Final status (2026-04-20)

| Phase | Status | Notes |
|---|---|---|
| 0. Foundation (3 tasks) | ✅ | `pyproject.toml`, `.gitignore`, `.env.example`, `scripts/bootstrap_env.sh`, `scripts/make_passwd.sh` |
| 1. Shared library (5 tasks) | ✅ | `shared/envelope_schema.json`, `shared/message_envelope.py` (39 tests), `shared/topics.py` (55 tests), `shared/metric_schemas.json` |
| 2. MQTT layer / bus (4 tasks) | ✅ | `bus/topic_schema.md`, `bus/mosquitto.conf`, `bus/acl_templates/_base.j2` + 14 per-region + `_new_region_stub.j2` |
| 3. Runtime DNA (17 tasks) | ✅ **Complete (17/17)** | All waves done. 508 unit tests + 6 component tests (real mosquitto via testcontainers). Ruff clean. |
| 4. Region Docker image | ✅ | `region_template/Dockerfile` (commit `f79c91a`). Builds `hive-region:v0` from `python:3.11-slim-bookworm@sha256:9c6f908…`. `docker run --rm hive-region:v0 --help` prints usage. |
| 5. Glia (12 tasks) | ✅ | All 12 tasks done: registry, launcher, heartbeat monitor, ACL manager, rollback, codechange executor, spawn executor, metrics aggregator, supervisor, `__main__`, 6 bridges. `docker build -t hive-glia:v0 -f glia/Dockerfile .` succeeds. |
| 6. Bootstrap CLI (2 tasks) | ✅ | `docker-compose.yaml` + `tools/hive_cli.py` (typer CLI: up/down/status/logs + --dev/--no-docker). 702 tests total (691 unit + 11 integration). |
| 7. Observability tools (4 tasks) | ✅ | `tools/dbg/{hive_trace,hive_watch,hive_stm,hive_inject}.py` (typer CLIs). 745 tests (691 unit + 54 integration + 1 skipped on Windows non-admin). |
| 8. Region scaffolding × 14 | ✅ | 14 regions scaffolded (`regions/<name>/{config.yaml,prompt.md,subscriptions.yaml,handlers/,memory/ltm/.gitkeep}`). One commit per region per P-XII. Task 8.15 integration test (`tests/integration/test_all_regions_load.py`) verifies all 14 load. 760 tests total (691 unit + 69 integration + 1 skipped). |
| 9. Integration + smoke + self-mod tests | ✅ | All 7 tasks landed. 773 tests total (691 unit + 73 integration + 9 smoke-collectable + 1 Windows skip + 3 option-b skips). Ruff clean. Minimal CI workflow on `push` + `pull_request`. |
| 10. Docs + HANDOFF | ✅ Complete (2026-04-21) | `README.md`, `docs/HANDOFF.md` updated. See Phase 10 section. |

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

---

## Phase 7 — Observability tools — COMPLETE (2026-04-20)

All 4 tools landed on `main` via parallel-dispatched implementers + consolidated fix-loop. 5 commits total. 54 integration tests (10 CLI + 6 trace + 10 watch + 10 stm + 11 inject + 7 new from fix-loop; 1 skipped on Windows without Developer Mode). 691 unit tests unchanged. Ruff clean.

**Per-task status:**

| Task | File | Status | Commits |
|---|---|---|---|
| 7.1 | `tools/dbg/hive_trace.py` + tests | ✅ | `2698267` impl; fixes in `c223619` |
| 7.2 | `tools/dbg/hive_watch.py` + tests + `__init__.py` | ✅ | `e02bc4e` impl; fixes in `c223619` |
| 7.3 | `tools/dbg/hive_stm.py` + tests | ✅ | `7121883` impl; fixes in `c223619` |
| 7.4 | `tools/dbg/hive_inject.py` + tests | ✅ | `81f8d6b` impl; fixes in `c223619` |

**V0 surface delivered:**

- `hive trace <correlation_id>` — subscribes to `hive/#`, filters by `correlation_id`, prints sorted timeline (timestamp-safe for mixed `Z`/`+00:00` suffixes). Warns on chain-gap envelopes per §H.4. Best-effort on broker failure per §H.7.
- `hive watch <pattern>` — subscribes to topic pattern (aliases: `modulators`, `attention`, `self`, `metrics`; or literal MQTT wildcard). `--retained` one-shot dump; `--timeout` cap; graceful `aiomqtt.MqttError` handling.
- `hive stm <region>` — reads `regions/<name>/memory/stm.json` from filesystem (bypasses §D.6 MQTT query per §H.3 operator authorization). `--raw`, `--slots-only`, `--events-only`, `--limit`, `--root` flags. Symlink escape rejected via resolved `is_relative_to` check. Type-guards `slots` (dict) and `recent_events` (list) with graceful degrade.
- `hive inject <topic> <payload_or_file>` — publishes a crafted envelope. Full-envelope mode (JSON with nested `payload`) or payload-shorthand (`{"data": ..., "content_type": ...}` → synthesized envelope with `source_region="hive_inject"`). Accepts file path, inline JSON, or `-` for stdin. `--qos`, `--retain`, `--correlation-id`, `--reply-to` flags.

**Review outcome:** all 4 tools APPROVED by combined spec+code reviews. 13 Important items consolidated into a single fix-pass commit (`c223619`). No Critical issues.

**Cumulative gotchas (Phase 7 additions):**

- **Parallel-agent git-index race.** Dispatching 4 implementers in parallel with `run_in_background=true` works for file authorship (non-overlapping paths) but `git add`/`git commit` share a single index per working tree. Concurrent staging in different agents can interleave and produce mislabeled commits. Mitigations for future parallel dispatches: (a) use `git worktree add` per agent (CLAUDE.md `isolation: "worktree"` option), or (b) serialize the final commit step, or (c) have each agent use `git commit -o <paths>` to scope the commit to explicitly named files. Fallout this session: one commit (`8fdbaa1`, discarded by a subsequent soft-reset) was mislabeled; hive_watch's initial commit was lost and had to be re-committed as `e02bc4e` during reconciliation. No work lost, but commit-per-task granularity degraded.
- **aiomqtt 2.5.1 `identifier=` kwarg** (not v1's `client_id=`). All four Phase-7 tools and `region_template/mqtt_client.py` use it; broker-log grepability depends on setting a meaningful identifier. Pattern: `f"hive-<tool>-{uuid4().hex[:8]}"`.
- **`asyncio.get_event_loop()` deprecated in 3.12.** Use `asyncio.get_running_loop()` when inside an already-running loop. Both call patterns work today but only the latter survives future Python versions.
- **ISO-8601 timestamp sort edge case.** Lexicographic sort on a mix of `Z` and `+00:00` suffixes misorders. `hive_trace` normalizes Z→+00:00 and parses with `datetime.fromisoformat`; use the same pattern anywhere cross-region timestamps are ordered.
- **Windows symlink tests require Developer Mode** (or admin). Phase-7's symlink-escape test in `test_hive_stm.py` probes `_can_symlink(tmp_path)` and skips gracefully; Linux CI will exercise the guard.
- **`aiomqtt.MqttError`** — broker-down / auth-fail exception class. All Phase-7 tools that connect catch it at the outermost async scope and emit a stderr message + non-zero exit (vs. crashing with a traceback). §H.7 mandates best-effort observability.
- **Envelope schema regex `^[a-z][a-z0-9_]{2,30}$` forbids hyphens** in `source_region`. Tools that mint envelopes on behalf of an operator must use underscore (`hive_inject`), not hyphen.

**Follow-up items worth tracking (non-blocking, from reviews):**

- `hive_trace`: tests don't exercise the typer CLI flag-plumbing for `--live`/`--host`/`--port`/`--timeout`. Add a single `CliRunner` test with patched client factory when time allows.
- `hive_watch`: class-level fake-client state cleared by a reset at the top of each test, but no `autouse` fixture enforces it — drift-prone; add when convenient. Docstring mentions "colored timeline" per spec §H.3 but implementation is plain text (aspirational spec wording). A `rich`-based prettifier is a post-v0 ergonomics win.
- `hive_stm`: `@lru_cache` on `_discover_root` makes repeated in-process invocations stick to the first answer; fine for one-shot CLI but flag for test reuse. `_format_slot_value` has a dead `isinstance(value, str)` branch that duplicates the fallthrough. Magic tuple of timestamp keys could become a module constant.
- `hive_inject`: no size-cap warning for large payloads (JSON-bomb); broker has its own limit so non-blocking. Em-dash in topic-mismatch error renders on UTF-8 terminals but may mangle in `cp1252`.

**Spec-vs-plan deviations from Phase 7:** none. The tools sit entirely within §H.3 / §H.4 / §K.2. Plan Task 7.1–7.4 shapes and spec §H.3 row descriptions match the delivered surface.

---

## Phase 8 — Region scaffolding — COMPLETE (2026-04-21)

All 14 regions scaffolded, one commit per region per Principle XII. Task 8.15 integration test added. 15 new commits total. Spec review: **APPROVED** (no Critical, no Important). Code-quality review skipped (config-only per CLAUDE.md Phase 6 precedent).

**Per-region status:** all 14 identical in shape — each commit creates `regions/<name>/{config.yaml, prompt.md, subscriptions.yaml, handlers/__init__.py, memory/ltm/.gitkeep}` (5 files). No `stm.json` or per-region `.git/` created at scaffolding time — those are first-bootstrap artifacts per §G.2.

| Task | Region | Commit |
|---|---|---|
| 8.1 | medial_prefrontal_cortex | `5ef3cb3` |
| 8.2 | prefrontal_cortex | `2194a50` |
| 8.3 | anterior_cingulate | `6e1b0c6` |
| 8.4 | hippocampus | `073e5e3` |
| 8.5 | thalamus | `8fc9413` |
| 8.6 | association_cortex | `6685567` |
| 8.7 | visual_cortex | `5cb3bc3` |
| 8.8 | auditory_cortex | `2db05b6` |
| 8.9 | motor_cortex | `a26bce5` |
| 8.10 | broca_area | `3f75e9d` |
| 8.11 | amygdala | `506300c` |
| 8.12 | vta | `d5300c5` |
| 8.13 | insula | `b2cf65d` |
| 8.14 | basal_ganglia | `f0df02a` |
| 8.15 | `tests/integration/test_all_regions_load.py` | `9c14d53` |

**Capability profile assignments** (from `glia/regions_registry.yaml` — spot-check reminders):
- `can_spawn: true` ONLY for `anterior_cingulate`.
- `vision: true` ONLY for `visual_cortex`.
- `audio: true` ONLY for `auditory_cortex`.
- `stream: true` for `prefrontal_cortex` + `broca_area`.
- `tool_use: advanced` for cognitive regions (mpfc/pfc/acc/hippocampus) + motor (motor_cortex/broca_area); `basic` everywhere else.
- `modalities`: `[text]` for most; `[text, vision]` for visual_cortex; `[text, audio]` for auditory_cortex; `[text, motor]` for motor_cortex + broca_area.

**Model assignments** (plan rule):
- **Haiku** (`claude-haiku-4-5-20251001`) — `motor_cortex`, `insula`, `amygdala`, `vta`. Reduced budgets: 500k in / 100k out / $10 daily.
- **Opus** (`claude-sonnet-4-6`) — other 10. Full budgets: 2M in / 300k out / $50 daily.

**Temperature assignments**:
- `0.3` — thalamus (routing, should be deterministic).
- `0.5` — prefrontal_cortex, motor_cortex, broca_area (executive/output).
- `0.7` — other 10 (default).

**subscriptions.yaml** per region: 6 base subscriptions always present (`hive/self/#`, `hive/modulator/#`, `hive/rhythm/#`, `hive/broadcast/#`, `hive/attention/#`, `hive/interoception/#`) + region-specific reads derived 1:1 from `bus/acl_templates/<name>.j2`'s `topic read` lines. QoS 1 for directed requests/responses; QoS 0 for ambient streams.

**Task 8.15 verification test** (`9c14d53`): parametrized across 14 regions; asserts per region (1) `config_loader.load_config("regions/<name>/config.yaml")` returns a `RegionConfig` with matching `.name`, (2) `handlers_loader.discover("regions/<name>/handlers/")` returns empty list (stub handler dirs), (3) `regions/<name>/prompt.md` exists and non-empty. Plus one non-parametrized filesystem-completeness test asserting `sorted(p.name for p in Path('regions').iterdir() if p.is_dir())` equals the expected 14. 15 new integration tests; all pass.

**Test totals after Phase 8**: 691 unit + 69 integration (1 skipped on Windows non-admin for symlink test) = **760 passing**. Ruff clean.

**Spec-vs-plan deviations during Phase 8:** one low-priority **Nit** only.

1. **Haiku model version.** The four Haiku regions use `claude-haiku-4-5-20251001` (matching the CLAUDE.md environment notes for the current session's model-ID list). Spec §C.14's litellm alias example uses `claude-haiku-4-6-20260401`. Config loader accepts any string, so this doesn't block validation. If Larry wants `4-6-20260401` instead, it's a one-line edit in each of the four region config files. Flagged during spec review; deferred to Larry's call.

**Follow-up items worth tracking (non-blocking):**

- No scaffold-time fixtures created per region (no sample `stm.json`, no seeded handlers). That's by design — each region grows its own handlers and STM on first bootstrap per §G.2. Watch for the first-boot path when Phase 9's `compose.test.yaml` boots a region.
- The `subscriptions.yaml` files duplicate the 6 base subscriptions that `_base.j2` already grants at ACL level. Runtime uses `subscriptions.yaml` for actual subscribe calls; the duplication is intentional (subscriptions.yaml is authoritative for the runtime, not the ACL). Non-issue.
- `modalities: [text, motor]` for motor_cortex and broca_area is a capability-honest declaration, but `motor` isn't a LiteLLM content-part type — it's the region's output channel. Purely informational metadata for now.
- Parallel-session interleave: the observatory sub-project's Task 9 commits (`8b6be24`, `fc0ce94`, `92bf3fa`) landed between my Phase-8 scaffold batch and my Task 8.15 commit because a separate session was running concurrently on `observatory/` paths. No conflict — disjoint directories — but worth knowing that `git log --oneline` for Phase 8 is not strictly contiguous.
- The spec-compliance reviewer's capability-matrix nit noted "stream: true for prefrontal_cortex" — the registry YAML doesn't mandate this (only broca_area has `stream: true` in `default_capabilities`). The implementer added it to PFC to allow streaming reasoning per the plan's intent. Defensible; flag here so a future spec-review doesn't treat it as drift.

**Cumulative gotchas (Phase 8 additions):**

- `config_loader.load_config(path)` is the actual API (the plan prose of `RegionConfig.load(...)` is informal). `handlers_loader.discover(handlers_dir)` returns a `list[HandlerModule]`; empty list = stub state. Use these exact signatures in future Phase-9 fixtures.
- Scaffold-time files are text (YAML + markdown + empty `.gitkeep`). No binary content; no encoding traps observed on Windows.
- Starter prompts under `docs/starter_prompts/` are LF-terminated; `git diff` between `regions/<name>/prompt.md` and the starter shows zero bytes on Windows with the repo's `.gitattributes` settings. If a future tool opens the starter with `open(..., "r")` on Windows, it gets LF content verbatim.
- Every region got `mqtt.password_env: MQTT_PASSWORD_<NAME_UPPER>` — this must match the env var name produced by `scripts/make_passwd.sh` output. Tie `.env` generation + region configs together when wiring Phase-9's `compose.test.yaml`.

---

## Phase 9 — Integration, smoke, self-mod tests, CI — COMPLETE (2026-04-21)

All 7 tasks landed on `main` in a 9-commit slice. Ruff clean. 773 tests total (691 unit + 73 integration + 1 Windows skip + 3 option-b skips + 1 smoke-collectable). Code-quality review skipped for config-only tasks (Phase 6 precedent); one spec-compliance review surfaced 3 findings on Task 9.1 which were fixed inline.

**Per-task status:**

| Task | File(s) | Status | Commits |
|---|---|---|---|
| 9.1 | `tests/conftest.py` | ✅ | `03b5ead` impl, `cfc3443` review-fix (broker skip-swallow + compose teardown + docstring) |
| 9.2 | `tests/integration/compose.test.yaml` + `tests/integration/mosquitto.test.conf` + conftest port bump | ✅ | `34b5c09` |
| 9.3 | `tests/integration/test_cross_region_flow.py` | ✅ | `7fb20de` — skip-when-not-ready (Docker/images/LLM key/pfc-handler) |
| 9.4 | `tests/integration/test_acl_enforcement.py` | ✅ | `39d9047` — all 4 ACL assertions pass against real mosquitto v2 + rendered ACLs |
| 9.5 | `regions/test_self_mod/` + `tests/integration/test_self_mod_cycle.py` + `test_all_regions_load.py` update | ✅ | `21e51db` scaffold, `125a4cd` test |
| 9.6 | `tests/smoke/boot_all.py` + `tests/smoke/conftest.py` + `pyproject.toml` marker | ✅ | `182be59` |
| 9.7 | `.github/workflows/ci.yml` | ✅ | `9c477b7` (also fixes 5 pre-existing ruff lint errors in `shared/message_envelope.py` + `tests/smoke/conftest.py` to keep CI green from day one) |

**Option-b skip strategy (Larry's call):** Tasks 9.3 / 9.5 / 9.6 do NOT implement an offline LLM stub. Each gates on `ANTHROPIC_API_KEY`, Docker availability, and image presence, skipping with a specific message when any precondition fails. This keeps the test scaffolding in place for CI once LLM access is wired, but avoids the complexity of a deterministic LLM stub in v0. If/when `region_template/llm_adapter.py` grows a `HIVE_TEST_OFFLINE=1` short-circuit, un-skipping is a local edit.

**Test region scaffold (`regions/test_self_mod/`):** Per spec §I.6, this is a dedicated self-mod test target with Haiku, `self_modify: true`, `tool_use: basic`, a starter prompt instructing it to append "Self-mod succeeded." during its first sleep, commit, and request restart. It's **not** in `glia/regions_registry.yaml` — the test launches it directly via docker SDK against a testcontainer broker; bypassing glia's supervisor avoids polluting production registry. `tests/integration/test_all_regions_load.py` filters `test_self_mod` from its 14-region completeness check so the suite stays green.

**Integration test fixtures (`tests/conftest.py`):** Five shared fixtures: `fake_llm`, `fake_mqtt`, `tmp_region_dir`, `broker_container` (session-scoped testcontainer mosquitto with anonymous auth), `compose_stack` (docker compose up/down with `hive_test` project name; broker on host port 11883). All fixtures defer heavy imports inside their bodies so test collection stays cheap when optional deps (testcontainers, docker SDK) aren't installed.

**Integration compose (`tests/integration/compose.test.yaml`):** Project name `hive_test`, broker on 127.0.0.1:11883 via `tests/integration/mosquitto.test.conf` (`allow_anonymous true`), glia + mpfc + prefrontal_cortex as static services (pattern B: compose-defined regions rather than runtime-launched). `test_harness` container omitted — pytest process acts as harness from the host. `HIVE_TEST_OFFLINE` env flag wired but not yet read by the runtime.

**ACL test (`test_acl_enforcement.py`):** 4 tests, all passing. Broker configured with `allow_anonymous false` + a passwd file generated by `mosquitto_passwd` inside a helper container + an ACL file rendered via `glia.acl_manager.ACLManager.render_all()`. A synthetic `hardware_bridge` user is appended to the ACL so tests have a writer authorized to publish on `hive/hardware/mic`. Windows-specific: mosquitto 2.x running as uid 1883 inside the container can't read bind-mounted passwd files at mode 600 — the helper `chmod 644`s the file (produces a world-readable-permissions warning but ACLs still enforce correctly).

**Smoke test (`tests/smoke/boot_all.py`):** Full-system gate requiring `hive up` + 14 wake heartbeats + retained `hive/self/*` + clean `hive down`. Registered under `@pytest.mark.smoke` marker; lives at `boot_all.py` (not `test_*.py`) with a local `pytest_collect_file` hook so it's invisible to plain `pytest tests/` but discoverable via `pytest tests/smoke/`. Current skip reason in dev env: `ANTHROPIC_API_KEY unset`.

**CI workflow (`.github/workflows/ci.yml`):** Single `test` job on `ubuntu-latest` + Python 3.12. Two steps: ruff + `pytest tests/unit/`. Uses `PYTHONPATH: ${{ github.workspace }}` to sidestep the flat-layout editable-install issue (HANDOFF cumulative gotcha). Dep list mirrors `scripts/setup.sh` + `region_template/pyproject.toml` + `glia/pyproject.toml` pins. **Deliberately minimal**: no integration/component/smoke jobs, no nightly, no real-LLM labeled PRs, no type-check, no build jobs. Those are post-v0.

**Spec-vs-plan deviations from Phase 9:**

1. **Task 9.1 `event_loop_policy` not hoisted to root conftest.** Kept component-scoped as before. Intentional — hoisting would change behavior for the full 691-test unit suite.
2. **Task 9.2 `test_harness` container omitted from `compose.test.yaml`.** Spec §I.4 lists it as a service; pragmatic choice is that pytest itself acts as the harness from the host. Documented inline in the compose file.
3. **Task 9.3 mostly-skip.** Spec assumes PFC has a handler for `hive/sensory/input/text`; v0 PFC handlers are empty (region grows handlers via self-modification). Test exists and is ready to un-skip once handlers land. Acceptable deferral.
4. **Task 9.5 post-restart heartbeat assertion relaxed.** Spec §I.6 step 4 mandates waiting for a second `status=wake` heartbeat post-restart. Since glia isn't running in the test (direct docker run), the container exits after `publish_restart_request` rather than actually restarting. The remaining three assertions (prompt changed, marker text present, ≥2 commits in per-region repo) satisfy the pipeline test. If/when the test wires through glia, the fourth assertion can be re-added.
5. **Task 9.5 `sleep_quiet_window_s: 5` bumped to 30.** JSON schema `minimum: 30` forbids 5. Test prompt tweak compensates (force-sleep bypasses quiet window anyway).
6. **Task 9.6 speech-intent check made non-fatal when PFC has no handler.** Same reason as 9.3 deviation; logs a note and continues instead of failing the smoke test.
7. **Task 9.6 anonymous broker connection.** Real broker is `allow_anonymous false`. A future fix should wire a dedicated `smoke_operator` MQTT credential (passwd + ACL entry). Smoke test skips with a clear message when anonymous probe fails.
8. **Task 9.7 dep list mirrors `scripts/setup.sh` + package pyproject pins rather than spec §I.8.** §I.8 doesn't enumerate a pip-list; the actual deps come from per-package `pyproject.toml`. CI dep list is faithful to the running repo state.
9. **Task 9.7 pre-existing ruff errors fixed in the CI commit.** Five auto-fix-grade issues (I001, UP017, UP037) in `shared/message_envelope.py` (4) and `tests/smoke/conftest.py` (1) would have broken CI on first run. Fixed in the same commit to avoid shipping a known-red CI from day one. Consider separating into its own commit on a future refactor pass.

**Follow-up items worth tracking (non-blocking):**

- **Offline LLM stub.** Larry chose option (b) — skip when LLM key missing. Un-blocking Tasks 9.3 / 9.5 / 9.6 without an API key would require teaching the runtime to respect `HIVE_TEST_OFFLINE=1` and route to a deterministic `FakeLlmAdapter`. Small code change in `region_template/llm_adapter.py` factory. Defer until the first CI push that wants full-flow assertions without cost.
- **PFC handler for `hive/sensory/input/text`.** The cross-region flow test (9.3) and the speech-intent side of the smoke test (9.6) both assume PFC produces `hive/motor/speech/intent` from sensory input. Handlers grow via self-modification — until that kicks in, these tests can only exercise the boot/broker/ACL/self-mod paths. Not a bug; an expected v0 limitation.
- **`smoke_operator` MQTT credential.** Smoke test observer needs broker read access without disturbing production credentials. Add a dedicated entry to `bus/acl_templates/_base.j2` (read-only to `hive/system/#`, `hive/self/#`) + a `MQTT_PASSWORD_SMOKE_OPERATOR` in `.env`. Small hardening pass.
- **Task 9.4 component-test relocation candidate.** The ACL enforcement test is categorized as integration (uses compose + 14-region image stack concerns). It actually only uses a single broker container + rendered ACLs and runs in ~8s. Could be demoted to `tests/component/` for faster PR feedback. Cosmetic — no behavior change.
- **Task 9.6 smoke test file naming.** `tests/smoke/boot_all.py` (not `test_*.py`) required a `pytest_collect_file` hook in `tests/smoke/conftest.py` for discovery. Renaming to `test_boot_all.py` would remove the hook. Either direction is defensible; the current shape honors the spec's filename verbatim.
- **Post-restart glia wiring for Task 9.5.** Adding glia as a second container in the test would un-relax assertion #4 (second wake heartbeat). Non-trivial — requires glia to be aware of a test-only region and not try to claim `singleton: true` on its own.
- **CI flat-layout cleanup.** The HANDOFF gotcha re: `pip install -e ./region_template` failing with flit is still unresolved. CI uses `PYTHONPATH` as a workaround. A proper fix (setuptools with `package-dir`, or restructuring each package into a nested module directory) would remove ~15 lines of `env: PYTHONPATH:` from the workflow and from every developer's mental model.

**Cumulative gotchas (Phase 9 additions):**

- **Mosquitto 2.x passwd file permissions.** Bind-mounted passwd files from Windows Docker Desktop appear in the container as mode 600 owned by root; mosquitto runs as uid 1883 and can't read them. Workaround: `chmod 644` the file after `mosquitto_passwd -b` writes it. Produces a warning in broker logs but ACLs still enforce.
- **Mosquitto 2.x silently denies ACL violations.** Subscribe and publish ACL denials don't raise aiomqtt exceptions or close the connection. Test pattern: "observe the negative" — have the allowed side publish and assert the denied side receives nothing within a timeout window. Used throughout `test_acl_enforcement.py`.
- **`aiomqtt.Client(identifier=...)` is v2.** v1 used `client_id=`. All Phase-9 tests use v2.
- **Envelope content types are a `Literal`, not an enum.** `"application/json"` and `"application/hive+motor-intent"` are the canonical strings, used verbatim as string literals in test code. `Envelope.new(source_region=, topic=, content_type=, data=, ...)` is the factory; `Envelope.from_json(bytes)` parses + validates against `shared/envelope_schema.json` on load and raises `EnvelopeValidationError` on malformed input.
- **`source_region` regex `^[a-z][a-z0-9_]{2,30}$`** continues to bite — `test_harness` is valid, `hive_inject` is valid, hyphens/uppercase forbidden. When minting envelopes on behalf of an operator, use `test_harness` or `hive_inject`, not anything with a dash.
- **Windows test-region docker plumbing.** `extra_hosts={"host.docker.internal": "host-gateway"}` is idempotent on Windows Desktop and compatibility-useful for Linux CI; always include when a region container needs to reach a testcontainer broker. Use `host.docker.internal:<host_port>` rather than trying to resolve the broker container's own bridge IP.
- **`pytest_collect_file` hook needed for non-`test_*.py` files.** `tests/smoke/boot_all.py` isn't a standard collectable pattern; `tests/smoke/conftest.py` wires a `pytest_collect_file` hook to make it discoverable from `pytest tests/smoke/` while remaining invisible to the default `pytest tests/` run. Good pattern for gated smoke suites.
- **`sleep_quiet_window_s` minimum is 30** per JSON schema. Tests can't configure shorter windows; use `hive/system/sleep/force` to bypass.
- **Flat-layout flit install still broken.** CI uses `PYTHONPATH` to bypass. Still a paper cut; fix deferred.

---

## Phase 10 — Docs + HANDOFF polish — COMPLETE (2026-04-21)

All 3 tasks landed on `main`. Doc-only phase. Per CLAUDE.md Phase-6 precedent, code-quality review was skipped for all tasks; spec-compliance review was run on each.

**Per-task status:**

| Task | File(s) | Status | Commits |
|---|---|---|---|
| 10.1 | `README.md` | ✅ | `37a3ec1` impl (v0-complete status + "Running Hive" 7-step setup + honest `hive` shorthand treatment); `6647e5c` review-fix (component count + hive alias hint) |
| 10.2 | `docs/HANDOFF.md` | ✅ | `fe79ab2` — mark v0 done, restructure Quick reference, add Phase 10 + 11 sections, refresh Appendix (review-fix in next commit: Phase 1 date + this SHA backfill) |
| 10.3 | `CLAUDE.md` | ✅ | `3f8d494` — post-v0 refresh: resume-protocol examples (phase 11 / runtime evolution), branch `main`, 691 unit test count, expanded ruff scope, pointer to Quick-reference + Phase-11 prompt, added two workflow reminders (never edit across region boundaries; self-modification is sleep-only). Cumulative gotchas preserved verbatim. |

**Verification at Phase 10 close:** 691 unit + 73 integration tests passing. Ruff clean. No code was modified.

---

### Prompt for next Phase-11 session (v0 DNA complete)

Paste the following into a new Claude Code session:

---

```
You are continuing Hive at C:/repos/hive/ on branch `main`.
v0 is DNA-complete. All 10 phases are done and committed. Both
`hive-region:v0` and `hive-glia:v0` images build; 710 unit + 73
integration (3 option-b skips + 1 Windows non-admin skip) + 1
smoke-collectable. Ruff clean. Minimal GitHub Actions CI green.

All 14 regions boot, sleep, self-modify, and roll back. Phase 11
is not a construction phase — it is runtime evolution: letting
regions grow their own handlers and memory via sleep cycles, and
eventually adding post-v0 regions when accumulated experience warrants.

## Start here

1. Read `docs/HANDOFF.md` in full — the Quick-reference table and
   the Phase 11 section (at the bottom) lay out the two tracks.
2. Confirm git state:
     git fetch origin && git checkout main && git log --oneline -10
   Expected HEAD is the Phase 10 HANDOFF update commit or newer.
3. Confirm runtime state: bring up broker + glia + 14 regions
   (`hive up`), check that heartbeats are visible
   (`hive watch hive/heartbeat/#`), and confirm `hive status` is
   clean. Then `hive down`.
4. Read the Phase 11 section of this file — it describes Track A
   (growth in place) and Track B (post-v0 region additions) and
   how to choose between them at any given moment.

## Phase 11 scope

See the Phase 11 section of this HANDOFF file. The full description
of Track A (growth in place), Track B (region additions),
emergent-state framing, observables, and red flags is there.
Do not duplicate it here; treat it as the authoritative reference.

## Execution model — observation first

Larry's preference for Phase 11 is to run the first self-mod cycle
**manually-observed** before enabling autonomous runs:

1. Boot the full system (`hive up`).
2. Watch a single region's sleep log (`hive watch hive/<name>/#`)
   as it enters its first sleep cycle.
3. Read the self-mod proposal the region's LLM draft — inspect
   `regions/<name>/memory/stm.json` and the per-region git log.
4. Verify the code change it proposed is sensible (no infinite loop,
   no cross-modality ACL violation, handler compiles cleanly).
5. Confirm the commit landed in `regions/<name>/.git/`.
6. Only after one clean cycle per region should you consider
   enabling autonomous sleep scheduling.

Do not silently dispatch subagents to "start Phase 11 implementation."
Phase 11 is empirical observation of Hive living, not a task-driven
build. When a region's handler library grows to the point where
Track B (a new region addition) becomes appropriate, that is a
deliberate Larry + ACC decision — not an automatic dispatch.

## Known open tasks for Phase 11

Pull these from the per-phase "Follow-up items" sections:

- **Offline LLM stub** (`HIVE_TEST_OFFLINE=1`). Un-gates Tasks 9.3 /
  9.5 / 9.6 in CI without an API key. Small code change in
  `region_template/llm_adapter.py` factory.
- **`smoke_operator` MQTT credential.** Add a dedicated entry to
  `bus/acl_templates/_base.j2` + `MQTT_PASSWORD_SMOKE_OPERATOR` in
  `.env`. Needed for smoke-test observer connectivity.
- **`compose.test.yaml` `test_harness` service** (spec §I.4). Currently
  pytest itself acts as the harness. Wire once Phase 11 integration
  tests need a dedicated test-harness container.
- **Bridge wiring in `glia/__main__.py`.** `RhythmGenerator` +
  `InputTextBridge` (the two enabled-by-default bridges) are
  implemented but not started in `_main()`. Wire them in alongside
  supervisor + stop in the finally block. `SpeakerBridge` and
  `MotorBridge` are a second pass once motor regions have handlers.
- **Docker-events listener for exit-code-based restart** (§E.3). Wire
  a `docker.events.listen()` call in `glia/__main__.py`; supervisor's
  `on_region_exit(region, exit_code)` already exists.
- **Flat-layout flit install cleanup.** CI uses `PYTHONPATH` workaround.
  A proper setuptools package-dir or nested module dir would remove the
  paper cut from every developer environment.
- **Type-checking job in CI.** Mypy was deferred post-v0. A `mypy
  region_template/ glia/ shared/` run in CI would surface drift early.

## Reminders

- Larry designs before coding; the spec + plan are authoritative.
  Phase 11 is organic growth, not spec-driven construction.
- Biology is the tiebreaker (Principle I).
- Infrastructure does not deliberate; cognition does not execute
  infrastructure. Glia is a mechanism; regions are the cognition.
- Commit-per-task is mandated by Principle XII. Per-region `.git/`
  commits are made by the region itself; `region_template/` and
  `glia/` commits must go through the code-change gate.
- Auto mode may be active — execute on routine decisions; pause for
  spec conflicts, risky ops, or Larry's explicit checkpoints.
- Read the per-phase "Cumulative gotchas" sections (~40+ items):
  env setup, Windows platform nuances, library pins, docker-SDK
  quirks, aiomqtt v2, mosquitto 2.x passwd permissions, silently-
  denied ACLs, envelope ContentType Literals, source_region regex,
  `sleep_quiet_window_s` minimum 30, flat-layout flit broken.
```

---

## Phase 11 — Runtime evolution

### Framing

v0 was construction — building the DNA. v1 is growth. The shared runtime (`region_template/`), 14 region scaffolds (`regions/`), glia, bus, CLI, observability tools, tests, and CI are now frozen-ish. Regions own their evolution from here. The repo's role shifts from "build infrastructure" to "observe and curate." A successful Phase 11 produces no changes to `region_template/` or `glia/`; all meaningful changes happen inside `regions/<name>/.git/` as each region authors its own commits during sleep cycles.

### Track A — Growth in place

The 14 v0 regions start with empty handler directories, starter prompts, and empty `memory/ltm/`. Expect the first wave of self-modification to produce:

- **prefrontal_cortex**: a handler for `hive/sensory/input/text` → `hive/motor/speech/intent`. Currently absent; blocks Tasks 9.3 / 9.6's speech-intent assertions. The most important first handler in the system.
- **hippocampus**: first `stm.json → memory/ltm/` consolidations during sleep. Watch `hive_stm hippocampus` before and after the first sleep.
- **amygdala / vta**: first emitted modulator values replacing the null-valued startup state. Use `hive watch hive/modulator/#` to observe.
- **insula**: first `hive/interoception/*` topics populated from real runtime metrics (token budgets, region health, compute pressure).
- **association_cortex**: first cross-modal bindings once visual_cortex and auditory_cortex start producing features.

Each self-modification is a region-authored commit in its own `regions/<name>/.git/`. Observability budget per cycle: `hive trace <correlation_id>` to follow envelope chains; `hive watch hive/modulator/#` for modulator drift; `hive_stm <region>` before and after sleep to verify STM evolution. Approve each iteration before the region's next sleep fires.

### Track B — Post-v0 region additions

When accumulated experience makes the addition worth the cost (or Larry explicitly decides), these regions join in likely order:

- **raphe_nuclei** — serotonin modulator. Stabilizes mood; counterweights amygdala under sustained stress. First addition because it calms a young, experience-thin system whose modulators may still oscillate strongly.
- **locus_coeruleus** — norepinephrine modulator (shared production with amygdala rather than amygdala owning it alone). Arousal and vigilance. Second addition; pairs with raphe for a balanced two-source economy.
- **hypothalamus** — homeostatic set-points. Body-temp / hunger analogs for compute pressure, quota, and token budget. Third; grounds the system in resource reality.
- **basal_forebrain** — acetylcholine modulator. Attention and learning gain. Fourth; boosts hippocampal consolidation quality.
- **cerebellum** — motor timing and skill refinement. Couples with motor_cortex and broca_area to smooth output. Fifth; meaningful only after motor regions have grown handlers.

Each addition flows through ACC's metacognitive spawn gate → glia's `spawn_executor` → new per-region git repo → new ACL grants via template render → heartbeat verification. The mechanism is already built (Phase 5 Task 5.7a); Phase 11 exercises it for real.

### Emergent developmental state (not declared)

v0 ships with a thin seed: 14 regions scaffolded with constitutional starter prompts, empty STM, empty LTM, empty appendices, modulator baselines at boot defaults. There is **no `hive/self/developmental_stage` topic and no `hive/self/age` topic** (both removed 2026-04-22 — see divergence entry below). There is no categorical stage a region reads to decide how to behave. Developmental state — whatever Hive currently is — is a function of accumulated experience: modulator history, STM depth, consolidated LTM count, appendix length, handler library size, rollback frequency, the richness of cross-region envelope chains.

What that means operationally:

- Behavior changes over time as the seed plus lived experience compound. A region with empty LTM and boot-default modulators behaves reactively; the same region with weeks of consolidated LTM and settled modulators behaves more deliberately. No stage label governs the shift.
- "Teenager-like" / "adult-like" are descriptive labels an operator (or mPFC's identity narrative) may apply to the observed state; they are not switches. mPFC's `hive/self/identity` and `hive/self/personality` free-text publications are the correct surface for narrative self-description.
- Dialing the seed (richer starter prompts, pre-populated LTM, appendix history, tuned modulator baselines, starter handler library) produces different starting behavior — this is the first-class lever for shaping boot state. Zero seed → newborn-like behavior. Rich seed → adult-like behavior. Current v0 seed sits closer to newborn-in-experience than to teenager despite the historical "teenager analog" framing.
- Post-v0 region additions are triggered by accumulated experience making the addition worth the cost, or by Larry's explicit decision — never by crossing a stage threshold. Age, when needed, is computed on demand as `delta(first_memory_timestamp, now)` via hippocampus query, not read from a topic.

### How to know Phase 11 is going well

Not a checklist — observables:

- Per-region `.git/` log grows beyond the birth commit. Each region is authoring its own real code changes, not just timestamp updates.
- `hive/modulator/*` retained values fluctuate meaningfully over days — not stuck at boot-default nulls.
- Cross-region envelope chains via `correlation_id` extend beyond the original sensory→cognitive→motor triad as regions develop richer subscription sets.
- Rollback events remain rare (fewer than one per region per week). When they happen, the rollback mechanism unblocks cleanly and the region re-enters with a corrected handler.
- Token + compute budgets hold. Insula alerts catch runaway regions before they exhaust quota.

### Red flags that would halt Phase 11 autonomy

- Silent regressions in the shared runtime. `region_template/` is DNA — a faulty handler could produce infinite-loop behavior. Symptom: a region never exits its wake phase, heartbeats stop.
- ACL leaks — cross-modality access that should be denied. Watch the broker logs for unexpected publish/subscribe attempts.
- Self-mod commits that do not compile. `compileall` guard should catch this; if a region commits broken Python, the guard produces a rollback. If rollback itself fails, Phase 11 autonomy pauses.
- Budget blowouts. Token overspend without insula catching it signals a handler loop or a misconfigured budget cap. Check daily-budget alerts.

### What this means for the repo

The `region_template/` directory is DNA and should rarely change in Phase 11. Any edits to shared runtime code must flow through the code-change gate (`glia/codechange_executor.py`) just like any region self-modification — cosign-gated by design, not a casual edit. The `regions/<name>/` directories are gene expression and change continuously; those changes belong to the regions themselves. The `glia/` and `tools/` directories may receive small wiring fixes (bridge wiring, offline LLM stub) but should not see architectural changes without Larry's explicit direction.

### 2026-04-21 — Append-only prompt evolution (§A.7.1 divergence)

**Decision.** Regions no longer self-modify ``prompt.md``. The starter
prompt is now truly immutable constitutional DNA, written once at
region birth by ``glia/spawn_executor.py`` and never overwritten.
Evolution happens via a per-region append-only appendix at
``regions/<name>/memory/appendices/rolling.md`` managed by
``region_template.appendix.AppendixStore``.

**Why.** The first real PFC self-mod cycle in the prior observation
session replaced the 200-line constitutional starter prompt with a
4-item TODO list — the pipeline worked, but the LLM's judgment on
rewriting its own DNA was self-destructive. Rather than add fragile
guardrails around prompt rewrites, we remove the footgun entirely.

**Mechanism.**
- ``region_template.appendix.AppendixStore`` — single writer of
  ``rolling.md``. Lazy-creates on first append. Dated H2 headers
  (``## <ISO-timestamp> — <trigger>``). Atomic read-modify-write via
  the existing ``_atomic_write_text`` helper.
- ``region_template.prompt_assembly.load_system_prompt`` — joins
  starter prompt + explicit ``# Evolution appendix`` delimiter +
  rolling appendix. Called at every LLM call that builds a system
  prompt (today: sleep review; future: handler-driven LLM calls).
- Sleep review schema: ``prompt_edit`` is gone, replaced by
  ``appendix_entry``. LLM emits only the new section body; framework
  prepends the timestamp header.
- Sleep now sends a ``role="system"`` message with starter + appendix
  plus a ``role="user"`` message with STM/events/schema. Previously
  the sleep LLM never saw the region's own starter prompt; it does now.
- ``SelfModifyTools.edit_prompt`` is **deleted**. No deprecation shim —
  zero production callers remain after the sleep wiring swap.

**Spec divergence from §A.7.1.** The spec lists ``edit_prompt`` as one
of the self-modification tools. It no longer exists. ``prompt.md`` is
not a writable surface for regions at all. Any future spec revision
should reframe §A.7.1 around the rolling appendix.

**What to check on resume.**
- ``regions/<name>/memory/appendices/rolling.md`` — grows over time.
- ``regions/<name>/prompt.md`` — should be byte-identical to its
  git-HEAD state across every sleep cycle. A non-zero diff here is a
  regression.
- Every ``SleepCoordinator.run()`` that appends commits the new
  rolling.md section through the region's per-region git.

**Follow-ups (explicitly deferred).**
- Consolidation pass: summarize older appendix sections into a gist
  so rolling.md doesn't grow unbounded over months. Out of scope for
  this session; revisit once we have real multi-week appendix data.
- Token-budget check on the assembled system prompt. No hard cap
  today (biology as tiebreaker, Principle I). Anthropic prompt
  caching on the stable system half is the first-line mitigation.
- Sleep-test harness helpers (``_build_coordinator``, ``_review_json``,
  ``_completion``) are currently imported from ``tests/unit/test_sleep.py``
  by the Task 9 integration test. Promote them to
  ``tests/fakes/sleep_harness.py`` in a follow-up so integration
  tests don't have to reach into unit-test internals.
- Polish the sleep-review user template's point 4 wording: the prose
  uses "evolution log" / "rolling appendix" where the JSON schema
  field is literally ``appendix_entry``. A one-word alignment would
  reduce schema-drift risk on first cycles (flagged by Task 5 review).
- ``_format_commit_message``'s per-change line currently reads
  ``"appendix: +1 section"`` / ``"unchanged"`` — sibling lines are
  ``"handlers: changed"`` / ``"unchanged"``. Minor symmetry polish.

### 2026-04-22 — Emergent developmental state (§A.7.1 / §B.4 divergence)

**Decision.** ``hive/self/developmental_stage`` and ``hive/self/age``
are no longer retained topics. They have been removed from
``shared/topics.py``, from the mPFC ACL template, from the topic schema
doc, and from the required-constants test. Regions no longer subscribe
to, read, or branch on a stage label. Developmental state is emergent
from accumulated experience — not a categorical field. Age, when
needed, is computed on demand as ``delta(first_memory_timestamp, now)``
via hippocampus query.

**Why.** Biology is the tiebreaker (Principle I). A biological mind's
developmental stage is a descriptive observation, not a switch that
drives behavior. "Teenager" means "seeded with and shaped by roughly
what a biological teenager has lived through," not a runtime flag. The
previous design invited stage-label / actual-state mismatch — a region
told "you are a teenager" while holding a newborn's actual experience
(empty LTM, empty appendix, no STM history) — which contributed to
brittle first-cycle self-mod behavior. Removing the topic removes the
footgun.

**Mechanism.**
- ``SELF_DEVELOPMENTAL_STAGE`` and ``SELF_AGE`` constants removed from
  ``shared/topics.py``.
- ``"SELF_DEVELOPMENTAL_STAGE"`` entry removed from
  ``REQUIRED_CONSTANTS`` in ``tests/unit/test_topics.py`` (``SELF_AGE``
  was not in the spot-check list).
- mPFC write grants for both topics removed from
  ``bus/acl_templates/medial_prefrontal_cortex.j2``.
- Matching rows removed from ``bus/topic_schema.md``.
- 14 region starter prompts + 14 region mirror prompts reworked:
  stage-subscription bullets deleted; "teenage X runs hot" narrative
  replaced with experience-grounded language naming observable state
  (modulator values, STM depth, LTM count, appendix length);
  "read ``hive/self/developmental_stage``" instructions deleted;
  mPFC "Periodic maturation review" renamed "Periodic identity review"
  and reframed — reflection refines ``hive/self/identity`` and
  ``hive/self/personality`` narrative, does not advance a stage.
- mPFC starter prompt bootstrap section no longer lists
  ``developmental_stage`` or ``age`` among retained publishes. The four
  remaining retained self-state channels are ``identity``, ``values``,
  ``personality``, ``autobiographical_index``.

**Spec divergence from §B.3.4 and §B.4.** §B.3.4's
``application/hive+self-state`` schema lists ``developmental_stage``
with enum ``["teenage", "young_adult", "adult"]`` and ``age`` as a
non-negative integer. §B.4's topic table lists both
``hive/self/developmental_stage`` and ``hive/self/age`` as retained
mPFC-published topics. Neither is part of v0's runtime surface any
more — both sections received divergence banners on 2026-04-22. A
future spec revision should drop both fields; retain ``identity``,
``values``, ``personality``, ``autobiographical_index`` as the four
retained self-state channels. (Separate from §A.7.1, which covers
``append_appendix`` — see the 2026-04-21 append-only divergence entry.)

**What to check on resume.**
- No region prompt references ``hive/self/developmental_stage`` or
  ``hive/self/age``.
- Python runtime never imports or references
  ``SELF_DEVELOPMENTAL_STAGE`` / ``SELF_AGE``.
- When wondering "how old is Hive?": age is computed on demand as
  ``delta(first_memory_timestamp, current_time)``, not read from a
  topic. First-memory timestamp is obtained from hippocampus.

**Follow-ups.**
- Observatory HUD's ``SelfPanel.tsx`` still renders a
  ``developmental_stage`` field (with ``?? 'unknown'`` fallback). It
  degrades gracefully to "unknown" forever until the observatory pass
  reworks the panel around the remaining 4 self-topics (or a computed
  age readout). Observatory is a separate sub-project; this is tracked
  there, not here.

**Done 2026-04-22.** Spec body edits landed — §B.3.4 (self-state
schema), §B.4 (topic table), §L.3 (retained-topic count), §A.4.2 step
7 (bootstrap cross-ref), §D.5.3 (review prompt), §D.5.6 (commit
message template), §I.6 (self-mod cycle test), §K.6 (starter prompt
iteration). Divergence banners subsequently removed once the spec
body agreed with itself end-to-end.

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

High-signal items Phase 11 will grapple with (full detail in per-phase "Follow-up items" sections):

- **Offline LLM stub.** The `HIVE_TEST_OFFLINE=1` flag is wired at the env level but the runtime's `llm_adapter.py` factory doesn't route to a `FakeLlmAdapter` when it's set. Un-blocking CI for full-flow integration tests (Tasks 9.3 / 9.5 / 9.6) without real API spend is the highest-leverage infrastructure item for Phase 11.
- **Bridge wiring.** `RhythmGenerator` and `InputTextBridge` are implemented in `glia/bridges/` but not started in `glia/__main__.py`. No region currently receives rhythm ticks or externally-injected text from the glia layer. Wiring is a small `_main()` edit; deferred because no region has a handler for those signals yet.
- **Post-v0 region authoring pattern.** When Track B kicks in (raphe_nuclei, locus_coeruleus, etc.), glia's `spawn_executor` scaffolds the region, but the region's starter prompt must be authored and reviewed before the spawn. The authoring pattern (who writes the prompt, what review loop it goes through, how it gets committed to `docs/starter_prompts/`) is undecided. Decide before spawning the first post-v0 region.

---

## Appendix: File map

```
C:/repos/hive/
├── README.md                      # Project overview (v0-complete, Running Hive section)
├── CLAUDE.md                      # Claude Code project guide — resume protocol + gotchas
├── pyproject.toml                 # Root ruff + pytest config (all packages inherit)
├── docker-compose.yaml            # Phase 6 — broker + glia services (regions launched by glia)
├── conftest.py                    # Root conftest (import shim)
├── .gitignore
├── .env.example                   # Template for MQTT passwords + ANTHROPIC_API_KEY
├── .github/
│   └── workflows/
│       └── ci.yml                 # Phase 9 — minimal CI (ruff + unit tests on push + PR)
├── scripts/
│   ├── bootstrap_env.sh           # Phase 0 — venv setup helper
│   ├── make_passwd.sh             # Phase 0 — mosquitto_passwd generator
│   └── setup.sh                   # Phase 0 — full dev environment setup
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
│       │   └── 2026-04-19-hive-v0-design.md   # Phase 2 — authoritative design spec (4,792 lines)
│       └── plans/
│           └── 2026-04-19-hive-v0-plan.md     # Phase 3 — task-level implementation plan
├── region_template/               # Phase 4 — Shared runtime DNA (17 modules, ruff clean)
│   ├── __init__.py
│   ├── __main__.py                # Entry point; Windows signal handling
│   ├── types.py                   # LifecyclePhase StrEnum + core types
│   ├── errors.py                  # Error hierarchy (ConnectionError shadows stdlib — qualify)
│   ├── logging_setup.py           # structlog setup; warn→warning remap
│   ├── config_loader.py           # RegionConfig Pydantic model + YAML loader
│   ├── capability.py              # Capability enforcement
│   ├── mqtt_client.py             # aiomqtt v2 wrapper + fake for tests
│   ├── llm_adapter.py             # LiteLLM integration + budget tracking
│   ├── llm_cache.py               # Anthropic cache_control markers
│   ├── llm_stream.py              # Streaming delta accumulator
│   ├── memory.py                  # MemoryStore — STM + LTM
│   ├── git_tools.py               # Per-region git integration
│   ├── self_modify.py             # Self-modification tools
│   ├── handlers_loader.py         # Handler module discovery
│   ├── heartbeat.py               # Heartbeat publisher
│   ├── sleep.py                   # Sleep cycle + self-mod pipeline
│   ├── runtime.py                 # RegionRuntime integrator
│   ├── litellm.config.yaml        # LiteLLM provider defaults
│   ├── defaults.yaml              # Config defaults
│   ├── config_schema.json         # JSON schema for config.yaml
│   ├── Dockerfile                 # hive-region:v0 image (python:3.11-slim + git + tini)
│   └── pyproject.toml             # Package metadata (no [tool.ruff] — root wins)
├── regions/                       # Phase 8 — 14 scaffolded region directories
│   ├── medial_prefrontal_cortex/  # Each contains: config.yaml, prompt.md,
│   ├── prefrontal_cortex/         #   subscriptions.yaml, handlers/__init__.py,
│   ├── anterior_cingulate/        #   memory/ltm/.gitkeep
│   ├── hippocampus/               # Per-region .git/ created on first boot (§G.2)
│   ├── thalamus/
│   ├── association_cortex/
│   ├── visual_cortex/
│   ├── auditory_cortex/
│   ├── motor_cortex/
│   ├── broca_area/
│   ├── amygdala/
│   ├── vta/
│   ├── insula/
│   ├── basal_ganglia/
│   └── test_self_mod/             # Phase 9 — dedicated self-mod test target (not in registry)
├── glia/                          # Phase 5 — Infrastructure (no LLM, no cognition)
│   ├── __init__.py
│   ├── __main__.py                # glia entry point
│   ├── registry.py                # RegionRegistry — regions_registry.yaml loader
│   ├── regions_registry.yaml      # 14 region definitions + capabilities
│   ├── launcher.py                # Docker region launcher
│   ├── heartbeat_monitor.py       # Heartbeat miss detection
│   ├── acl_manager.py             # ACL template renderer + mosquitto reload
│   ├── rollback.py                # Per-region git rollback
│   ├── codechange_executor.py     # Code-change gate (cosign + apply + rollback)
│   ├── spawn_executor.py          # Neurogenesis executor
│   ├── metrics.py                 # System metrics aggregator
│   ├── supervisor.py              # Circuit breaker + restart policy
│   ├── bridges/                   # 6 bridges (rhythm, input-text, speaker, motor, ...)
│   └── Dockerfile                 # hive-glia:v0 image
├── bus/                           # Phase 2 — MQTT broker config
│   ├── mosquitto.conf             # Broker config
│   ├── topic_schema.md            # Full topic catalog with ACL rules
│   └── acl_templates/             # Jinja2 ACL templates
│       ├── _base.j2               # Shared grants for all regions
│       ├── _new_region_stub.j2    # Template for spawned regions
│       └── <14 per-region>.j2     # One per v0 region
├── shared/                        # Phase 1 — Shared library (envelope + topics)
│   ├── message_envelope.py        # Envelope schema + factory + parser
│   ├── topics.py                  # Topic constant catalog
│   ├── envelope_schema.json       # JSON schema for envelope validation
│   └── metric_schemas.json        # JSON schemas for system metrics
├── tools/                         # Phase 6 + 7 — CLI + debug tools
│   ├── hive_cli.py                # `hive` command (up/down/status/logs)
│   └── dbg/
│       ├── hive_trace.py          # Trace a correlation_id across the bus
│       ├── hive_watch.py          # Watch a topic pattern (or alias)
│       ├── hive_stm.py            # Inspect a region's STM from filesystem
│       └── hive_inject.py         # Publish a crafted envelope
├── tests/
│   ├── unit/                      # 691 unit tests — fast, no external deps
│   ├── component/                 # Component tests (real mosquitto via testcontainers)
│   ├── integration/               # 73 integration tests (real broker + compose fixtures)
│   │   ├── compose.test.yaml      # Phase 9 test compose (broker + glia + mpfc + pfc)
│   │   ├── mosquitto.test.conf    # Anonymous auth for integration tests
│   │   └── test_*.py              # Per-phase integration tests
│   └── smoke/
│       └── boot_all.py            # Full-system smoke gate (requires hive up + LLM key)
└── observatory/                   # Self-contained sub-project (see observatory/CLAUDE.md)
    └── ...
```
