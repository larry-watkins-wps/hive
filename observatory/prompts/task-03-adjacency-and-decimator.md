# Implementer prompt — Observatory v1, Task 3: Adjacency matrix + decimator

## Context

You are a fresh implementer subagent executing **Task 3** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1 and 2 have shipped with review-fixes. The full observatory suite is 20 passed, ruff clean. Current HEAD is commit `1978fc5`.

Task 3 adds two pure-function components:

- `observatory/adjacency.py` — rolling 5 s-window message-rate matrix per `(source, destination)` pair. Drives edge thickness and link-spring distance in the 3D scene.
- `observatory/decimator.py` — per-client envelope drop logic. When a WS client exceeds `max_rate` envelopes per 1 s window, drop further envelopes until the window rotates.

Both are synchronous, in-memory, and have no external dependencies. This is a small, mechanical task — the plan code is nearly complete; TDD discipline is the main deliverable.

## Authoritative documents (read first)

- **Plan (Task 3):** `observatory/docs/plans/2026-04-20-observatory-plan.md` — search for `### Task 3:` (~line 660). Has complete code blocks for all four files and Step 9 commit message.
- **Spec:** `observatory/docs/specs/2026-04-20-observatory-design.md` — read only if the plan is ambiguous. Spec wins on conflicts.
- **Sub-project guide:** `observatory/CLAUDE.md` — scope boundary + execution model.
- **Prior precedent:** `observatory/memory/decisions.md` (6 entries) — read to understand the mechanical ruff-fix conventions already in effect.
- **Existing code:** `observatory/ring_buffer.py`, `observatory/retained_cache.py` — style references.

## Your scope

Execute all 9 steps of Task 3 exactly as written in the plan:

1. Write failing test `observatory/tests/unit/test_adjacency.py` (4 tests).
2. Run it — confirm `ModuleNotFoundError`.
3. Implement `observatory/adjacency.py`.
4. Run tests — confirm all pass.
5. Write failing test `observatory/tests/unit/test_decimator.py` (4 tests).
6. Run it — confirm failure.
7. Implement `observatory/decimator.py`.
8. Run both test files — confirm all pass.
9. `python -m ruff check observatory/` clean, then commit with the plan's Step 9 HEREDOC.

## Important constraints

- **Python venv:** `source .venv/Scripts/activate` before running `python -m pytest` / `python -m ruff` (system python lacks pytest/ruff).
- **One commit** at the end of the task, scoped to the four new files only. Commit message HEREDOC ending with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **Scope:** touch only the four Task 3 files. Do NOT modify other observatory files. Do NOT touch `region_template/`, `glia/`, `regions/`, `bus/`, `shared/`, `tools/`, top-level `tests/`, or `observatory/pyproject.toml`.
- **Ruff workspace config is at repo root.** Plan code blocks may fail lint (precedent: UP037 quoted forward refs, UP035 `typing.Iterable`, PLR2004 magic numbers in tests). Apply the same minimal mechanical fixes as prior tasks — check `observatory/memory/decisions.md` for the full list and imitate. If a NEW kind of ruff fix is needed beyond those documented patterns, log it in `decisions.md`.
- **TDD discipline:** red-first, then green. Do not write the implementation before the failing test.
- **Pre-existing files untouched** except `decisions.md` (append-only) if a new non-obvious call is needed.

## Known issues in the plan's code (read carefully before implementing)

1. **`test_decimator.py` uses `for i in range(...)` with an unused `i`.** Ruff may flag `B007` or similar. If so, rename `i` → `_`. This is in Step 5's test code — the loop variables are unused.

2. **`Decimator.should_keep` has a dead branch (cosmetic).** In plan Step 7 the code does `if _is_low_priority(topic): self._dropped_in_window += 1 else: self._dropped_in_window += 1` — both arms do the same thing. Ruff `SIM108` / `B-rules` may flag. The v1 intent (per the comment "v1 simplification: once over budget, drop everything further this window") is that priority is NOT yet differentiated — the decimator is a simple per-window budget, and the `_is_low_priority` hook exists for future use. Clean up this dead branch to just unconditionally `self._dropped_in_window += 1` and remove the `_is_low_priority` call entirely if it becomes unused; log the simplification in `decisions.md` and note that the `_LOW_PRIORITY_PREFIXES` constant + `_is_low_priority` helper are retained for the v1.1 differentiation that the plan's comment anticipates.

3. **Tests that assert magic-number equalities will need `# noqa: PLR2004`.** Apply the same pattern as prior tasks.

4. **Top-of-file `from __future__ import annotations`** — plan already has it. Keep it.

## What you must NOT do

- Do NOT implement Task 4 (MQTT subscriber).
- Do NOT modify ring buffer, retained cache, region registry, or types.
- Do NOT use `git add -A` or `git add .` — stage only the Task 3 files explicitly.
- Do NOT invent new behaviors beyond what the plan specifies; this is mechanical execution with the minimum ruff fixes.
- Do NOT skip the red→green TDD cycle.

## Verification commands

After each component:
```bash
source .venv/Scripts/activate
python -m pytest observatory/tests/unit/test_adjacency.py observatory/tests/unit/test_decimator.py -v
python -m ruff check observatory/
```

Full-suite sanity check before commit:
```bash
python -m pytest observatory/tests/unit/ -q     # expect 20 prior + 4 + 4 = 28 passed
python -m ruff check observatory/               # clean
```

## Report back (<200 words)

- Files created (paths)
- Test counts (new / full observatory suite)
- Ruff result
- Commit SHA + subject
- Any deviations from the plan and rationale (logged in `decisions.md` if material)
- Anything surprising worth flagging for review
