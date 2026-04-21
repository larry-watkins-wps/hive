# Implementer prompt — Observatory v1, Task 2: Retained cache + region registry

## Context

You are a fresh implementer subagent executing **Task 2** of the Observatory v1 implementation plan. Task 1 (package scaffolding + ring buffer) is complete at commit `3896f64`, with review fixes in `491a36a`. The package now exists at `observatory/` with `config.py`, `types.py`, `ring_buffer.py`, and their tests.

Task 2 adds two small stateful components: a retained-topic cache (`topic → latest envelope`) and a region registry seeded from `glia/regions_registry.yaml` and enriched by observed heartbeat payloads.

## Authoritative documents (read first)

- **Plan (Task 2):** `observatory/docs/plans/2026-04-20-observatory-plan.md` — search for `### Task 2:` (~line 390). Has exact code blocks for all four new files.
- **Spec:** `observatory/docs/specs/2026-04-20-observatory-design.md` — read if the plan is ambiguous. Spec wins on conflicts.
- **Sub-project guide:** `observatory/CLAUDE.md` — scope boundary + execution model.
- **Top-level guide:** `CLAUDE.md` at repo root — cumulative Python gotchas.
- **Existing code:** `observatory/types.py` (uses `RegionMeta`, `RegionStats`) and `observatory/ring_buffer.py` (as a style reference).
- **Registry source of truth:** `glia/regions_registry.yaml` — the format the registry loads. Read it to confirm the schema matches the plan's YAML example.

## Your scope

Execute all 9 steps of Task 2 exactly as written in the plan:

1. Write failing test `observatory/tests/unit/test_retained_cache.py` (4 tests).
2. Run it — confirm `ModuleNotFoundError`.
3. Implement `observatory/retained_cache.py`.
4. Run tests — confirm all pass.
5. Write failing test `observatory/tests/unit/test_region_registry.py` (4 tests).
6. Run it — confirm failure.
7. Implement `observatory/region_registry.py`.
8. Run both test files — confirm all pass.
9. Ruff clean, then commit.

Use the exact code blocks from the plan. TDD red→green for each component.

## Important constraints

- **One commit** at the end of the task with the HEREDOC message shown in the plan (Step 9), ending with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **Scope:** touch only `observatory/retained_cache.py`, `observatory/region_registry.py`, and their two test files. Do NOT modify other observatory files, and do NOT touch `region_template/`, `glia/`, `regions/`, `bus/`, `shared/`, `tools/`, or top-level `tests/`.
- **Venv:** the project venv is at `.venv/` — activate with `source .venv/Scripts/activate` before running `python -m pytest` / `python -m ruff` (system python does not have pytest/ruff installed).
- **Ruff workspace config is at the repo-root `pyproject.toml`.** Do NOT add `[tool.*]` blocks to `observatory/pyproject.toml`. Expect the same lint strictness Task 1 hit (UP037, UP035, PLR2004 on magic numbers in tests). Apply the same mechanical fixes if needed — precedent is logged in `observatory/memory/decisions.md`.
- **Pre-existing files untouched:** do not overwrite `observatory/memory/decisions.md` except to log NEW non-obvious decisions (append-only).

## Gotchas (precedent from Task 1)

- Plan code blocks import `Iterable` from `typing` or use quoted forward refs — ruff UP035/UP037 will fail. Mechanically fix to `collections.abc.Iterable` and unquoted refs if needed.
- Tests that compare against literal ints (`== 42`, `== 500`, etc.) trigger PLR2004. Add `# noqa: PLR2004` on those lines (same pattern as `observatory/tests/unit/test_config.py` and `test_ring_buffer.py`).
- `from __future__ import annotations` at the top of every module (plan uses it consistently).
- Python 3.11+ target.
- `ruamel.yaml` is listed as a dep in `observatory/pyproject.toml`; confirm it's importable in the venv. If not, flag it — don't silently pivot to PyYAML.

## What you must NOT do

- Do NOT implement Task 3 (adjacency + decimator).
- Do NOT modify the existing `observatory/types.py` unless the plan explicitly requires it for Task 2 (it should not).
- Do NOT use `git add -A` or `git add .` — stage explicitly.
- Do NOT skip the TDD red→green cycle.
- Do NOT commit any stale changes from prior work (the working tree should be clean of non-observatory changes at this point; verify with `git status`).

## Verification commands

After each implementation:
```bash
source .venv/Scripts/activate
python -m pytest observatory/tests/unit/test_retained_cache.py observatory/tests/unit/test_region_registry.py -v
python -m ruff check observatory/
```

Full suite sanity check before commit:
```bash
python -m pytest observatory/tests/unit/ -q      # expect 9 prior + 4 + 4 = 17 passed
python -m ruff check observatory/                # clean
```

## Report back (<200 words)

- Which files created (paths)
- Test counts (new tests / full observatory suite)
- Ruff result
- Commit SHA + subject
- Any deviations from the plan and rationale (log in `observatory/memory/decisions.md` if material)
- Anything surprising worth flagging for review
