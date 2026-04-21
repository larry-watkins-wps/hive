# Hive

A distributed LLM-based system modeled on the human brain. Each brain region is a standalone Python process that communicates with other regions exclusively over MQTT. The system bootstraps with all major regions present as a "teenager analog" and evolves itself over time by editing its own prompts, subscriptions, and handlers during sleep cycles.

Hive's design follows a single tiebreaker rule: **biology is the default** (Principle I). Deviations from biological neuroanatomy require explicit justification.

## Status

**v0 implementation complete (2026-04-21).** All 10 phases done; 691 unit tests + 73 integration tests (3 option-b skips + 1 Windows non-admin skip) + 1 smoke-collectable pass; ruff clean. All 14 regions scaffolded; `glia/`, `bus/`, `region_template/`, `shared/`, `tools/` implemented; `docker-compose.yaml` at repo root. Next: Phase 11 (runtime evolution — first self-modification cycles). See [docs/HANDOFF.md](docs/HANDOFF.md) for the authoritative state snapshot and the "what to do next" prompt.

## Quickstart (new machine)

```bash
git clone https://github.com/larry-watkins-wps/hive.git
cd hive
bash scripts/setup.sh        # creates .venv, installs deps, copies .env.example → .env
source .venv/bin/activate    # Windows: .venv\Scripts\activate
# Edit .env and fill in ANTHROPIC_API_KEY at minimum.
python -m pytest tests/unit/ -q    # expect 691 passed
```

Docker Desktop running is required for component tests:

```bash
python -m pytest tests/component/ -m component -v    # expect all passed
```

## Running Hive

> **Windows users:** the setup scripts are bash — use Git Bash or WSL.

**One-time setup:**

1. Run setup (creates `.venv`, installs deps, seeds `.env`):
   ```bash
   bash scripts/setup.sh
   ```
2. Activate the virtual environment:
   ```bash
   # POSIX
   source .venv/bin/activate
   # Windows (Git Bash / PowerShell)
   .venv/Scripts/activate
   ```
3. Edit `.env` — fill in at minimum `ANTHROPIC_API_KEY` and all 15 `MQTT_PASSWORD_*` entries (14 regions + glia).

4. Regenerate `bus/passwd` from the env vars (requires `mosquitto_passwd` on PATH):
   ```bash
   bash scripts/make_passwd.sh
   ```

**Starting, checking, and stopping:**

```bash
# Start broker + glia + 14 regions via docker compose
python -m tools.hive_cli up

# Show heartbeat state for each region
python -m tools.hive_cli status

# Graceful shutdown
python -m tools.hive_cli down
```

> **Note on the `hive` shorthand:** the `hive up` / `hive status` / `hive down` console script is deferred to post-v0 packaging. Until then, use `python -m tools.hive_cli <subcommand>` as shown above.

See [docs/HANDOFF.md](docs/HANDOFF.md) for deeper operator context, environment-variable reference, and known runtime gotchas.

## Continuing work in Claude Code

Open Claude Code in the repo root:

```bash
claude-code
```

Then type `continue phase 11` (runtime evolution — first self-modification cycles). The agent will read `CLAUDE.md` → `docs/HANDOFF.md` automatically and resume work following the documented execution model.

## Documentation

| Document | Purpose |
|---|---|
| [CLAUDE.md](CLAUDE.md) | **Project guide for Claude Code agents — read first on every session.** |
| [docs/HANDOFF.md](docs/HANDOFF.md) | **Session handoff — source of truth for what's done and what's next.** |
| [docs/principles.md](docs/principles.md) | 16 guiding principles — the constitutional layer for every region |
| [docs/architecture.md](docs/architecture.md) | System architecture with 13 mermaid diagrams, MQTT topic schema, flow diagrams |
| [docs/superpowers/specs/2026-04-19-hive-v0-design.md](docs/superpowers/specs/2026-04-19-hive-v0-design.md) | Approved design spec (4,792 lines) — authoritative over plan prose |
| [docs/superpowers/plans/2026-04-19-hive-v0-plan.md](docs/superpowers/plans/2026-04-19-hive-v0-plan.md) | Implementation plan broken into tasks |
| [docs/starter_prompts/](docs/starter_prompts/) | Starting `prompt.md` for each of the 14 v0 regions |

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

## Development

- Python 3.11+ required (`LifecyclePhase` uses `StrEnum`).
- Lint: `python -m ruff check region_template/ glia/ tools/ tests/ shared/`.
- Unit tests: `python -m pytest tests/unit/ -q`.
- Component tests (require Docker): `python -m pytest tests/component/ -m component -v`.
- Commit-per-task is mandated by Principle XII; commits end with the `Co-Authored-By: Claude Opus 4.7 (1M context)` trailer.
