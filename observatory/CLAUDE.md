# Observatory — Claude Code sub-project guide

**Read this first, then `observatory/HANDOFF.md`.**

This directory is self-contained. Specs, plans, prompts, and session memory for the observatory live here — not in the top-level `docs/superpowers/` tree.

## What this sub-project is

The observatory is a 3D visual instrument for watching Hive think. It reads MQTT and reads region filesystems, then renders a force-directed 3D scene in a browser. It is an *instrument*, not a participant: it never publishes to MQTT and never writes to region files. See [docs/specs/2026-04-20-observatory-design.md](docs/specs/2026-04-20-observatory-design.md) for the full design.

## How to resume

When the user types `continue observatory`, `continue observatory v1|v2|v3`, `resume observatory`, or anything similar:

1. Read `observatory/HANDOFF.md` in full. The progress table is the authoritative state snapshot. The "Prompt for next session" block at the bottom is your starting instruction.
2. Confirm state:
   ```bash
   git log --oneline -10 -- observatory/
   python -m pytest observatory/tests/ -q          # when tests exist
   python -m ruff check observatory/                # when code exists
   ```
3. Read the relevant sections of:
   - `observatory/docs/specs/2026-04-20-observatory-design.md` — authoritative design spec.
   - `observatory/docs/plans/2026-04-20-observatory-plan.md` — task-level implementation plan (written by `writing-plans`).
4. Execute per `superpowers:subagent-driven-development`, scoped to `observatory/`.

## Execution model — `superpowers:subagent-driven-development`

Same discipline as the main Hive project, but scoped to this sub-project:

- **Fresh implementer subagent per task.** Never reuse context. Craft self-contained prompts with full spec excerpts, existing-contract surface, and known gotchas.
- **Two-stage review after each implementer:** spec-compliance review first (`general-purpose` subagent), then code-quality review (`superpowers:code-reviewer`). Fix-loop on anything Important+.
- **One commit per plan task.** HEREDOC commit messages ending with:
  ```
  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  ```
- **Store implementer prompts** in `observatory/prompts/` for audit.
- **Log non-obvious decisions** in `observatory/memory/decisions.md` with date, question, and call made.
- **Update HANDOFF.md at the end of every meaningful session** — bump `Last updated`, update the progress table, add follow-up items.

## Scope boundary

The observatory is an instrument, not a participant. It reads MQTT and reads region filesystems. It does not write to either.

Do **not** touch `region_template/`, `glia/`, `regions/`, `bus/`, or `shared/` unless the task explicitly requires it — the observatory is read-only toward Hive. If a task seems to require a write into Hive, that is either a spec bug (flag it) or the task belongs in the main Hive tracks, not here.

## Authority ordering

1. **Spec wins over plan prose.** `observatory/docs/specs/2026-04-20-observatory-design.md`'s text is authoritative over any plan step that conflicts.
2. **Biology wins ties in Hive**, but the observatory sits outside Hive's biological model — it is the neuroscientist's microscope, not an organ. Constitutional principles that govern regions do not bind the observatory.
3. **User (Larry) instructions always override.**

## Cumulative gotchas

*(Populated as we hit them during implementation. Initial list seeded from top-level CLAUDE.md gotchas that are likely to recur here.)*

- **Windows-specific:** see top-level `CLAUDE.md` for `WindowsSelectorEventLoopPolicy` requirements, path-separator caveats, and signal handling. aiomqtt needs `add_reader`/`add_writer` which the selector event loop provides.
- **`aiomqtt` version pinning** — keep in sync with `region_template/mqtt_client.py`'s pin so both talk to the same broker the same way.
- **Ruff config lives at workspace root `pyproject.toml`.** `observatory/pyproject.toml` MUST NOT re-declare `[tool.ruff]` / `[tool.mypy]` / `[tool.pytest.ini_options]` blocks.

## Workflow reminders

- **Commit-per-task.** Granular history is a feature; the plan tasks map to commits one-to-one.
- **Do not re-brainstorm the design.** The spec in `docs/specs/` is approved. If a gap surfaces, log it in `memory/decisions.md` and flag it — do not silently improvise.
- **Observatory crashing must not affect Hive.** Keep it a clean sidecar: no glia dependency, no region dependency. It connects to MQTT and reads files, nothing more.
