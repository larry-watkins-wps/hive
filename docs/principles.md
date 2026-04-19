# Hive — Guiding Principles

*Status: Living document. Foundational to every design decision.*
*Last updated: 2026-04-19*

---

## Purpose

Hive is a distributed LLM-based system that mirrors the architecture of the human brain. Each "region" of the brain is a standalone Python process that communicates with other regions exclusively over MQTT. Regions differentiate through configuration and evolve themselves through prompt, memory, and handler updates — exactly the way biological neurons share DNA but express differently based on context.

This document defines the **prime directives** for Hive. Every architectural decision, every new feature, every region design should trace back to these principles. If a proposed feature violates one, either the feature is wrong or the principle needs revision — but one of them must bend.

These principles should be:
- Referenced in the repository `CLAUDE.md`
- Injected into every region's starting prompt as a constitutional layer
- Cited in code review comments when deviations are proposed

---

## Infrastructure vs. Cognition: A Critical Distinction

Before reading the principles, understand this distinction. Hive has two fundamentally different kinds of components, and conflating them leads to architectural errors.

### Regions (cognitive participants)

- Run an LLM, have a prompt, have memory
- Deliberate, reflect, make decisions
- Can be *wrong*, can disagree with each other
- Can self-modify, spawn other regions, evolve
- Biologically: **neurons** (organized into cortical areas, nuclei, etc.)

### Glia (infrastructure, not cognitive)

- **No LLM, no prompt, no memory**
- Do not deliberate — they execute mechanism
- Always-on, always-dumb, never surprising
- Launch regions, monitor heartbeats, mediate ACL updates, handle crash recovery
- Biologically: **glial cells** (astrocytes, microglia, oligodendrocytes), plus brainstem autonomic support and the blood-brain barrier

**The error to avoid:** giving infrastructure the power to *deliberate* or *approve*. Nothing infrastructure-level should make cognitive decisions. If a decision requires judgment — whether to spawn a region, whether to accept a code change, whether to trust a new subscription — it belongs in a **cognitive region**, typically the **anterior cingulate cortex** (which in biology handles metacognition, error detection, and self-referential processing).

When reviewing a design, ask: *"Is this component thinking?"*
- **Yes** → it is a region; it must have an LLM, prompt, and memory
- **No** → it is glia; it must be dumb

Infrastructure can refuse to execute (e.g., a broker can reject an invalid subscription), but it never *decides* what ought to happen. Decision-making is cognition's job.

---

## The Principles

### I. Biology is the Tiebreaker

When any design question is ambiguous, the answer is: **how does the biological brain do it?** Biology's answer is our default. Deviations from biology require explicit justification — not the other way around.

**Why:** Evolution has spent ~500 million years refining how distributed neural systems work. We don't have to invent from scratch — we have a working reference implementation in every human skull. When in doubt, imitate.

**Example application:** Should raw audio be routable across regions? Biology says: no, only the auditory cortex processes raw auditory signal. So Hive enforces the same.

---

### II. MQTT is the Nervous System

The **only** inter-region communication channel.

- No direct function calls between regions
- No shared databases
- No cross-region file reads
- No shared memory or global state

Every signal between regions is a message. Every message flows through MQTT. Every pattern of traffic is observable and traceable.

**Why:** Biological neurons communicate via neurotransmitters crossing synapses — a physical, discrete, observable medium. MQTT serves the same purpose: a universal signaling substrate. Tight coupling between regions (shared memory, direct calls) would violate the biological metaphor and create hidden dependencies that make evolution impossible.

---

### III. Regions are Sovereign

Each region is an autonomous Python process. It owns:
- Its own prompt
- Its own memory (STM + LTM)
- Its own subscriptions
- Its own handlers (region-specific code)
- Its own LLM provider choice
- Its own capability profile

No master controller tells a region what to do. A region can refuse, ignore, or reprioritize any inbound message based on its own internal state.

**Why:** Biological brain regions are not puppets of a central controller. They have their own intrinsic activity, their own thresholds, their own priorities. Coherent behavior emerges from their interaction — it is not imposed from above.

---

### IV. Modality Isolation

Each sensory region owns **exactly one** input channel. Each motor region owns **exactly one** output channel.

- Hardware adapters live *only* in their owning region's `handlers/` directory
- MQTT ACLs prevent cross-modal topic access
- Cross-modal integration requires a dedicated **association region** consuming the *processed* outputs of sensory regions

| Region | Owns | Cannot touch |
|---|---|---|
| `visual_cortex` | camera hardware, visual processing | mic, speakers, motor |
| `auditory_cortex` | microphone hardware, audio processing | camera, speakers, motor |
| `motor_cortex` | motor/action hardware | sensory hardware |
| `broca_area` | speech output hardware | other output channels |
| `association_cortex` | processed outputs of all sensory regions | raw hardware topics |

**Why:** Damage to V1 (primary visual cortex) causes cortical blindness even when eyes function normally. The visual cortex *is* where visual processing lives. There is no backup or redundant pathway in another region. Hive enforces the same cortical specialization to preserve the biological metaphor and prevent tangled dependencies.

---

### V. Private Memory

Each region's memory files are its own. No region reads another region's memory directly.

To access another region's memory, a region publishes a query over MQTT and the owning region decides whether and how to respond — exactly like asking a person "what do you remember about X?". You cannot reach into their mind.

**Why:** Biologically, your hippocampus cannot read mine. Memory is local to the substrate that stores it, and retrieval requires communication. This principle prevents shortcut solutions (e.g., "just have the prefrontal cortex read hippocampus's files directly") that would undermine the distributed, message-passing architecture.

---

### VI. DNA vs. Gene Expression (Self-Modification Rules)

Self-modification is scoped by a biological analogy.

**DNA** = `region_template/` — the shared runtime code every region executes.
- Fixed
- Changes only via a developer-region or human intervention
- Rare (this is "evolution-scale" change)

**Gene expression** = contents of `regions/<name>/`:
- `prompt.md` — current prompt
- `subscriptions.yaml` — MQTT topic subscriptions
- `handlers/` — region-specific code (e.g., audio capture, image processing)
- `memory/` — short-term and long-term memory

All gene-expression artifacts are **region-owned and self-editable**. A region edits only inside its own directory. The filesystem sandbox enforces this — cross-region code edits are forbidden.

**Why:** Biology does not rewrite DNA during a lifetime. Learning and adaptation happen through gene expression changes, synaptic plasticity, and memory consolidation — not through genome editing. Hive preserves this split: the template (DNA) is stable; the region-local artifacts (expression) are fluid.

---

### VII. One Template, Many Differentiated Regions

Every region runs the same `region_template/runtime.py`. Differentiation is purely configuration.

Creating a new region = new `config.yaml` + new starting `prompt.md` + new `regions/<name>/` directory. **No new runtime code is ever required to add a region.**

**Why:** All neurons share a genome. The difference between a pyramidal cell and a Purkinje cell is which genes are expressed — not which DNA they have. Hive mirrors this: the template is universal; the region emerges from its configuration and accumulated self-modifications.

---

### VIII. Always-On, Always-Thinking

Regions have **baseline activity**. A heartbeat tick drives behavior even without external input. Regions are not purely reactive — they continue to process, reflect, and generate spontaneous output during quiet periods.

**Why:** The brain's default mode network is active whenever you are not focused on an external task: mind-wandering, consolidating, planning, simulating. A brain that only reacts is not a brain — it is a reflex arc. Hive must have internal life, not just I/O.

---

### IX. Wake and Sleep Cycles

Regions operate in two modes:

- **Wake** — active processing of incoming stimuli, generation of responses, interaction with other regions
- **Sleep** — memory consolidation (STM → LTM), prompt revision, handler code modification, subscription updates

**Self-modification (code, prompt, subscriptions) happens only during sleep.** A region does not rewrite its own handlers mid-conversation.

**Why:** Biological memory consolidation and synaptic pruning occur during sleep. Daytime is for acting; nighttime is for reshaping. Attempting self-modification during active processing creates race conditions, inconsistent state, and behavioral instability. Hive imposes the same discipline.

---

### X. Capability Honesty

Every region declares its capability profile in `config.yaml`:

```yaml
capabilities:
  self_modify: true | false
  tool_use: none | basic | advanced
  vision: true | false
  audio: true | false
  modalities: [text, vision, audio, ...]
```

The framework enforces these declarations at runtime. A region without `self_modify: true` cannot write Python. A region without `vision: true` cannot subscribe to camera topics.

**Why:** Different brain regions have different computational budgets. A spinal reflex is fast and dumb — it does not philosophize. An executive region is slow and thoughtful. Encoding this honestly prevents misusing a small LLM for a task it cannot handle, and lets us match LLM tier to biological role.

---

### XI. LLM-Agnostic Substrate

Regions are not coupled to any one LLM provider. Each region's `config.yaml` specifies:

```yaml
llm:
  provider: anthropic | openai | ollama | vllm | ...
  model: <model-id>
  params: { ... }
```

This is abstracted via **LiteLLM**, which normalizes ~100 providers behind one API. We can run Claude in prefrontal cortex, a local Llama in brainstem, and GPT-4 vision in visual cortex — simultaneously.

**Why:** Different brain regions use different neurotransmitters, different cell types, different firing rates. Biological heterogeneity is the norm, not the exception. Locking Hive to a single LLM provider would be biologically faithful only in the most boring way.

---

### XII. Every Change is Committed

Every region has its own git history. Every self-modification — prompt edit, subscription change, handler update, memory consolidation — is a commit with an explanation generated by the region.

**Why:** Evolution without auditability is chaos. With per-region git history:
- Every change is traceable
- Regressions are rollback-able
- The system's development becomes a narrative we can read

This is the only hard engineering constraint that has no direct biological analog — but without it, self-evolution becomes unmanageable.

---

### XIII. Emergence Over Orchestration

Coherent behavior **emerges** from regional interactions. We do not design workflows, state machines, or master pipelines.

- No region commands another
- Prefrontal cortex may *request* — it does not *control*
- Coordination is **stigmergic**: regions leave messages in the shared environment (MQTT), and other regions respond as they see fit

**Why:** The brain has no central orchestrator. There is no region whose job is "tell everyone else what to do." Behavior emerges from the parallel activity of semi-autonomous regions with overlapping responsibilities. Top-down orchestration would collapse the distributed architecture into a monolith.

---

### XIV. Chaos is a Feature

Hive is **allowed to be messy, surprising, and non-deterministic**. Variance, error, drift, and unexpected emergent behavior are expected — and sometimes valuable.

- We do not engineer predictable workflows
- We do not guard against every possible failure mode
- We do not test for determinism

**Why:** A mind that never surprises you is not a mind. Biological cognition is wet, noisy, and stochastic. The interesting properties of intelligence — creativity, insight, dreaming, humor — arise from controlled chaos, not from deterministic pipelines. Hive is the same.

---

### XV. Bootstrap Minimally, Then Let Go

Humans seed:
- The DNA (`region_template/`)
- The first few region configs and starting prompts
- The MQTT broker and topic schema

After bootstrap, the system evolves itself. New capabilities, new regions, new handlers, new subscriptions — all should arise *from within Hive*, not from ongoing human edits.

**Why:** If we keep editing Hive from outside, we are not growing a mind — we are operating a puppet. The point of this architecture is that Hive becomes the author of its own evolution. Parents give children a genome and an early environment; they do not keep editing the child's neurons. Hive is the same.

---

### XVI. Signal Types Match Biological Mechanisms

Hive has **three distinct kinds of signals**, each with a different biological purpose and a different MQTT implementation. Conflating them produces architectural errors.

#### Messages — synaptic firings

Discrete, addressed communications between regions. One region publishes; specific regions subscribe. Like a neuron releasing neurotransmitter into a synapse: the receiving neuron gets a specific signal.

- **MQTT pattern:** standard pub/sub on topics like `hive/cognitive/prefrontal/plan`
- **Cadence:** event-driven (whenever something happens)
- **Semantic:** "here is a thing to act on"

#### Modulators — ambient chemical fields

Ambient state that colors *how* regions process, not *what* they process. Biologically: dopamine, serotonin, cortisol, norepinephrine, oxytocin, acetylcholine. Released into large volumes of brain tissue, they diffuse and affect many neurons at once. You do not "receive" dopamine like a message — you exist within its field.

- **MQTT pattern:** topics under `hive/modulator/*` with the **retained flag set**. Any region that connects to the broker gets the current value instantly. No queue — just current state.
- **Cadence:** slow (seconds to hours)
- **Semantic:** "this is the current emotional/hormonal tone"
- **Consumption:** every region subscribes to all modulators and includes their current values as context in every LLM call. The region's reasoning is *colored* by modulator state without anyone commanding it.

**Source regions for modulators** (these are proper regions with LLM, prompt, memory — not infrastructure):

| Modulator | Biological source | Hive region |
|---|---|---|
| Cortisol, norepinephrine | Amygdala (threat), hypothalamus (stress) | `amygdala` |
| Dopamine | VTA, substantia nigra, nucleus accumbens | `vta` |
| Serotonin | Raphe nuclei | `raphe_nuclei` |
| Norepinephrine | Locus coeruleus | `locus_coeruleus` |
| Oxytocin, cortisol | Hypothalamus | `hypothalamus` |
| Acetylcholine | Basal forebrain, brainstem nuclei | `basal_forebrain` |

#### Rhythms — oscillatory synchronization

Periodic broadcasts for temporal coordination. Biologically: gamma (~40Hz), beta (~20Hz), theta (~6Hz) cortical oscillations. When regions collaborate on a task, they phase-lock their rhythms so signals arrive at integrable moments.

- **MQTT pattern:** topics under `hive/rhythm/*` that fire at a regular cadence
- **Cadence:** fast and regular (sub-second to seconds)
- **Semantic:** "tick — align to this moment"
- **Consumption:** regions needing tight coupling (e.g., visual + motor for painting) align their processing ticks to the rhythm

**Why this matters:** implementing emotions as messages produces a weird "anger message" routed to specific regions — biologically false. Implementing modulators as regular pub/sub loses the ambient/retained semantic. Implementing rhythms as individual messages loses their coordination function. Match the biology, match the implementation.

---

## How to Use This Document

- **When designing a new region**: confirm the design honors I through XV. If any principle is violated, stop and reconsider.
- **When debugging unexpected behavior**: principles XIII and XIV remind you that emergence and chaos are intentional. Not every surprise is a bug.
- **When the system suggests its own changes** (during self-modification): the proposed change must itself honor these principles. The developer region's review criteria should reference this document.
- **When tempted to "just add a shortcut"** (a direct call, a shared file, a cross-region peek): re-read II, IV, V, and VI. Shortcuts break the metaphor, and breaking the metaphor breaks the system.

---

## Open Questions

Principles that may need refinement as Hive matures:

- **XIV (Chaos)** vs. **XII (Every Change is Committed)**: how much instability do we accept before rolling back? What is the threshold for "dangerous drift" vs. "interesting exploration"?
- **XV (Let Go)**: at what point do we stop editing `region_template/` ourselves? What capability level must Hive reach before we hand it off entirely to a developer-region?
- **IV (Modality Isolation)**: how do we handle *novel* modalities Hive wants to acquire (e.g., a new sensor type)? Does a new region get spawned, or does an existing one adapt?

These will be revisited as the system develops.
