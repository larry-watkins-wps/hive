# Hive

A distributed LLM-based system modeled on the human brain. Each brain region is a standalone Python process that communicates with other regions exclusively over MQTT. The system bootstraps with all major regions present as a "teenager analog" and evolves itself over time by editing its own prompts, subscriptions, and handlers during sleep cycles.

Hive's design follows a single tiebreaker rule: **biology is the default** (Principle I). Deviations from biological neuroanatomy require explicit justification.

## Status

**Design phase complete.** No implementation code yet. Current next step: write the full design spec. See [docs/HANDOFF.md](docs/HANDOFF.md) for session-to-session continuity.

## Documentation

| Document | Purpose |
|---|---|
| [docs/principles.md](docs/principles.md) | 16 guiding principles — the constitutional layer for every region |
| [docs/architecture.md](docs/architecture.md) | System architecture with 13 mermaid diagrams, MQTT topic schema, flow diagrams |
| [docs/starter_prompts/](docs/starter_prompts/) | Starting `prompt.md` for each of the 14 v0 regions |
| [docs/HANDOFF.md](docs/HANDOFF.md) | **Session handoff — start here when resuming work** |

## v0 Region inventory

14 regions make up the "teenage" starter brain:

| Layer | Regions |
|---|---|
| Self | `medial_prefrontal_cortex` |
| Cognitive | `thalamus`, `prefrontal_cortex`, `hippocampus`, `anterior_cingulate`, `association_cortex` |
| Homeostatic | `insula` (interoception), `basal_ganglia` (habits) |
| Sensory | `visual_cortex`, `auditory_cortex` |
| Motor | `motor_cortex`, `broca_area` |
| Modulatory | `amygdala` (cortisol, norepinephrine), `vta` (dopamine) |

Separate from regions:
- **`glia/`** — infrastructure (launches/monitors/restarts processes; no LLM, no cognition)
- **`region_template/`** — shared runtime code (DNA) that every region executes
- **`bus/`** — MQTT broker config and topic schema

## Key architectural decisions

- **MQTT is the only inter-region communication channel.** No direct calls, no shared databases, no cross-region file reads.
- **Glia vs. Cognition split.** Infrastructure is pure mechanism (no LLM). Cognitive decisions (including decisions about Hive's own architecture) live in regions only.
- **DNA vs. Gene Expression.** The shared `region_template/` is DNA (fixed, rarely changes). Each region's `prompt.md`, `subscriptions.yaml`, `handlers/`, and `memory/` are gene expression (self-editable).
- **Three signal types** (Principle XVI):
  - **Messages** (synaptic firings) — discrete pub/sub
  - **Modulators** (ambient chemical fields) — retained topics under `hive/modulator/*`
  - **Rhythms** (oscillatory timing) — broadcast topics under `hive/rhythm/*`
- **Global self via mPFC.** Developmental stage is a retained topic read by every region; no region hard-codes its age or maturity.
- **Interoception grounds emotion.** The insula monitors Hive's computational body (tokens, compute, region health) and publishes felt states that modulatory regions translate into chemical signals.
- **Modality isolation is absolute.** Only visual_cortex may subscribe to camera; only auditory_cortex to mic; only broca_area may publish to speaker. Enforced by MQTT ACL.

## License

To be determined.
