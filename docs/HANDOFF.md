# Hive — Session Handoff

**Last updated:** 2026-04-20 (Phase 3 COMPLETE — all 17 tasks done)
**Current phase:** Phase 4 (Implementation) — Phase 3 (Runtime DNA) ✅; Phase 4 (Docker image), Phase 5 (Glia), or Phase 8 (14 regions) next
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
| 4. Region Docker image | ⏳ | |
| 5. Glia (12 tasks) | ⏳ | |
| 6. Bootstrap CLI (2 tasks) | ⏳ | |
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

**Execution model:** `superpowers:subagent-driven-development` — fresh implementer subagent per task; spec review (always) + code quality review (for real code; skip for config-only); commit-per-task; checkpoint with user every ~10-15 tasks or at wave boundaries.

### Goal

Implement Hive v0 per the plan. Multi-session; use parallel dispatched agents for the 14-region scaffolding work in Phase 8.

### Prompt for next Phase-4 session (Phase 3 DONE — pivot to Phase 4/5/8)

Paste the following into a new Claude Code session:

---

```
You are continuing Hive v0 at C:/repos/hive/ on branch `impl/v0`.
Phase 3 (Runtime DNA) is COMPLETE — all 17 tasks done, 508 unit
tests + 6 component tests passing, ruff clean, 48 commits ahead of
origin. Next: Phase 4 (Region Docker image), Phase 5 (Glia), or
Phase 8 (14-region scaffolding). Larry picks.

## Start here

1. Read `docs/HANDOFF.md` in full. The Phase-3 progress table is the
   authoritative state snapshot for Wave C completion. The "Follow-up
   items worth tracking" section lists non-blocking cleanup candidates
   you can optionally address.
2. Confirm git state:
     git fetch origin && git checkout impl/v0 && git log --oneline -20
   Expected HEAD is `782e354 runtime: defaults + litellm config (3.17)`
   or newer. Push to origin early in the session: 48 commits ahead.
3. Confirm environment:
     cd C:/repos/hive && python -m pytest tests/unit/ -q       # 508 passed
     python -m pytest tests/component/ -m component -v          # 6 passed
     python -m ruff check region_template/ tests/               # clean
4. Pick the next phase and read its plan section:
     docs/superpowers/plans/2026-04-19-hive-v0-plan.md
   - Phase 4 (Task 4.1-4.2): Region Docker image. Builds on Phase 3.
   - Phase 5 (Tasks 5.1-5.12): Glia (infrastructure, no LLM). Launcher,
     heartbeat monitor, ACL manager, rollback, registry. Sequential
     through 5.1-5.10; `bridges/` (5.11) is parallelizable.
   - Phase 8 (Tasks 8.1-8.14): 14-region scaffolding. **PARALLEL-OK** —
     each region is independent once Phase 5 is done. Good fit for
     `superpowers:dispatching-parallel-agents`.

## Suggested order (Larry's call)

- **Phase 4 first** if you want a working container to smoke-test.
- **Phase 5 first** if you want the whole infrastructure stack before
  regions. Larger scope; tighter feedback loop for integration bugs.
- **Phase 8 first** if you want to stress-test the region template
  against 14 real configs before building glia — surfaces config
  schema gaps early.

My recommendation: Phase 4 → Phase 5 → Phase 8, because Phase 4 is
tiny (1-2 tasks) and unblocks the end-to-end "can a region actually
run in a container" check; Phase 5 is the biggest chunk; Phase 8 is
the parallel-dispatch win.

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

## Known gotchas (inherit cumulatively from Wave C)

See HANDOFF.md's "Known gotchas for future sessions" section — 14
items spanning env setup, Windows platform nuances, library pins,
and repo hygiene. The `=2.6` / `=24` stray files at repo root are
still pip-install typos, still left alone.

Spec-vs-plan deviations from Wave C are catalogued in
"Spec-vs-plan deviations resolved during Wave C" — 8 items. Read
these before the first Phase-4/5/8 implementer dispatch so you can
flag the relevant ones in prompts that touch §C (LLM), §B (MQTT),
§A.7 (tools), or §D.5 (sleep).

## Deliverable at end of session

- More tasks committed on `impl/v0`.
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
