# Hive v0 — MQTT Topic Catalog

> Generated from spec §B.4 (docs/superpowers/specs/2026-04-19-hive-v0-design.md).
> Ops reference for broker/ACL work. Keep in sync with spec; do not edit in isolation.

This is the single source of truth for topics in v0. `bus/topic_schema.md` MUST be
regenerated from this table during implementation. Each row lists the topic, retained
flag, QoS, publisher ACL, subscriber ACL, and content_type.

Legend:

- **R** = retained flag
- **QoS** = default publish QoS (consumers MAY subscribe at lower)
- **Publishers** = who MAY publish (glia-enforced via ACL template B.6)
- **Subscribers** = who MAY subscribe (same)
- `*` in a column means "any region that declares interest"
- `—` means "none" (topic is terminal or one-way)

## Hardware — raw I/O, ACL-gated

| Topic | R | QoS | Publishers | Subscribers | Content |
|---|---|---|---|---|---|
| `hive/hardware/mic` | N | 0 | `auditory_cortex` (producer handler, or OS bridge running as auditory_cortex) | `auditory_cortex` | raw bytes (not envelope) |
| `hive/hardware/camera` | N | 0 | `visual_cortex` | `visual_cortex` | raw bytes |
| `hive/hardware/speaker` | N | 1 | `broca_area` | glia's audio-bridge (not a region) | raw bytes |
| `hive/hardware/motor` | N | 1 | `motor_cortex` | glia's motor-bridge | raw bytes |

Hardware bridges are Section E.8.

## Sensory — processed output, broadcast-safe

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/sensory/visual/processed` | N | 1 | `visual_cortex` | `*` |
| `hive/sensory/visual/features` | N | 1 | `visual_cortex` | `*` |
| `hive/sensory/auditory/text` | N | 1 | `auditory_cortex` | `*` |
| `hive/sensory/auditory/features` | N | 1 | `auditory_cortex` | `*` |
| `hive/sensory/auditory/events` | N | 1 | `auditory_cortex` | `*` |
| `hive/sensory/input/text` | N | 1 | external bridge (host typing) | `*` |

## Cognitive — inter-region messaging

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/cognitive/thalamus/attend` | N | 1 | `thalamus` | `*` |
| `hive/cognitive/prefrontal/plan` | N | 1 | `prefrontal_cortex` | `*` |
| `hive/cognitive/hippocampus/query` | N | 1 | `*` | `hippocampus` |
| `hive/cognitive/hippocampus/response` | N | 1 | `hippocampus` | `*` |
| `hive/cognitive/association/integrate` | N | 1 | `association_cortex` | `*` |
| `hive/cognitive/<region>/#` | N | 1 | `*` (to publish TO `<region>`) | `<region>` (only) |

The wildcard rule: `hive/cognitive/<region>/request` is a dedicated inbox for `<region>`.
Only `<region>` subscribes. Any region publishes.

## Motor — pre-hardware intents

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/motor/intent` | N | 1 | `prefrontal_cortex`, `basal_ganglia` | `motor_cortex` |
| `hive/motor/intent/cancel` | N | 1 | `prefrontal_cortex` | `motor_cortex` |
| `hive/motor/speech/intent` | N | 1 | `prefrontal_cortex`, `basal_ganglia` | `broca_area` |
| `hive/motor/speech/cancel` | N | 1 | `prefrontal_cortex` | `broca_area` |
| `hive/motor/speech/complete` | N | 1 | `broca_area` | `*` |
| `hive/motor/complete` | N | 1 | `motor_cortex` | `*` |
| `hive/motor/failed` | N | 1 | `motor_cortex`, `broca_area` | `*` |
| `hive/motor/partial` | N | 1 | `motor_cortex` | `*` |

## System — framework/infrastructure

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/system/heartbeat/<region>` | N (normal); retained on LWT | 1 | `<region>` | `glia` |
| `hive/system/sleep/request` | N | 1 | `*` | `glia` |
| `hive/system/sleep/granted` | N | 1 | `glia` | `*` |
| `hive/system/sleep/force` | N | 1 | `glia`, `anterior_cingulate` | `*` |
| `hive/system/restart/request` | N | 1 | `*` | `glia` |
| `hive/system/spawn/proposed` | N | 1 | `*` | `anterior_cingulate`, `hippocampus` |
| `hive/system/spawn/request` | N | 1 | `anterior_cingulate` | `glia` |
| `hive/system/spawn/complete` | N | 1 | `glia` | `*` |
| `hive/system/spawn/failed` | N | 1 | `glia` | `*` |
| `hive/system/spawn/query` | N | 1 | `*` | `glia` |
| `hive/system/spawn/query_response` | N | 1 | `glia` | `*` |
| `hive/system/codechange/proposed` | N | 1 | `*` | `anterior_cingulate`, external human |
| `hive/system/codechange/approved` | N | 1 | `anterior_cingulate` (co-signed) | `glia` |
| `hive/system/metrics/compute` | R (last value) | 0 | `glia` | `*` |
| `hive/system/metrics/tokens` | R | 0 | `glia` | `*` |
| `hive/system/metrics/region_health` | R | 0 | `glia` | `*` |
| `hive/system/region_stats/<region>` | N | 0 | `<region>` | `glia` |

## Metacognition — ACC channels

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/metacognition/error/detected` | N | 1 | `*` | `anterior_cingulate`, `glia` (logging) |
| `hive/metacognition/conflict/observed` | N | 1 | `anterior_cingulate`, `medial_prefrontal_cortex` | `*` |
| `hive/metacognition/reflection/request` | N | 1 | `*` | `medial_prefrontal_cortex`, `anterior_cingulate` |
| `hive/metacognition/reflection/response` | N | 1 | `medial_prefrontal_cortex`, `anterior_cingulate` | `*` |

## Attention — shared state

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/attention/focus` | **R** | 1 | `prefrontal_cortex` | `*` |
| `hive/attention/salience` | **R** | 1 | `thalamus` | `*` |

## Self — global identity

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/self/identity` | **R** | 1 | `medial_prefrontal_cortex` | `*` |
| `hive/self/values` | **R** | 1 | `medial_prefrontal_cortex` | `*` |
| `hive/self/personality` | **R** | 1 | `medial_prefrontal_cortex` | `*` |
| `hive/self/autobiographical_index` | **R** | 1 | `medial_prefrontal_cortex` | `*` |

## Interoception — felt body state

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/interoception/compute_load` | **R** | 0 | `insula` | `*` |
| `hive/interoception/token_budget` | **R** | 0 | `insula` | `*` |
| `hive/interoception/region_health` | **R** | 0 | `insula` | `*` |
| `hive/interoception/felt_state` | **R** | 0 | `insula` | `*` |

## Habit

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/habit/suggestion` | N | 1 | `basal_ganglia` | `motor_cortex`, `broca_area`, `prefrontal_cortex` |
| `hive/habit/reinforce` | N | 1 | `vta` | `basal_ganglia` |
| `hive/habit/learned` | N | 1 | `basal_ganglia` | `*` |

## Modulator — ambient chemical fields

All retained. QoS 0 (publisher re-publishes often; occasional loss is acceptable,
retained value catches new subscribers).

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/modulator/dopamine` | **R** | 0 | `vta` | `*` |
| `hive/modulator/cortisol` | **R** | 0 | `amygdala` (v0) | `*` |
| `hive/modulator/norepinephrine` | **R** | 0 | `amygdala` (v0) | `*` |
| `hive/modulator/serotonin` | **R** | 0 | `raphe_nuclei` (post-v0) | `*` |
| `hive/modulator/acetylcholine` | **R** | 0 | `basal_forebrain` (post-v0) | `*` |
| `hive/modulator/oxytocin` | **R** | 0 | `hypothalamus` (post-v0) | `*` |

**Important**: `serotonin` etc. have publisher slots reserved even in v0 so new modulator
regions spawn without requiring an ACL migration. At v0 the slots are empty (no publisher);
subscribers see no retained value and treat that as the neutral/default.

## Rhythm — oscillatory timing

Broadcast, not retained. A late subscriber simply misses prior ticks.

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/rhythm/gamma` | N | 0 | glia's `rhythm_generator` bridge | `*` |
| `hive/rhythm/beta` | N | 0 | glia | `*` |
| `hive/rhythm/theta` | N | 0 | glia | `*` |

Rhythm generator is a glia service (E.7). It publishes a tiny envelope:

```json
{"beat": 12345, "rate_hz": 40, "ts": "2026-04-19T10:30:00.025Z"}
```

`beat` is a monotonic counter per rhythm band.

## Broadcast

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/broadcast/shutdown` | N | 1 | `glia` | `*` |
