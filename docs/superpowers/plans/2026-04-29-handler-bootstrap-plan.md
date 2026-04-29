# Handler Bootstrap Plan — bring all 14 regions to working cognition by hand

*Drafted: 2026-04-29 · Author: Claude (Opus 4.7) for Larry · Status: ratified by Larry; in execution.*

> **Larry's framing (2026-04-29):** "We need to bootstrap a completely working system. After it works, we can let it evolve."

## Decisions ratified (2026-04-29)

1. **Tag schema:** `<thoughts>...</thoughts>` (private, not published) + `<publish topic="X">{...json body...}</publish>` (one or more per response) + `<request_sleep reason="..."/>` (optional). Every region's `prompt.md` gets a "Response format" appendix committing to this. Parsing failures publish `hive/metacognition/error/detected` with `kind: "llm_parse_failure"`.
2. **VTA is LLM-driven**, not algorithmic. VTA's handler becomes a `respond.py` (not `signal.py`), reads motor-outcome envelopes, and the LLM produces a nuanced dopamine value with reasoning. Higher cost than the algorithmic version, biologically more apt.
3. **No test fixtures, no recorded-LLM CI fixtures.** Tests use real LLM input/output. Unit-level `ctx.llm` stubs are allowed only where needed to isolate handler control flow; integration + component tests hit the real API. CI runs real LLM and consumes real tokens. Acceptable cost per Larry.
4. **No "sleep observation" coded task.** Larry runs the system after Phase B and handles bugs/observations in real time as they surface. Original Phase C drops; original Phase D folds into the final HANDOFF commit alongside Phase B.
5. **No token-budget caps, no phase pauses.** Drive all tasks consecutively — bootstrap a working system ASAP.
6. **Every task ships in a working state.** Subscription edits and handler edits land in the same commit per task. No "subscription separately, handler later" splits. The bootstrap-mode allowance from CLAUDE.md (commit `42e60df`) is the authority for hand-applied region edits.

Mechanical defaults (also ratified):
- **Execution model:** `superpowers:subagent-driven-development` — fresh implementer per task, two-stage review (general-purpose spec compliance + superpowers:code-reviewer code quality), fix-loop on Important+ findings, one commit per task.
- **Test location:** `tests/unit/regions/<name>/test_handlers.py` (matches existing `tests/unit/` repo-root convention).
- **Per-region prompt revisions:** "Response format" section appended in the same task as that region's handler.

That shapes the plan: hand-write working deliberation handlers for **every** region, get a fully functional Hive (chat round-trips, sensory→cognition→motor loops fire, modulators move, sleep is meaningful), and only **then** let self-modification take over. Don't bootstrap thin and lean on sleep-cycle evolution to close the gap — the gap is too big and self-mod is unproven end-to-end.

---

## 1. Problem

After the v4 chat ship, MQTT messages reach the regions that subscribe to them. But **13 of 14 regions have empty `handlers/` directories** (only `__init__.py`). The runtime's dispatcher [`src/region_template/runtime.py:563`](../../../src/region_template/runtime.py:563) returns immediately when no handler matches:

```python
handlers = match_handlers_for_topic(self._handlers, envelope.topic)
if not handlers:
    return       # subscribed but inert
```

There is **no default "LLM-on-stimulus"** behavior. The only existing handler is PFC's [`notebook.py`](../../../regions/prefrontal_cortex/handlers/notebook.py) — a 29-line scaffold that records sensory text into STM but does not call an LLM. PFC's docstring presumes regions self-modify during sleep to fill in the rest, but:

1. STM only accumulates from subscribed traffic the existing scaffold matches — most subscriptions are unhandled, so STM stays sparse.
2. Sleep coordinators read STM to decide what to evolve. Sparse STM → `no_change` sleep results → no evolution happens.
3. The chicken-and-egg never breaks on its own.

**Consequence right now:** chat publishes reach assoc_cortex but produce silence (no handler matches `hive/external/perception`); inter-region cognitive traffic is empty (no handler publishes anything beyond rhythm/heartbeats); modulators stay at neutral defaults; sleep produces nothing.

## 2. Goal

A fully working Hive cognitive loop, hand-written end-to-end:

1. **Chat round-trip:** Larry types → assoc_cortex integrates → PFC deliberates → broca articulates → observatory chat shows the reply, in <30 s, reliably.
2. **Sensory → cognition:** when audio/visual hardware bridges arrive (out of scope here, but the receiving handlers must be ready), `hive/sensory/*` traffic produces cognitive integration the same way chat does.
3. **Motor loop:** PFC + basal_ganglia produce `motor/intent`, motor_cortex executes (or stub-executes), `motor/complete`/`failed`/`partial` propagate back to PFC for prediction-error and to VTA for reward.
4. **Modulators move:** VTA publishes `modulator/dopamine` on motor outcomes; amygdala publishes `modulator/cortisol` on threat-shaped inputs; insula publishes `interoception/felt_state` from system metrics.
5. **Metacognition lives:** anterior_cingulate detects conflict in cognitive output streams and publishes `metacognition/conflict/detected`; mPFC handles `metacognition/reflection/request` with a real reflection.
6. **Hippocampus encodes:** every meaningful envelope (cognitive/sensory/external) writes an episodic event to hippocampus's STM via its handler, with emotional tagging from amygdala.
7. **Sleep produces commits:** with real STM, sleep cycles run their consolidation pipeline against meaningful content and either prune, promote, or rewrite memory/handlers as designed.

After (7), regions can begin self-modifying — but the bootstrap deliverable is everything *up to* (7), end-to-end working without relying on sleep to fill gaps.

This plan does **not** include modulator-based saliency, hardware bridges, or audio synthesis. Those are explicit follow-ons.

## 3. Architecture

### 3.1 Handler shape (existing pattern)

```python
# regions/<name>/handlers/<file>.py
SUBSCRIPTIONS = ["hive/...", "hive/..."]   # MQTT topic patterns
TIMEOUT_S = 5.0                             # async dispatch timeout

async def handle(envelope, ctx):
    """ctx fields:
       - region_name, phase
       - publish(topic, content_type, data, qos, retain) -> coroutine
       - llm.complete(prompt, ...) -> LLMResponse
       - memory.record_event(envelope, summary)  → appends to STM
       - tools (region's tool surface)
       - request_sleep(reason)
       - log (structlog logger)
    """
```

Multiple handler modules per region are allowed — the runtime auto-loads everything in `handlers/`. Each module's `SUBSCRIPTIONS` registers its dispatch patterns.

### 3.2 Three handler classes

We split the work across three orthogonal handler types, applied per region as appropriate:

**(A) `notebook.py` — STM-only recorder.** Mirrors PFC's existing pattern: receive envelope, write a one-line summary to STM, return. Zero LLM cost, gives sleep something to consolidate. Applied to every region for its non-deliberation subscriptions (rhythm/heartbeat/region_stats are filtered out by `record_event`'s built-in noise filter, so no manual filtering needed in the handler).

**(B) `respond.py` — LLM-driven deliberation.** Receive envelope, build a prompt from the region's `prompt.md` + recent STM + the inbound envelope, call `ctx.llm.complete(...)`, parse the structured response, publish output envelope(s). Applied to regions that genuinely deliberate: cognitive layer (assoc_cortex, PFC, mPFC, anterior_cingulate, hippocampus, basal_ganglia, thalamus, amygdala) plus speech/motor articulation (broca, motor_cortex).

**(C) `signal.py` — algorithmic / non-LLM.** Receive envelope, compute a signal from data, publish. No LLM call. Applied to regions whose role is signal-shaped, not language-shaped: VTA (reward → dopamine), insula (metrics → felt_state), basal_ganglia (habit reinforcement counter — separate from its respond.py deliberation).

A region may have multiple handler files: e.g. `basal_ganglia/handlers/{notebook.py, respond.py, signal.py}`.

### 3.3 LLM output convention

To make handler `respond.py` parsing robust across all regions, prompts must commit to a tag schema. Proposal (subject to Larry's veto in §10):

```xml
<thoughts>internal reasoning, not published</thoughts>
<publish topic="hive/cognitive/<region>/integration">
  {"text": "...", "confidence": 0.7, "...": "..."}
</publish>
<publish topic="hive/motor/speech/intent" if="warranted">
  {"text": "verbal response goes here"}
</publish>
<request_sleep reason="..." if="STM is overflowing or fatigue is high"/>
```

The `respond.py` handler:
1. Calls LLM with `prompt = region_prompt + recent_events + envelope`.
2. Extracts every `<publish topic="X">…</publish>` block, parses inner JSON, and calls `ctx.publish(topic=X, ..., data=parsed_inner)`.
3. Honors `<request_sleep reason="…"/>` by calling `ctx.request_sleep(reason)`.
4. On parse failure: log + publish `hive/metacognition/error/detected` with `kind: "llm_parse_failure"` + the raw response. Don't crash the region.

Every region's `prompt.md` gets a final section "Response format" documenting these tags. We hand-edit those during the per-region tasks.

### 3.4 Saliency gate (token cost control)

Hand-written `respond.py` handlers will fire on every matching envelope, calling LLM each time. Many topics are high-volume (sensory/auditory/features at audio frame rate, sensory/visual/features at video frame rate when hardware lands). Even now, `hive/cognitive/<X>/#` wildcards could fan in fast.

Tiered gating:

- **Hard topic gate:** `respond.py`'s `SUBSCRIPTIONS` is the list of "deliberation-worthy" topics. Anything not in that list is handled by `notebook.py` only (record-to-STM, no LLM).
- **STM-pressure gate:** if `recent_events` count > 50 (configurable), drop the LLM call for that envelope and just record. Prevents runaway during bursts. STM-pressure is also what triggers sleep, so this is consistent.
- **Modulator gate (deferred):** when modulators are flowing, weight LLM calls by current cortisol/dopamine — high arousal makes more envelopes salient, low arousal less. Out of scope for v0; in v1.

Bootstrap recommendation: hard topic gate + STM-pressure gate. Both are cheap to implement.

### 3.5 STM record format

Mirrors PFC's existing `notebook.py`:

```python
summary = f"{topic_kind}: {text[:200]}"
await ctx.memory.record_event(envelope, summary)
```

Where `topic_kind` is the second-segment slug (`sensory.text`, `external.perception`, `motor.speech.intent`, etc.). For non-dict payloads, `summary = f"{topic_kind}: {str(data)[:200]}"`.

The runtime's `record_event` already filters rhythm/heartbeat/region_stats noise; handlers don't need to re-check.

## 4. Per-region handler matrix

The bootstrap deliverable. Each cell is a file we hand-write. Bold = LLM-driven. Plain = scaffold/algorithmic.

| Region | notebook.py | respond.py | signal.py | Notes |
|---|---|---|---|---|
| **amygdala** | sensory/visual/{processed,features}, sensory/auditory/{features,events}, cognitive/hippocampus/response, **external/perception** | **threat-detect** on `external/perception` + sensory features → publish `cognitive/amygdala/threat_assessment` + `modulator/cortisol` (when threat_score > θ) | — | Threat handler is the LLM job; cortisol publish is part of respond.py's structured output, not separate. |
| **anterior_cingulate** | metacognition/#, system/spawn/proposed, system/codechange/proposed | **conflict-detect** on `metacognition/#` + `cognitive/<X>/integration` traffic → publish `metacognition/conflict/detected` when integrations diverge | — | Watches multiple cognitive streams for conflict. |
| **association_cortex** | sensory/#, cognitive/association_cortex/# | **integrate** on `external/perception` + `sensory/auditory/text` (+ future visual/text) → publish `cognitive/association_cortex/integration` and conditionally `motor/speech/intent` | — | The chat gateway. First task. |
| **auditory_cortex** | hardware/mic, cognitive/auditory_cortex/# | **transcribe** stub on `cognitive/auditory_cortex/transcribe_request` (when text input arrives via that path) → publish `sensory/auditory/text` | — | Real STT lands when mic hardware does. Scaffold the publish path now so cognitive integration can test with mocked transcription. |
| **basal_ganglia** | sensory/#, cognitive/basal_ganglia/#, habit/reinforce | **action-select** on `cognitive/<X>/integration` carrying actionable intent → publish `motor/intent` (or `motor/speech/intent`) | reinforce-counter on `habit/reinforce` → maintain habit-strength state for action selection (in-region only, no publish unless threshold crossed) | The motor loop's selection arbiter. |
| **broca_area** | motor/speech/{intent,cancel}, habit/suggestion, cognitive/broca_area/# | **articulate** on `motor/speech/intent` → publish `motor/speech/complete` with `text` field | — | Closes the chat loop. Also satisfies the broca text-payload proposal artifact. |
| **hippocampus** | cognitive/hippocampus/{query,encoding_hint,#}, sensory/#, metacognition/reflection/response, system/spawn/proposed, **external/perception** | **encode** on every meaningful envelope (cognitive/integration, external/perception, sensory/auditory/text) → record episodic event with emotional tag from latest amygdala threat_assessment + publish `cognitive/hippocampus/response` on incoming `query` | — | Hippocampus subs to external/perception too — every chat turn is a memory event. |
| **insula** | system/metrics/#, system/region_stats/#, cognitive/insula/# | **feel** on metric thresholds → publish `interoception/felt_state` (e.g. "fatigued", "alert", "stressed") | metrics-rollup on metrics/region_stats → maintain rolling-state aggregates for the LLM's prompt | The interoceptive surface. |
| **medial_prefrontal_cortex** | metacognition/reflection/request | **reflect** on incoming reflection request → publish `metacognition/reflection/response` with the reflection text | — | Lower-volume, per-request only. |
| **motor_cortex** | motor/{intent,intent/cancel}, habit/suggestion, cognitive/motor_cortex/# | **execute** on `motor/intent` → publish `motor/complete`/`motor/failed`/`motor/partial` (no actuators yet, so this is "describe what would happen" + return success/failure stub) | — | Hand-written stub until physical actuators land. |
| **prefrontal_cortex** | extend existing notebook to cover cognitive/hippocampus/response, motor/{complete,failed,partial,speech/complete}, habit/suggestion, cognitive/prefrontal_cortex/#, **external/perception** | **deliberate** on `cognitive/association_cortex/integration` + `motor/{complete,failed,partial,speech/complete}` (prediction error) → publish `motor/intent` or `motor/speech/intent` or `cognitive/prefrontal_cortex/plan` | — | The deliberation hub. |
| **thalamus** | sensory/#, cognitive/thalamus/# | **route** on cognitive/<X>/integration that targets `<thalamus>` namespace or carries a routing-hint tag → publish `cognitive/thalamus/route` (a routing decision envelope downstream regions consume) | — | Lighter LLM use; the routing logic is mostly tag/heuristic-driven, LLM only for ambiguous cases. |
| **visual_cortex** | hardware/camera, cognitive/visual_cortex/# | **caption** stub on `cognitive/visual_cortex/caption_request` → publish `sensory/visual/text` | — | Real captioning lands when camera hardware does. |
| **vta** | motor/{complete,speech/complete,failed} | **reward** on motor outcomes → LLM reads outcome semantics + recent context + publishes `modulator/dopamine` with a reasoned value | — | LLM-driven per ratified decision 2. |

**Totals:** 14 notebooks (extend PFC's; new for the other 13), 13 respond.py (every cognitive region + VTA + speech regions; auditory_cortex/visual_cortex respond stubs are LLM-driven but trivially small until hardware arrives), 2 signal.py (insula metric rollup, basal_ganglia habit counter).

## 5. Sequencing — chat-loop first, then expand outward

Each task is a separate commit, follows the `superpowers:subagent-driven-development` discipline (fresh implementer + two-stage review), one commit-per-task per Principle XII.

### Phase A — close the chat loop end-to-end (Tasks 1–5)

Goal: typing in chat produces a textual reply rendered in the v4 chat surface.

**Task 1 — assoc_cortex notebook + respond + prompt revision**
Files: `regions/association_cortex/handlers/{notebook.py, respond.py}`, `regions/association_cortex/prompt.md` (append "Response format" section).
Subs (notebook): `hive/sensory/#`, `hive/cognitive/association_cortex/#`. Subs (respond): `hive/external/perception`, `hive/sensory/auditory/text`.
Tests: stubbed-LLM unit tests asserting publish on `cognitive/association_cortex/integration` and conditional `motor/speech/intent`.
Verification: chat probe → mosquitto sniff shows the integration publish.

**Task 2 — PFC respond (existing notebook extends)**
Files: `regions/prefrontal_cortex/handlers/respond.py` (new), `notebook.py` (extend), `prompt.md` (revise).
Subs (respond): `hive/cognitive/association_cortex/integration`, motor outcome topics.
Tests: stubbed-LLM unit tests asserting publish on `motor/speech/intent`.
Verification: chat probe → sniff shows the speech/intent.

**Task 3 — broca articulate**
Files: `regions/broca_area/handlers/{notebook.py, respond.py}`, `prompt.md` revise.
Subs (respond): `hive/motor/speech/intent`.
Tests: stubbed-LLM asserts `text` field is populated in `motor/speech/complete`.
Verification: chat probe → sniff shows `motor/speech/complete` with non-empty text → observatory chat surface renders Hive's reply.

**Task 4 — hippocampus encode (chat memory)**
Files: `regions/hippocampus/handlers/{notebook.py, respond.py}`, `prompt.md` revise. Subscription file gets `hive/external/perception` added.
Subs (respond): `hive/external/perception`, `hive/cognitive/<X>/integration`, `hive/sensory/auditory/text`, `hive/cognitive/hippocampus/query`.
Tests: stubbed-LLM unit tests for encode-on-perception and query-response.
Verification: chat probes → recent_events grows in hippocampus's STM.

**Task 5 — chat round-trip component test**
File: `observatory/tests/component/test_chat_round_trip.py`.
Real broker testcontainer + recorded-LLM fixture (canned responses for assoc_cortex, PFC, broca). POST `/sensory/text/in` → assert `motor/speech/complete` with text lands within 30 s.
Verification: passes locally and in CI.

### Phase B — wire the rest of the cognitive layer (Tasks 6–10)

Goal: motor + modulator loops fire so the system feels alive, not just chat-replying.

**Task 6 — motor_cortex execute stub + basal_ganglia action-select**
Files: `regions/motor_cortex/handlers/*`, `regions/basal_ganglia/handlers/*`.
Closes the motor side: `motor/intent` → motor_cortex stub-executes → publishes `motor/complete`/`failed`. basal_ganglia subscribes to upstream cognitive integration to decide between competing intents.

**Task 7 — VTA reward + amygdala threat → modulators move**
Files: `regions/vta/handlers/{notebook.py, respond.py}`, `regions/amygdala/handlers/{notebook.py, respond.py}`.
VTA's respond is LLM-driven (decision 2): reads motor-outcome envelopes + recent context, publishes `modulator/dopamine` with reasoned value. Amygdala publishes `modulator/cortisol` on threat-shaped envelopes (perception with negative-valence text, or threat-tagged sensory features when hardware lands).

**Task 8 — insula felt_state + anterior_cingulate conflict + mPFC reflection**
Files: `regions/insula/handlers/*`, `regions/anterior_cingulate/handlers/*`, `regions/medial_prefrontal_cortex/handlers/*`.
insula publishes `interoception/felt_state` from system metrics; anterior_cingulate publishes `metacognition/conflict/detected` when integrations diverge; mPFC handles reflection requests.

**Task 9 — thalamus routing + auditory/visual scaffolds**
Files: `regions/thalamus/handlers/*`, `regions/auditory_cortex/handlers/*`, `regions/visual_cortex/handlers/*`.
thalamus routes ambiguous cognitive traffic; auditory/visual cortexes have respond stubs ready for when hardware bridges arrive.

**Task 10 — full-system component test**
File: `observatory/tests/component/test_full_loop.py`.
Recorded-LLM fixture exercising: chat input → assoc_cortex → PFC → motor_cortex stub → motor/complete → VTA dopamine publish → PFC sees outcome → publishes a follow-up. Asserts every link in the chain fires within a budget.

### Phase C — HANDOFF + retrospective (Task 11)

(Original Phase C "sleep observation" dropped per ratified decision 4 — Larry handles sleep observation in real time during operation.)

**Task 11 — close the plan**
- Update `docs/HANDOFF.md` with the bootstrap completion state.
- Document anything that didn't ship cleanly + any sleep/cognition issues Larry surfaced during the build.
- Decide what becomes v1.1: hardware bridges, modulator-based saliency, audio synthesis, prompt refinement.

## 6. Testing strategy

- **Per-handler unit tests** isolate handler control flow only — `ctx.publish` / `ctx.memory` are stubbed, but `ctx.llm` may be stubbed only when verifying purely structural behavior (e.g. parse-failure path produces a metacog error). Most assertion logic should run against real LLM output (decision 3).
- **Cross-region component tests** with real broker + **real LLM** — Tasks 5 and 10. CI consumes API tokens; that's the trade for not having canned fixtures.
- **No recorded-LLM fixtures anywhere.** Per Larry: real input, real output.
- **Lint:** ruff over `regions/*/handlers/`. Each handler file is self-contained.
- **Schema validation:** every published envelope's `source_region` must satisfy the `^[a-z][a-z0-9_]{2,30}$` regex. This is now enforced by `Envelope.new`. Tests should never use literal source_region values that violate it (we caught one such bug in v4 — `observatory.sensory` → `observatory_sensory`).

## 7. Risks + mitigations

- **Token cost.** Per ratified decision 5, no budget caps — bootstrap ASAP. Topic gates + STM-pressure gates (§3.4) are the only structural cost controls; CI runs against real LLM. Larry monitors live; if cost runs hot mid-bootstrap, escalate before continuing.
- **LLM output parsing.** Handlers depend on a tag schema (§3.3) the prompts must follow. Mitigation: every handler logs raw responses + parse-status; on parse failure publish a metacog/error envelope rather than crash; prompts get explicit "Response format" sections.
- **Cascade failures.** A bad publish from assoc_cortex cascades into PFC, broca, etc. Mitigation: each handler logs its publishes; observatory's metacog tab visualizes `metacognition/error/detected` clusters; at 5+ errors/min, system pauses cognition (out of scope for v0; track as v0.1).
- **Regions drift apart.** Hand-writing 12 sets of handlers means subtle inconsistencies (different tag conventions, different summary formats). Mitigation: a `regions/_template/handlers/` directory with reference notebook + respond + signal files, copied per region. CI lint checks adherence.
- **Sleep self-mod might still produce `no_change`.** With STM filled by Phase A/B, Phase C should produce real commits — but if it doesn't, that's a separate problem. Plan an out: if Phase C reveals sleep is broken, freeze handlers manually + open a sleep-coordinator plan. Don't block bootstrap on it.
- **Subscription drift.** Hand-applied subscriptions in `subscriptions.yaml` and handler `SUBSCRIPTIONS` lists can drift. Mitigation: a tiny CI lint asserting `subscriptions.yaml` topics ⊇ union of handler `SUBSCRIPTIONS` patterns.

## 8. Out of scope (explicit follow-ons)

- **Hardware bridges:** mic, camera, speaker. auditory_cortex / visual_cortex / broca audio output stay scaffold-only.
- **Audio synthesis:** broca's `motor/speech/complete` carries `text` only. Synthesizing audio bytes is a separate sensory-output project.
- **Modulator-based saliency:** §3.4 option (B). Plan it after observation data accumulates from option (A).
- **Self-modification machinery beyond observation:** Phase C just observes. Whether sleep-cycle self-mod actually produces useful evolution gets a separate plan.
- **Region-prompt revisions beyond the "Response format" appendix added per task.** Larger prompt rewrites land in their own commits.

## 9. Effort + sequencing

Per ratified decisions 4 + 5: drive all 11 tasks consecutively, no phase pauses, no token-budget caps. Estimated ~5–7 days of focused work end-to-end. Cost depends on iteration count during real-LLM verification; rough order-of-magnitude $50–150 across Phase A + B at chat-only volumes; will run hotter once amygdala/insula respond on metric streams.

## 11. Acceptance criteria

The plan is complete when:

- ✅ All 14 regions have at least a `notebook.py`; cognitive/motor regions have `respond.py`; signal regions have `signal.py`.
- ✅ Chat round-trip component test (Task 5) passes: chat input → text reply in the v4 chat surface within 30 s.
- ✅ Full-loop component test (Task 10) passes: input cascades through cognitive → motor → modulator → metacognition → returns to PFC for prediction-error.
- ✅ Sleep observation (Task 11) produced *something* — either a documented working evolution loop or a clearly-scoped "sleep is broken" follow-up plan.
- ✅ All ruff + mypy + pytest gates green; recorded-LLM CI passes.
- ✅ HANDOFF documents what's working, what's deferred to v1.1.

## Appendix A — what the bus should look like after Phase B

Idle Hive (no chat, no hardware): rhythm/heartbeat/region_stats/metrics traffic only, plus periodic sleep cycles.

Chat input: `external/perception` → assoc_cortex publishes `cognitive/association_cortex/integration` → PFC publishes `motor/speech/intent` → broca publishes `motor/speech/complete` with `text`. observatory chat shows reply.

Sensory input (when hardware lands): `hardware/mic` → auditory_cortex `transcribe_request` chain → `sensory/auditory/text` → assoc_cortex integration → … same downstream as chat.

Motor outcome: PFC publishes `motor/intent` → basal_ganglia confirms or arbitrates → motor_cortex publishes `motor/complete`/`failed` → VTA publishes `modulator/dopamine` → PFC sees both outcome and reward.

Metacognition: anterior_cingulate publishes `metacognition/conflict/detected` when integration streams disagree; mPFC handles incoming reflection requests; insula publishes `interoception/felt_state` periodically.

Memory: every meaningful envelope (perception/integration/motor/etc.) lands in hippocampus STM with emotional tagging from amygdala.

## Appendix B — early indicators that this plan is wrong

- **Phase A finishes but chat stays one-way:** prompts produce unparseable output. Pivot to prompt engineering before continuing.
- **LLM cost exceeds 3× the cap in any phase:** saliency gate is too loose. Tighten the topic gates.
- **Cross-region cascades crash repeatedly:** runtime's per-handler exception isolation isn't enough. May need a circuit-breaker pattern.
- **Phase C reveals sleep is fundamentally broken:** the bootstrap was right (don't lean on self-mod), but now we have a separate sleep-coordinator project.
