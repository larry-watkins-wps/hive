# Hive — Session Handoff

**Last updated:** 2026-04-19 (Phase 3 Wave A complete)
**Current phase:** Phase 4 (Implementation) — Phase 3 (Runtime DNA) Wave A done, Wave B next
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
| 3. Runtime DNA (17 tasks) | 🟡 **In progress (4/17)** | Wave A ✅ (3.1-3.4), Wave B next (3.5, 3.6, 3.9, 3.10, 3.13 — parallel-safe), Wave C after |
| 4. Region Docker image | ⏳ | |
| 5. Glia (12 tasks) | ⏳ | |
| 6. Bootstrap CLI (2 tasks) | ⏳ | |
| 7. Observability tools (4 tasks) | ⏳ | |
| 8. Region scaffolding × 14 | ⏳ | PARALLEL-OK |
| 9. Integration + smoke + self-mod tests | ⏳ | |
| 10. Docs + HANDOFF | ⏳ | |

**Phase 3 progress (4/17 tasks done, Wave A):**

| Task | File | Status | Commits |
|---|---|---|---|
| 3.1 | `region_template/pyproject.toml` + `__init__.py` | ✅ | `924b289` |
| 3.2 | `region_template/types.py` (+ tests) | ✅ | `acdcfd6` impl, `3079852` lint fix, `bd77a61` spec §A.4.1 StrEnum update |
| 3.3 | `region_template/errors.py` (+ tests) | ✅ | `1ec03d9` impl, `f57cd8b` review fixes (raise/catch round-trip, `*args: Any`) |
| 3.4 | `region_template/logging_setup.py` (+ tests) | ✅ | `f218d1f` impl, `1d664e3` review fixes (ProcessorFormatter for stdlib, honest docstring) |
| 3.5 | `region_template/config_loader.py` | ⏳ Wave B | — |
| 3.6 | `region_template/capability.py` | ⏳ Wave B | — |
| 3.7 | `region_template/mqtt_client.py` | ⏳ Wave C | — |
| 3.8 | LLM adapter stack (5 files) | ⏳ Wave C | — |
| 3.9 | `region_template/memory.py` | ⏳ Wave B | — |
| 3.10 | `region_template/git_tools.py` | ⏳ Wave B | — |
| 3.11 | `region_template/self_modify.py` | ⏳ Wave C | — |
| 3.12 | `region_template/handlers_loader.py` | ⏳ Wave C | — |
| 3.13 | `region_template/heartbeat.py` | ⏳ Wave B | — |
| 3.14 | `region_template/sleep.py` | ⏳ Wave C | — |
| 3.15 | `region_template/runtime.py` | ⏳ Wave C | — |
| 3.16 | `region_template/__main__.py` | ⏳ Wave C | — |
| 3.17 | `defaults.yaml` + `litellm.config.yaml` | ⏳ Config-only | — |

Plus one side-commit: `2af2df0 tests: ruff lint cleanup for shared-phase tests` (cleaned up 7 ruff findings in Phase 1 test files that predated ruff config enforcement).

**Git state:** 22 commits on `impl/v0`. 190 unit tests passing (envelope + topics + types + errors + logging_setup). `ruff check region_template/ tests/unit/` is clean. Push to origin on next handoff update.

**Spec updates during Phase 3 so far:**
- §A.4.1 — `LifecyclePhase(str, Enum)` → `LifecyclePhase(StrEnum)` (commit `bd77a61`, approved by Larry). StrEnum behavior is identical for `.value`, `isinstance`, and JSON serialization; changes `str(phase)` from `"LifecyclePhase.WAKE"` to `"wake"` (safer for MQTT topic f-strings).

**Noted known gotchas for future sessions:**
- The host Python env lacks `pydantic`, `structlog`, `ruff`, `testcontainers` by default on fresh shells. Implementers have pip-installed these on demand. `scripts/bootstrap_env.sh` exists from Phase 0 — consider using it to create a proper venv.
- structlog 25.x hardcodes `warn` → `warning` internally; `region_template/logging_setup.py` installs `_remap_warning_to_warn` processor to satisfy spec §H.1.2's lowercase-`warn` requirement.
- `ConnectionError` in `region_template/errors.py` intentionally shadows the stdlib — always reference fully-qualified (`region_template.errors.ConnectionError`) or import-alias to avoid ambiguity.

**Execution model:** `superpowers:subagent-driven-development` — fresh implementer subagent per task; spec review (always) + code quality review (for real code; skip for config-only); commit-per-task; checkpoint with user every ~10-15 tasks or at wave boundaries.

### Goal

Implement Hive v0 per the plan. Multi-session; use parallel dispatched agents for the 14-region scaffolding work in Phase 8.

### Prompt for next Phase-4 session (resume in-progress work — Wave B)

Paste the following into a new Claude Code session:

---

```
You are continuing Hive v0 Phase 3 implementation at C:/repos/hive/ on
branch `impl/v0`. Wave A (tasks 3.1-3.4) is complete. Your job this
session is Wave B (5 parallel-safe tasks), then checkpoint with Larry
before Wave C.

## Start here

1. Read `docs/HANDOFF.md` in full. The Phase-3 progress table is the
   authoritative state snapshot. Expect to see 22 commits on `impl/v0`
   and 190 unit tests passing.
2. Confirm git state:
     git fetch origin && git checkout impl/v0 && git log --oneline -15
   Expected HEAD: `1d664e3 runtime: logging_setup review fixes
   (ProcessorFormatter + docstring)` OR the HANDOFF.md commit after it
   (whichever is newest).
3. Confirm environment:
     cd C:/repos/hive && python -m pytest tests/unit/ -q
   Must show "190 passed" (or 190+N if later work landed).
     python -m ruff check region_template/ tests/unit/
   Must show "All checks passed!".
4. Read the plan's Wave B section:
     docs/superpowers/plans/2026-04-19-hive-v0-plan.md
   Tasks 3.5, 3.6, 3.9, 3.10, 3.13 (lines 381-520 in the plan).
5. Spot-read the relevant spec sections before each implementer dispatch:
   - 3.5 config_loader → spec §F (config schema + loader)
   - 3.6 capability → spec §A.7.8 (decorators)
   - 3.9 memory → spec §D.2-D.4 (STM/LTM schemas)
   - 3.10 git_tools → spec §D.5.7 + §D.8
   - 3.13 heartbeat → spec §A.5

## Execution model — approach C (batched parallel)

Use `superpowers:subagent-driven-development` but batch Wave B into two
parallel groups instead of running all 5 serially:

### Batch 1 — dispatch in parallel:
  - 3.6 `capability.py` (smaller, self-contained, decorators only)
  - 3.10 `git_tools.py` (subprocess wrapper, self-contained)
  - 3.13 `heartbeat.py` (asyncio ticker, self-contained)

  Fire all three implementer subagents in a SINGLE message (multi-tool
  call). Wait for all three to return. Then run spec + code-quality
  reviews sequentially per task (per skill's standard pattern).

### Batch 2 — dispatch in parallel after batch 1 reviews pass:
  - 3.5 `config_loader.py` (bigger — Pydantic RegionConfig + YAML merge)
  - 3.9 `memory.py` (bigger — STM atomic writes, TTL, ring buffer, LTM)

  Same pattern: parallel implementers, sequential reviews.

### Per-task discipline (unchanged):
- Fresh implementer subagent per task. Never reuse context.
- Spec compliance review after each implementer returns.
- Code quality review (via `superpowers:code-reviewer` subagent type)
  after spec review passes. Skip for config-only tasks.
- One commit per plan task (may end up 2+ commits if review finds fixes
  — that's fine, still one logical task).
- HEREDOC commit messages ending with:
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
- Verify `python -m ruff check region_template/ tests/unit/` clean
  after each task.

## Known gotchas (inherit these from prior sessions)

1. Spec-vs-plan conflicts: the spec is authoritative. The plan's plain-
   prose descriptions sometimes paraphrase loosely (e.g., HandlerContext
   field list, key names in log output). When the spec's code block and
   the plan's prose differ, follow the spec, and flag the discrepancy
   in your implementer prompt so the subagent doesn't get confused.

2. Host Python env may lack `pydantic`, `structlog`, `ruff`, `GitPython`,
   `testcontainers`. Implementers have been pip-installing on demand.
   No venv has been set up yet; `scripts/bootstrap_env.sh` exists but
   hasn't been used. If an implementer can't `import` something, tell
   them to pip install and continue.

3. `region_template/errors.py` intentionally shadows stdlib
   `ConnectionError`. Always reference fully-qualified or use an import
   alias. Spec §A.9 acknowledges this.

4. `LifecyclePhase` is `StrEnum` (Python 3.11+), NOT `(str, Enum)`.
   Spec §A.4.1 was updated in commit `bd77a61`. `str(phase)` returns
   the lowercase value (e.g., "wake"), not "LifecyclePhase.WAKE".

5. `tool_use: "wizard"` in a region config must raise ConfigError —
   only `none | basic | advanced` are valid per spec §F.2. `CapabilityProfile`
   is already implemented in `region_template/types.py` with a Literal
   type — config_loader composes it.

6. Ruff config lives at `C:/repos/hive/pyproject.toml` (workspace root,
   tool config only). Package-specific `region_template/pyproject.toml`
   MUST NOT re-declare tool blocks.

## When you hit a spec issue

Flag it — don't silently improvise. The spec is 4,792 lines and has
been review-iterated three times. If something looks wrong or genuinely
conflicts with lint rules, bring it to Larry before deciding. Example
from prior session: UP042 flagged `(str, Enum)` → Larry approved
switching to StrEnum AND updating the spec section to match.

## Chunking & checkpoints

After all 5 Wave B tasks complete with reviews passing, CHECKPOINT with
Larry. Do NOT start Wave C silently. State of play to report:
  - Wave B complete (5/5 tasks)
  - Total Phase 3: 9/17 tasks done
  - Test count and ruff status
  - Any spec deviations or open questions
  - Summary of what Wave C needs (reviewing the bigger pieces —
    mqtt_client + LLM adapter stack + runtime.py integrator)

If any Wave B task blocks or surfaces a major spec issue, stop and
surface it rather than continuing through the batch.

## Deliverable at end of session

- 5 more tasks committed on `impl/v0` (total 22 + N commits).
- Unit suite passing (expected ~230-260 tests depending on how many
  each Wave B module adds).
- Ruff clean across `region_template/` and `tests/unit/`.
- HANDOFF.md updated: Wave B row transitions to ✅ in the phase-3
  progress table; the "Next work" section pivots to Wave C.
- Clear checkpoint summary for Larry.

## Reminders (from memory / project principles)

- Larry designs before coding; the spec + plan are authoritative.
- Biology is the tiebreaker (P-I). If you feel a Python idiom tugging
  against the biological metaphor, the biology wins.
- Infrastructure (glia) does not deliberate; cognition (regions) does
  not execute infrastructure. Don't cross this line.
- Commit-per-task is mandated by Principle XII (Every Change is Committed).
  Granular history is a feature.
- Auto mode may be active — if so, execute immediately on routine
  decisions; only pause for spec conflicts, risky ops, or Larry's
  explicit checkpoints.
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
