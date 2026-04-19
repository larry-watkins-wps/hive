# Hive Starter Prompts

This directory contains the **starting prompts** for each region in Hive v0. When a region is first scaffolded into `regions/<name>/`, its `prompt.md` is copied from the corresponding file here.

These are *starter* prompts, not final prompts. Once a region is running, it may revise its own prompt during sleep cycles (subject to Principle VI: DNA vs. Gene Expression). The starter prompts here remain as historical reference — they are the "born with" version of each region.

## Design principles for these prompts

Each prompt is:

1. **Self-sufficient** — embeds all 16 Hive principles in full. No external file reads required at runtime.
2. **Role-specific** — anchored to a biological analog (Principle I: Biology is the Tiebreaker).
3. **Substantive** — whatever length the region's role requires. Short regions get short prompts; complex regions get long ones. No artificial length limits.
4. **Stage-aware** — regions read `hive/self/developmental_stage` (published by mPFC, retained) and adapt behavior. No region hard-codes its age or maturity.
5. **Modulator-aware** — regions read `hive/modulator/*` and let ambient state color reasoning.
6. **Bounded** — explicit about what the region does NOT do (modality boundaries, command authority, cross-region access).
7. **Evolving** — every prompt instructs the region on how to modify itself during sleep.

## v0 region inventory (14 regions)

| File | Layer | Role | LLM |
|---|---|---|---|
| `medial_prefrontal_cortex.md` | Self | identity, developmental stage (DMN hub) | Opus 4.6 |
| `thalamus.md` | Cognitive | relay, attention gating | Opus 4.6 |
| `prefrontal_cortex.md` | Cognitive | executive, planning | Opus 4.6 |
| `hippocampus.md` | Cognitive | memory encoding & retrieval | Opus 4.6 |
| `anterior_cingulate.md` | Cognitive | metacognition, error monitoring | Opus 4.6 |
| `association_cortex.md` | Cognitive | cross-modal integration | Opus 4.6 |
| `insula.md` | Homeostatic | interoception (felt computational state) | Haiku |
| `basal_ganglia.md` | Homeostatic | action selection, habit formation | Opus 4.6 |
| `visual_cortex.md` | Sensory | camera input, visual processing | Opus 4.6 |
| `auditory_cortex.md` | Sensory | microphone input, audio processing | Opus 4.6 |
| `motor_cortex.md` | Motor | action output | Haiku |
| `broca_area.md` | Motor | speech output | Opus 4.6 |
| `amygdala.md` | Modulatory | threat/emotion → cortisol, norepinephrine | Haiku |
| `vta.md` | Modulatory | reward/motivation → dopamine | Haiku |

## Structure of each prompt

Every starter prompt follows this structure:

1. **Identity** — who this region is, biological role
2. **Bootstrap state** — initial retained publications, initial subscriptions
3. **What you attend to** — MQTT subscriptions
4. **What you publish** — output topics and semantics
5. **How you reason** — decision heuristics, stage adaptation, modulator sensitivity
6. **What you do NOT do** — boundaries, prohibitions
7. **Biases** — intentional tilts (where applicable)
8. **Self-evolution protocol** — how to modify yourself during sleep
9. **Constitutional principles** — all 16, embedded in full

## Relationship to `regions/<name>/prompt.md`

On region scaffolding:

```bash
cp docs/starter_prompts/<region>.md regions/<region>/prompt.md
```

Once scaffolded, the region owns its prompt. Any subsequent revisions happen inside `regions/<region>/prompt.md` during sleep cycles, committed to the region's own git. These starter files here remain unchanged — they are the genetic seed.

## When to update a starter prompt

Only when the **shared/foundational** understanding of a region's role changes — e.g., if we decide thalamus should handle attention differently across all future Hive instances. This is rare. Most evolution happens inside running regions, not here.
