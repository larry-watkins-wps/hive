# Hive — Claude Code project guide

**Read this first, then `docs/HANDOFF.md`.** Everything else you need is linked from one of those two.

## What this project is

Hive is a distributed LLM-based system modeled on the human brain. 14 brain-region Python processes talk only over MQTT, each with its own memory, prompt, and handlers. Regions evolve themselves by editing their own code during sleep cycles. See [README.md](README.md) for the full overview and [docs/principles.md](docs/principles.md) for the 16 constitutional principles.

## How to resume work

**Observatory sub-project:** if the user types anything matching `continue observatory`, `continue observatory v1|v2|v3`, `resume observatory`, etc., read [observatory/CLAUDE.md](observatory/CLAUDE.md) and follow its resume protocol instead of this one. The observatory is a self-contained sub-project with its own spec, plan, prompts, and handoff tracked inside `observatory/`.

When the user types something like `continue phase 11`, `resume runtime evolution`, `start first self-mod cycle`, or similar post-v0 commands:

1. Read [docs/HANDOFF.md](docs/HANDOFF.md) in full. The Quick-reference table at the top is the authoritative state snapshot. The "Prompt for next Phase-11 session" at the bottom is your starting instruction.
2. Confirm state:
   ```bash
   git fetch origin && git checkout main && git log --oneline -10
   python -m pytest tests/unit/ -q            # expect 691 passed
   python -m ruff check src/region_template/ src/glia/ tools/ tests/ src/shared/
   ```
3. Read the relevant sections of:
   - `docs/superpowers/specs/2026-04-19-hive-v0-design.md` — **authoritative design spec** (4,792 lines).
   - `docs/superpowers/plans/2026-04-19-hive-v0-plan.md` — task-level implementation plan.
4. Execute using the model below.

## Execution model — `superpowers:subagent-driven-development`

Per-task discipline:

- **Fresh implementer subagent per task.** Never reuse context. Craft self-contained prompts with full spec excerpts, existing-contract surface, and known gotchas.
- **Two-stage review after each implementer:** spec-compliance review first (`general-purpose` subagent), then code-quality review (`superpowers:code-reviewer` subagent). Fix-loop on anything Important+.
- **One commit per plan task** + review-fix commits as needed. HEREDOC commit messages ending with:
  ```
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
- **Verify after each task:**
  ```bash
  python -m pytest tests/unit/ -q
  python -m ruff check src/region_template/ src/glia/ tools/ tests/ src/shared/
  ```

## Authority ordering

1. **Spec wins over plan prose.** If `2026-04-19-hive-v0-design.md`'s code block disagrees with the plan's Step-N text, follow the spec and flag the discrepancy in the implementer prompt.
2. **Biology wins ties.** Principle I — when a Python idiom fights the biological metaphor, biology wins.
3. **User (Larry) instructions always override.**

## Cumulative gotchas (save rediscovering these)

- **`ConnectionError` in `region_template/errors.py` shadows the stdlib.** Fully-qualify (`region_template.errors.ConnectionError`) or alias on import.
- **`LifecyclePhase` is `StrEnum`** (Python 3.11+). `str(phase)` is lowercase (`"wake"`, not `"LifecyclePhase.WAKE"`).
- **`LlmError`** first positional arg is the kind string; `.kind` property exposes it.
- **`tool_use: "wizard"` raises `ConfigError`** — only `none | basic | advanced` per spec §F.2.
- **Ruff config lives at workspace root `pyproject.toml`.** Package-level `src/region_template/pyproject.toml` and `src/shared/pyproject.toml` MUST NOT re-declare `[tool.ruff]` / `[tool.mypy]` / `[tool.pytest.ini_options]` blocks.
- **`src/` layout (2026-04-23):** `region_template/`, `glia/`, `shared/` live under `src/`. Container-side paths (`/hive/region_template`, `/hive/shared`, `/hive/glia`) unchanged — only host-side moved. CI `PYTHONPATH=${{ github.workspace }}/src`. Developers running locally need `PYTHONPATH=./src` or equivalent until full pip-install cleanup lands.
- **`MemoryStore.stm_size_bytes_sync()`** is the lock-free sync helper for `_check_sleep_triggers`. Async path is `stm_size_bytes()`.
- **litellm pinned `>=1.54,<2`** — pre-1.54 has Windows long-path extraction issues; 1.60+ may have `cost_per_token` signature drift.
- **Windows-specific:**
  - `_atomic_write_text` in `self_modify.py` uses `O_BINARY` to avoid LF→CRLF translation.
  - `tests/component/conftest.py` forces `WindowsSelectorEventLoopPolicy` (aiomqtt needs `add_reader`/`add_writer`) and disables testcontainers Ryuk (port 8080 probe fails).
  - `__main__.py` uses `signal.signal(SIGBREAK, …)` + `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` for graceful shutdown.
- **`compileall` in the sleep pipeline writes `__pycache__/`**, which is mitigated three ways: `PYTHONDONTWRITEBYTECODE=1` env, post-check cleanup, and a `.gitignore` written by `GitTools._ensure_repo`.
- **`structlog` 25.x maps `warn` → `warning` internally.** `region_template/logging_setup.py` installs a `_remap_warning_to_warn` processor to satisfy spec §H.1.2's lowercase-`warn` requirement.
- **Two stray files at repo root** (`=2.6`, `=24`) are leftover pip-install typos. Leave them alone.

## Workflow reminders

- **Commit-per-task is mandated by Principle XII.** Granular history is a feature, not a burden.
- **Larry designs before coding.** Don't re-brainstorm the design or plan. If you find a gap, flag it — don't silently improvise.
- **Auto mode may be active.** Execute on routine decisions; pause only for spec conflicts, risky ops (destructive git, pushes to shared branches without scope), or Larry's explicit checkpoints.
- **Infrastructure (glia) does not deliberate; cognition (regions) does not execute infrastructure.** Don't cross this line.
- **Update HANDOFF.md at the end of every meaningful session** — bump `Last updated`, update the progress table, add follow-up items.
- **Never edit across region boundaries.** Each region's `regions/<name>/` is that region's sovereign territory (Principle III). Cross-region coordination happens via MQTT signals, not file writes. If you find yourself editing `regions/<A>/` while working on `regions/<B>/`, stop — that's a spec violation.
- **Self-modification is sleep-only.** Regions may only edit their own `prompt.md`, `subscriptions.yaml`, `handlers/`, and `memory/` during a sleep cycle (Principle IX). `region_template/` (DNA) is read-only from a region's perspective and changes only via the cosign-gated code-change path.
