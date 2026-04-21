# Implementer prompt — Observatory v1, Task 1: Package scaffolding + types + ring buffer

## Context

You are a fresh implementer subagent executing **Task 1** of the Observatory v1 implementation plan. The observatory is a read-only 3D visual instrument for Hive: it subscribes to MQTT, reads region filesystem state, and serves a FastAPI + React frontend. It is a sidecar — it must never publish to MQTT or write to region files.

This is a sub-project under `observatory/` in an existing Python monorepo (`C:\repos\hive`). The main repo already has `region_template/`, `glia/`, `shared/`, `regions/`, and `bus/` packages. You are adding a sibling package.

## Authoritative documents

- **Plan (authoritative for this task):** `observatory/docs/plans/2026-04-20-observatory-plan.md` — read Task 1 in full (search for "### Task 1:" around line 114). It lists every file to create and gives exact code blocks for all of them.
- **Spec (authoritative overall):** `observatory/docs/specs/2026-04-20-observatory-design.md` — read sections relevant to types and ring buffer if the plan is ambiguous. Spec wins over plan on conflicts; log any discrepancy in `observatory/memory/decisions.md`.
- **Sub-project guide:** `observatory/CLAUDE.md` — execution model and scope boundary.
- **Top-level guide:** `CLAUDE.md` at repo root — cumulative gotchas that apply project-wide.

## Your scope

Execute **every step 1–13** of Task 1 exactly as written in the plan:

1. `observatory/__init__.py`
2. `observatory/pyproject.toml` — **NO `[tool.*]` blocks** (workspace root owns ruff/mypy/pytest config — see top-level CLAUDE.md gotcha)
3. `observatory/.gitignore`
4. `observatory/config.py` — env-var-driven `Settings` dataclass
5. `observatory/types.py` — `RingRecord`, `RegionStats`, `RegionMeta`
6. Verify `observatory/memory/decisions.md` exists and is non-empty (it was pre-seeded — do NOT overwrite it)
7. `observatory/prompts/.gitkeep` (empty file; this directory already exists — just add the placeholder)
8. `observatory/tests/__init__.py` and `observatory/tests/unit/__init__.py` (empty)
9. Write the failing test `observatory/tests/unit/test_ring_buffer.py`
10. Run the test — confirm it fails with `ModuleNotFoundError`
11. Implement `observatory/ring_buffer.py`
12. Run the test — confirm all 5 tests pass
13. Run `python -m ruff check observatory/` — expect clean
14. Commit with the exact HEREDOC message shown in the plan (Step 13)

Use the exact code blocks from the plan — they are authoritative for this task. TDD discipline required: write the test FIRST, confirm it fails, then write the implementation.

## Important constraints

- **One commit, produced at the end of this task.** Commit message must end with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **Scope boundary:** do not touch `region_template/`, `glia/`, `regions/`, `bus/`, `shared/`, `tools/`, or `tests/` (top-level). The working tree has uncommitted changes in `tools/hive_cli.py` and `tests/integration/test_hive_cli.py` from prior unrelated work — **leave those alone**, do not stage or commit them.
- **Windows:** this is a Windows host. Use forward slashes in code; the top-level CLAUDE.md notes project-wide Windows gotchas — none apply directly to Task 1, but be aware.
- **Ruff config is at workspace root.** Do not add `[tool.ruff]` to `observatory/pyproject.toml`.
- **Python 3.11+.** The plan code uses PEP 604 union syntax (`str | None`) and `from __future__ import annotations`.

## What you must NOT do

- Do NOT re-brainstorm or re-design. The plan has exact code.
- Do NOT implement Tasks 2+; stop at end of Task 1.
- Do NOT commit unrelated changes.
- Do NOT use `git add -A` or `git add .` — add only observatory/ paths.
- Do NOT skip the TDD red→green cycle.
- Do NOT overwrite `observatory/memory/decisions.md` (it is pre-seeded with two entries).

## Verification commands

After each implementation step, run:
```bash
python -m pytest observatory/tests/unit/test_ring_buffer.py -v
python -m ruff check observatory/
```

Final verification:
```bash
git log --oneline -3
git status
```

Commit must exist on the current branch. `git status` should be clean for observatory/ paths (uncommitted `tools/` and `tests/integration/` changes unrelated to this task may remain).

## Report back

Return a short summary (<200 words):
- Which files were created (paths)
- Test results (N passed)
- Ruff result (clean or not)
- Commit SHA and subject line
- Any deviations from the plan and why (should be none; flag and log any surprises in `observatory/memory/decisions.md` if they occur)
- Anything the reviewer should pay special attention to
