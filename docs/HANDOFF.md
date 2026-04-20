# Hive — Session Handoff

**Last updated:** 2026-04-19
**Current phase:** Phase 4 (Implementation) — ready to start
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

### Status as of 2026-04-19

| Phase | Status | Notes |
|---|---|---|
| 0. Foundation (3 tasks) | ✅ | `pyproject.toml`, `.gitignore`, `.env.example`, `scripts/bootstrap_env.sh`, `scripts/make_passwd.sh` |
| 1. Shared library (5 tasks) | ✅ | `shared/envelope_schema.json`, `shared/message_envelope.py` (39 tests), `shared/topics.py` (55 tests), `shared/metric_schemas.json` |
| 2. MQTT layer / bus (4 tasks) | ✅ | `bus/topic_schema.md`, `bus/mosquitto.conf`, `bus/acl_templates/_base.j2` + 14 per-region + `_new_region_stub.j2` |
| 3. Runtime DNA (17 tasks) | ⏳ **Next** | `region_template/` — critical path, longest phase |
| 4. Region Docker image | ⏳ | |
| 5. Glia (12 tasks) | ⏳ | |
| 6. Bootstrap CLI (2 tasks) | ⏳ | |
| 7. Observability tools (4 tasks) | ⏳ | |
| 8. Region scaffolding × 14 | ⏳ | PARALLEL-OK |
| 9. Integration + smoke + self-mod tests | ⏳ | |
| 10. Docs + HANDOFF | ⏳ | |

**Git state:** 12 commits on `impl/v0` (pushed to `origin/impl/v0`). `main` still holds docs + spec + plan only. 94 unit tests passing (envelope + topics).

**Execution model:** `superpowers:subagent-driven-development` — fresh implementer subagent per task; spec review (always) + code quality review (for real code); commit-per-task; checkpoint with user every ~10-15 tasks.

### Goal

Implement Hive v0 per the plan. Multi-session; use parallel dispatched agents for the 14-region scaffolding work in Phase 8.

### Prompt for next Phase-4 session (resume in-progress work)

Paste the following into a new Claude Code session:

---

```
You are continuing Hive v0 Phase 4 implementation at C:/repos/hive/ on
branch `impl/v0`.

## Start here

1. Read `docs/HANDOFF.md` in full — it has authoritative phase status.
2. Confirm git state:
     git fetch origin && git checkout impl/v0 && git log origin/impl/v0 --oneline -15
   You should see ~12+ commits from Phases 0-2.
3. Read the next phase's section of the plan:
     docs/superpowers/plans/2026-04-19-hive-v0-plan.md
   Use the Phase-level task list in HANDOFF.md's status table to find where
   to resume.
4. Spot-read the relevant spec section before starting any real-code task
   (e.g., for Phase 3 runtime, read §A of
   docs/superpowers/specs/2026-04-19-hive-v0-design.md).

## Execution model

Use `superpowers:subagent-driven-development`:
- Fresh implementer subagent per task — never re-use context across tasks.
- Spec review after every task (dispatch plan-document-reviewer template
  adapted, or general-purpose + focused prompt).
- Code quality review for any task producing real code (skip for
  config-only/data-only tasks).
- One commit per plan task. Don't batch multiple tasks into one commit —
  granular history is a project constraint (Principle XII).
- Use HEREDOC commit messages with Co-Authored-By trailer:
    Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Chunking

Work manageable chunks. Checkpoint with Larry (user) every ~10-15 tasks
or at phase boundaries, whichever is sooner. Don't push silently through
a full phase of 17 tasks.

## When you hit a spec issue

Flag it — do not silently improvise. Spec is 4,792 lines and has been
review-iterated three times; if something looks wrong, surface it before
coding around it.

## Next work

Phase 3 (Runtime DNA) — 17 tasks in `region_template/`. Follow the
dependency waves in the plan:
  - Wave A (sequential): 3.1-3.4 (pyproject, types, errors, logging)
  - Wave B (parallel after A): 3.5, 3.6, 3.9, 3.10, 3.13
  - Wave C (sequential, composes B): 3.7, 3.8, 3.11, 3.12, 3.14, 3.15, 3.16, 3.17

Complete-session deliverables for Phase 3:
- `region_template/` with all 17 modules, each with passing unit tests
- Component tests for mqtt_client (testcontainers mosquitto) passing
- RegionRuntime boots in-process against a mock broker
- HANDOFF.md updated to mark Phase 3 ✅ and move "Next" flag to Phase 4

## Reminders (from memory)

- Larry designs before coding; the spec + plan are authoritative.
- Biology is the tiebreaker (P-I). If you feel a Python idiom tugging
  against the biological metaphor, the biology wins.
- Infrastructure (glia) does not deliberate; cognition (regions) does not
  execute infrastructure. Don't cross this line in the implementation.
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
