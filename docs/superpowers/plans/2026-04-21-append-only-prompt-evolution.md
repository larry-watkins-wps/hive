# Append-Only Prompt Evolution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each region's `prompt.md` truly immutable constitutional DNA and move self-evolution into an append-only per-region appendix (`memory/appendices/rolling.md`) that the runtime concatenates onto the system prompt at every LLM call that assembles one.

**Architecture:**
- Two new shared-DNA modules: `region_template/appendix.py` (`AppendixStore` — atomic append with dated H2 headers, lazy-create) and `region_template/prompt_assembly.py` (`load_system_prompt(region_root) -> str` — joins `prompt.md` + explicit delimiter + optional `rolling.md`).
- Sleep review now builds a **system** message from `load_system_prompt` and a **user** message from the STM/recent-events template. `_ReviewOutput` drops `prompt_edit` and gains `appendix_entry: str | None`. The review-result branch that used to call `self_modify.edit_prompt` now calls `AppendixStore.append`.
- `self_modify.edit_prompt` is **deleted** — there are no other callers once sleep stops using it, so a clean removal beats deprecation.
- §A.7.1 divergence (prompt is no longer a writable surface for regions) is documented in HANDOFF.

**Tech Stack:** Python 3.11+, pytest, ruff, existing `region_template` runtime (aiomqtt/litellm/structlog/docker-py), `_atomic_write_text` helper already in `region_template/self_modify.py`.

---

## File map

**Create:**
- `region_template/appendix.py` — `AppendixStore` class.
- `region_template/prompt_assembly.py` — `load_system_prompt` function.
- `tests/unit/test_appendix.py` — unit coverage for `AppendixStore`.
- `tests/unit/test_prompt_assembly.py` — unit coverage for `load_system_prompt`.
- `region_template/sleep_prompts/default_review_user.md` — new user-side template (stm/events/schema).
- `tests/integration/test_sleep_appendix_growth.py` — two-cycle integration test.

**Modify:**
- `region_template/sleep.py` — schema, `_ReviewOutput`, `_review_events`, `_apply_prompt_edit` → `_append_appendix`, `_load_review_prompt` → `_render_review_user_prompt`, `_format_commit_message` bool rename.
- `region_template/self_modify.py` — delete `edit_prompt` method + `_PROMPT_MAX_BYTES` constant.
- `region_template/sleep_prompts/default_review.md` — delete (replaced by system-side `load_system_prompt` output + new user-side template). Or retain as a compat stub if anyone documents it; plan chooses to delete for cleanliness.
- `tests/unit/test_sleep.py` — replace every `prompt_edit` reference with `appendix_entry`; swap the oversized-prompt recovery test for an `AppendixStore.append`-raises recovery test.
- `tests/unit/test_self_modify.py` — delete `edit_prompt` test block (lines ~140–195) and `_PROMPT_FIXTURE`.
- `tests/unit/test_runtime.py` — remove `"prompt_edit": None` from the scripted review payload.
- `docs/HANDOFF.md` — append Phase 11 subsection recording the decision and the §A.7.1 divergence.

---

### Task 1: `AppendixStore` skeleton + lazy-create contract

Create the module and its failing-test first. Coverage for Task 1 is just "empty rolling.md is lazy-created on first append".

**Files:**
- Create: `region_template/appendix.py`
- Create: `tests/unit/test_appendix.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_appendix.py` with:

```python
"""Unit tests for :mod:`region_template.appendix`.

The appendix store is the single writer of
``regions/<name>/memory/appendices/rolling.md``. It must:
  - lazy-create the file + parent dir on first append,
  - prepend an ISO-timestamped H2 header to every entry,
  - append atomically (read-modify-write via ``_atomic_write_text``),
  - tolerate externally-authored edits (runtime only guarantees
    "sleep appends"; it does not own the file exclusively).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from region_template.appendix import AppendixStore


@pytest.mark.asyncio
async def test_append_lazy_creates_file_and_parent(tmp_path: Path) -> None:
    region_root = tmp_path / "regions" / "test_region"
    region_root.mkdir(parents=True)
    store = AppendixStore(region_root)

    rolling = region_root / "memory" / "appendices" / "rolling.md"
    assert not rolling.exists()
    assert not rolling.parent.exists()

    await store.append(
        "Observed that text input produced no speech intent.",
        when=datetime(2026, 4, 22, 3, 14, 0, tzinfo=timezone.utc),
        trigger="quiet_window",
    )

    assert rolling.is_file()
    body = rolling.read_text(encoding="utf-8")
    assert "## 2026-04-22T03:14:00+00:00 — quiet_window" in body
    assert "Observed that text input produced no speech intent." in body
```

- [ ] **Step 2: Run the test and verify it fails with ModuleNotFoundError**

```bash
python -m pytest tests/unit/test_appendix.py::test_append_lazy_creates_file_and_parent -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'region_template.appendix'`.

- [ ] **Step 3: Write the minimal `AppendixStore` implementation**

Create `region_template/appendix.py`:

```python
"""Append-only prompt-evolution store.

Writes ``regions/<name>/memory/appendices/rolling.md`` — the single
per-region rolling appendix that the runtime concatenates onto the
system prompt at every LLM call (see :mod:`region_template.prompt_assembly`).

Design choices (see
``docs/superpowers/plans/2026-04-21-append-only-prompt-evolution.md``):

- Lazy-create: the file and its parent dir are created on the first
  successful append. No spawn-time scaffolding.
- Dated H2 headers: every entry is framed with
  ``## <ISO-timestamp> — <trigger>`` so the file is human-scannable
  and chronological.
- Atomic read-modify-write: Windows raw-append mode can partial-write
  under contention, and we already ship an atomic helper in
  :mod:`region_template.self_modify`. Reuse it.
- Tolerate external edits: the runtime's only contract is
  "sleep appends"; anything the user pastes in between cycles is
  preserved verbatim.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from region_template.self_modify import _atomic_write_text


_APPENDIX_SUBPATH = Path("memory") / "appendices" / "rolling.md"


class AppendixStore:
    """Single writer for ``rolling.md``. One instance per region."""

    def __init__(self, region_root: Path) -> None:
        self._region_root = region_root

    @property
    def path(self) -> Path:
        """Absolute path to the rolling appendix (may not yet exist)."""
        return self._region_root / _APPENDIX_SUBPATH

    async def append(
        self,
        entry: str,
        *,
        when: datetime | None = None,
        trigger: str = "sleep",
    ) -> None:
        """Append ``entry`` under a dated H2 header.

        Args:
            entry: The appendix body — a single paragraph of insight
                the region wants to commit to its evolving self.
                Whitespace-trimmed before writing.
            when: Timestamp for the header. Defaults to ``now(UTC)``.
            trigger: Short label for the header (e.g.
                ``"quiet_window"``, ``"cortisol_spike"``, ``"sleep"``).
        """
        stamp = (when or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        header = f"## {stamp} — {trigger}"
        body = entry.strip()
        section = f"{header}\n\n{body}\n"

        target = self.path
        existing = ""
        if target.exists():
            existing = target.read_text(encoding="utf-8")
            if existing and not existing.endswith("\n"):
                existing += "\n"
            if existing:
                existing += "\n"  # blank line between sections
        new_text = existing + section
        _atomic_write_text(target, new_text)
```

- [ ] **Step 4: Run the test and verify it passes**

```bash
python -m pytest tests/unit/test_appendix.py::test_append_lazy_creates_file_and_parent -v
```
Expected: PASS.

- [ ] **Step 5: Ruff check**

```bash
python -m ruff check region_template/appendix.py tests/unit/test_appendix.py
```
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add region_template/appendix.py tests/unit/test_appendix.py
git commit -m "$(cat <<'EOF'
feat(appendix): introduce AppendixStore for rolling per-region prompt appendix

Lazy-creates memory/appendices/rolling.md on first append. Writes dated
H2 sections atomically via the existing _atomic_write_text helper.
Unit-covered with a lazy-create assertion.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `AppendixStore.append` — chronological ordering + external-edit tolerance

Add two more behaviors that Task 1 left unproven: consecutive appends produce two separate dated sections in order, and a manually-edited rolling.md is preserved.

**Files:**
- Modify: `tests/unit/test_appendix.py`

- [ ] **Step 1: Write two failing tests**

Append to `tests/unit/test_appendix.py`:

```python
@pytest.mark.asyncio
async def test_two_appends_produce_two_sections_in_order(tmp_path: Path) -> None:
    region_root = tmp_path / "regions" / "test_region"
    region_root.mkdir(parents=True)
    store = AppendixStore(region_root)

    await store.append(
        "first cycle insight",
        when=datetime(2026, 4, 22, 3, 14, 0, tzinfo=timezone.utc),
        trigger="quiet_window",
    )
    await store.append(
        "second cycle insight",
        when=datetime(2026, 4, 22, 9, 41, 0, tzinfo=timezone.utc),
        trigger="quiet_window",
    )

    body = store.path.read_text(encoding="utf-8")
    first_idx = body.index("first cycle insight")
    second_idx = body.index("second cycle insight")
    assert first_idx < second_idx
    assert body.count("## 2026-04-22T03:14:00+00:00") == 1
    assert body.count("## 2026-04-22T09:41:00+00:00") == 1


@pytest.mark.asyncio
async def test_external_content_is_preserved(tmp_path: Path) -> None:
    region_root = tmp_path / "regions" / "test_region"
    (region_root / "memory" / "appendices").mkdir(parents=True)
    rolling = region_root / "memory" / "appendices" / "rolling.md"
    rolling.write_text(
        "# Rolling appendix\n\nSome notes I pasted in by hand.\n",
        encoding="utf-8",
    )

    store = AppendixStore(region_root)
    await store.append(
        "scheduled insight",
        when=datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc),
        trigger="sleep",
    )

    body = rolling.read_text(encoding="utf-8")
    assert "Some notes I pasted in by hand." in body
    assert "scheduled insight" in body
    assert body.index("Some notes I pasted in by hand.") < body.index("scheduled insight")
```

- [ ] **Step 2: Run the tests and verify they pass (no implementation change expected)**

```bash
python -m pytest tests/unit/test_appendix.py -v
```
Expected: all three PASS. The initial implementation from Task 1 already handles these cases; this step proves it.

If either test fails, fix the implementation to satisfy the contract (likely tweak in `append`'s handling of trailing newlines or blank-line separation). Re-run until green.

- [ ] **Step 3: Ruff check**

```bash
python -m ruff check tests/unit/test_appendix.py
```
Expected: no issues.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_appendix.py
git commit -m "$(cat <<'EOF'
test(appendix): cover chronological append + external-edit tolerance

Two extra tests: consecutive appends stay in chronological order with
correctly-stamped H2 headers, and any content present before the first
runtime append is preserved verbatim. Pins AppendixStore's
"sleep only appends" contract.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `load_system_prompt` helper

The reusable context-assembly function. One LLM call site today (sleep review); future handler-driven calls will use the same helper.

**Files:**
- Create: `region_template/prompt_assembly.py`
- Create: `tests/unit/test_prompt_assembly.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_prompt_assembly.py`:

```python
"""Unit tests for :mod:`region_template.prompt_assembly`.

``load_system_prompt`` concatenates a region's immutable starter
prompt (``prompt.md``) with its append-only evolution appendix
(``memory/appendices/rolling.md``) using an explicit delimiter so the
LLM can tell "what I was born with" from "what I've learned".
"""

from __future__ import annotations

from pathlib import Path

from region_template.prompt_assembly import load_system_prompt


def _make_region(tmp_path: Path, *, starter: str, rolling: str | None) -> Path:
    root = tmp_path / "regions" / "test_region"
    root.mkdir(parents=True)
    (root / "prompt.md").write_text(starter, encoding="utf-8")
    if rolling is not None:
        appendix_dir = root / "memory" / "appendices"
        appendix_dir.mkdir(parents=True)
        (appendix_dir / "rolling.md").write_text(rolling, encoding="utf-8")
    return root


def test_returns_starter_verbatim_when_no_appendix(tmp_path: Path) -> None:
    starter = "You are the test region.\n\nBe curious.\n"
    root = _make_region(tmp_path, starter=starter, rolling=None)
    assert load_system_prompt(root) == starter


def test_concatenates_with_explicit_delimiter(tmp_path: Path) -> None:
    starter = "You are the test region.\n"
    rolling = "## 2026-04-22T03:14:00+00:00 — quiet_window\n\nFirst insight.\n"
    root = _make_region(tmp_path, starter=starter, rolling=rolling)

    out = load_system_prompt(root)
    assert out.startswith(starter)
    assert "# Evolution appendix" in out
    assert out.endswith(rolling) or out.endswith(rolling.rstrip() + "\n")
    # The starter must appear before the delimiter, and the delimiter
    # before the appendix content, so the LLM reads them in order.
    assert out.index(starter) < out.index("# Evolution appendix")
    assert out.index("# Evolution appendix") < out.index("First insight.")


def test_empty_appendix_file_is_treated_as_absent(tmp_path: Path) -> None:
    starter = "You are the test region.\n"
    root = _make_region(tmp_path, starter=starter, rolling="")
    assert load_system_prompt(root) == starter
```

- [ ] **Step 2: Run the tests and verify they fail with ModuleNotFoundError**

```bash
python -m pytest tests/unit/test_prompt_assembly.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'region_template.prompt_assembly'`.

- [ ] **Step 3: Implement `load_system_prompt`**

Create `region_template/prompt_assembly.py`:

```python
"""System-prompt assembly: starter DNA + rolling evolution appendix.

The only public entry point is :func:`load_system_prompt`. It reads
``regions/<name>/prompt.md`` (immutable constitutional DNA written
once at region birth) and, if present and non-empty,
``regions/<name>/memory/appendices/rolling.md`` (append-only evolution
log maintained by :class:`region_template.appendix.AppendixStore`).

The two halves are joined with an explicit delimiter
(``# Evolution appendix``) so the LLM can distinguish "what I was
born with" from "what I've learned". Today the single call site is
``SleepCoordinator._review_events``; post-v0 handler-driven LLM calls
will use the same helper.
"""

from __future__ import annotations

from pathlib import Path


_APPENDIX_SUBPATH = Path("memory") / "appendices" / "rolling.md"
_DELIMITER = "\n\n---\n\n# Evolution appendix\n\n"


def load_system_prompt(region_root: Path) -> str:
    """Return the full system prompt for a region.

    Args:
        region_root: absolute path to ``regions/<name>/``.

    Returns:
        ``prompt.md`` content verbatim if no appendix exists or the
        appendix is empty; otherwise ``prompt.md`` + explicit
        delimiter + ``rolling.md`` content.
    """
    starter = (region_root / "prompt.md").read_text(encoding="utf-8")
    rolling_path = region_root / _APPENDIX_SUBPATH
    if not rolling_path.is_file():
        return starter
    rolling = rolling_path.read_text(encoding="utf-8")
    if not rolling.strip():
        return starter

    head = starter if starter.endswith("\n") else starter + "\n"
    return head + _DELIMITER.lstrip("\n") + rolling
```

- [ ] **Step 4: Run the tests and verify they pass**

```bash
python -m pytest tests/unit/test_prompt_assembly.py -v
```
Expected: all 3 PASS.

- [ ] **Step 5: Ruff check**

```bash
python -m ruff check region_template/prompt_assembly.py tests/unit/test_prompt_assembly.py
```
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add region_template/prompt_assembly.py tests/unit/test_prompt_assembly.py
git commit -m "$(cat <<'EOF'
feat(prompt_assembly): add load_system_prompt helper

Single shared entry point for assembling a region's system prompt.
Joins immutable starter prompt with optional rolling appendix using
an explicit "# Evolution appendix" delimiter so the LLM can tell
constitutional DNA from accumulated evolution.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Swap review schema — drop `prompt_edit`, add `appendix_entry`

Update `_ReviewOutput`, `_REVIEW_SCHEMA_STR`, and the parser. Parser silently ignores a legacy `prompt_edit` field (forward-compat: no persisted sleep output depends on it — PFC was reverted to `d7c84d6`).

**Files:**
- Modify: `region_template/sleep.py:90-120, 586-627`
- Modify: `tests/unit/test_sleep.py:176-200, 587-620`
- Modify: `tests/unit/test_runtime.py:122-140`

- [ ] **Step 1: Write failing parser tests**

In `tests/unit/test_sleep.py`, locate the existing parser-coverage block and append these new tests (find a natural location such as just after the last `_parse_review_output` test):

```python
@pytest.mark.asyncio
async def test_parse_review_accepts_appendix_entry(tmp_path: Path) -> None:
    root = _make_region_root(tmp_path)
    coord = _make_sleep_coordinator(root)
    payload = json.dumps(
        {
            "ltm_candidates": [],
            "prune_keys": [],
            "appendix_entry": "Cycle insight: input→intent gap.",
            "handler_edits": [],
            "needs_restart": False,
            "reason": "observed gap",
        }
    )
    out = coord._parse_review_output(payload)
    assert out.appendix_entry == "Cycle insight: input→intent gap."


@pytest.mark.asyncio
async def test_parse_review_silently_ignores_legacy_prompt_edit(
    tmp_path: Path,
) -> None:
    root = _make_region_root(tmp_path)
    coord = _make_sleep_coordinator(root)
    payload = json.dumps(
        {
            "ltm_candidates": [],
            "prune_keys": [],
            "prompt_edit": "legacy rewrite payload",
            "handler_edits": [],
            "needs_restart": False,
            "reason": "legacy shape",
        }
    )
    out = coord._parse_review_output(payload)
    assert out.appendix_entry is None
    # _ReviewOutput must not carry a prompt_edit attribute at all.
    assert not hasattr(out, "prompt_edit")
```

(If `_make_region_root` / `_make_sleep_coordinator` helpers don't exist with those exact names in `test_sleep.py`, use whatever factory names the file already uses — e.g. `_build_runtime` + `SleepCoordinator(runtime)`.)

- [ ] **Step 2: Run tests — expect failure**

```bash
python -m pytest tests/unit/test_sleep.py::test_parse_review_accepts_appendix_entry tests/unit/test_sleep.py::test_parse_review_silently_ignores_legacy_prompt_edit -v
```
Expected: both FAIL (`_ReviewOutput` has no `appendix_entry` field; `prompt_edit` still present).

- [ ] **Step 3: Update `_ReviewOutput` and `_REVIEW_SCHEMA_STR`**

In `region_template/sleep.py`, replace:

```python
@dataclass(frozen=True)
class _ReviewOutput:
    """Parsed LLM review result — internal."""

    ltm_candidates: list[dict[str, Any]] = field(default_factory=list)
    prune_keys: list[str] = field(default_factory=list)
    prompt_edit: str | None = None
    handler_edits: list[dict[str, Any]] = field(default_factory=list)
    needs_restart: bool = False
    reason: str = ""
```

with:

```python
@dataclass(frozen=True)
class _ReviewOutput:
    """Parsed LLM review result — internal.

    ``appendix_entry`` replaces the removed ``prompt_edit`` field
    (see ``docs/superpowers/plans/2026-04-21-append-only-prompt-evolution.md``).
    The LLM emits only the new appendix section body; the framework
    prepends the timestamped H2 header via
    :class:`region_template.appendix.AppendixStore`.
    """

    ltm_candidates: list[dict[str, Any]] = field(default_factory=list)
    prune_keys: list[str] = field(default_factory=list)
    appendix_entry: str | None = None
    handler_edits: list[dict[str, Any]] = field(default_factory=list)
    needs_restart: bool = False
    reason: str = ""
```

Then replace the schema constant:

```python
_REVIEW_SCHEMA_STR = """{
  "ltm_candidates": [
    {"filename": "str", "content": "str", "topic": "str",
      "importance": 0.0, "tags": ["str"], "reason": "str",
      "emotional_tag": "str or null"}
  ],
  "prune_keys": ["str"],
  "prompt_edit": "str or null",
  "handler_edits": [{"path": "str", "content": "str", "delete": false}],
  "needs_restart": false,
  "reason": "str"
}"""
```

with:

```python
_REVIEW_SCHEMA_STR = """{
  "ltm_candidates": [
    {"filename": "str", "content": "str", "topic": "str",
      "importance": 0.0, "tags": ["str"], "reason": "str",
      "emotional_tag": "str or null"}
  ],
  "prune_keys": ["str"],
  "appendix_entry": "str or null",
  "handler_edits": [{"path": "str", "content": "str", "delete": false}],
  "needs_restart": false,
  "reason": "str"
}"""
```

- [ ] **Step 4: Update the parser**

In `region_template/sleep.py`, replace the tail of `_parse_review_output`:

```python
        return _ReviewOutput(
            ltm_candidates=list(data.get("ltm_candidates") or []),
            prune_keys=list(data.get("prune_keys") or []),
            prompt_edit=data.get("prompt_edit"),
            handler_edits=list(data.get("handler_edits") or []),
            needs_restart=bool(data.get("needs_restart", False)),
            reason=str(data.get("reason", "") or ""),
        )
```

with:

```python
        appendix_raw = data.get("appendix_entry")
        appendix_entry: str | None
        if isinstance(appendix_raw, str) and appendix_raw.strip():
            appendix_entry = appendix_raw
        else:
            appendix_entry = None

        return _ReviewOutput(
            ltm_candidates=list(data.get("ltm_candidates") or []),
            prune_keys=list(data.get("prune_keys") or []),
            appendix_entry=appendix_entry,
            handler_edits=list(data.get("handler_edits") or []),
            needs_restart=bool(data.get("needs_restart", False)),
            reason=str(data.get("reason", "") or ""),
        )
```

Note: `data.get("prompt_edit")` is intentionally ignored. No warning logged — the field may show up in legacy LLM output during the transition and is genuinely uninteresting.

- [ ] **Step 5: Update the scripted review payload helpers in tests**

In `tests/unit/test_sleep.py`, find `_empty_review_response`-style helpers (around line 176):

```python
def _review_payload(
    ...
    prompt_edit: str | None = None,
    ...
) -> str:
    return json.dumps(
        {
            ...
            "prompt_edit": prompt_edit,
            ...
        }
    )
```

Rename `prompt_edit` → `appendix_entry` in the helper signature, dict key, and every call site in the file. (Search for `prompt_edit` in `test_sleep.py` and update each occurrence.)

In `tests/unit/test_runtime.py:127`, replace:

```python
    payload = {
        "ltm_candidates": [],
        "prune_keys": [],
        "prompt_edit": None,
        "handler_edits": [],
        "needs_restart": False,
        "reason": "nothing to consolidate",
    }
```

with:

```python
    payload = {
        "ltm_candidates": [],
        "prune_keys": [],
        "appendix_entry": None,
        "handler_edits": [],
        "needs_restart": False,
        "reason": "nothing to consolidate",
    }
```

- [ ] **Step 6: Run parser + unit tests to verify green**

```bash
python -m pytest tests/unit/test_sleep.py -v -k "parse_review"
python -m pytest tests/unit/test_runtime.py -v
```
Expected: parser tests PASS; runtime tests PASS (the review-payload swap shouldn't affect other runtime behaviors).

- [ ] **Step 7: Ruff**

```bash
python -m ruff check region_template/sleep.py tests/unit/test_sleep.py tests/unit/test_runtime.py
```
Expected: no issues.

- [ ] **Step 8: Commit**

```bash
git add region_template/sleep.py tests/unit/test_sleep.py tests/unit/test_runtime.py
git commit -m "$(cat <<'EOF'
refactor(sleep): swap prompt_edit for appendix_entry in review schema

_ReviewOutput.prompt_edit is gone; _ReviewOutput.appendix_entry takes
its place. Parser silently ignores any legacy prompt_edit key (no
persisted sleep output depends on it — PFC's first self-mod cycle was
reverted in the prior session). Updated test payload helpers + the
runtime fake.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: New review templates — system/user split

Replace the single templated review prompt with a system text (`load_system_prompt` output) + a user template focused on the STM/events/schema.

**Files:**
- Create: `region_template/sleep_prompts/default_review_user.md`
- Delete: `region_template/sleep_prompts/default_review.md`

- [ ] **Step 1: Write the new user template**

Create `region_template/sleep_prompts/default_review_user.md`:

```markdown
You are in sleep consolidation.

Here is a summary of your recent wake period:
- stm snapshot: {stm_summary}
- recent events: {recent_events}
- current modulators: {modulator_snapshot}
- current self state: {self_state}

Identify:
1. Events worth storing as episodes in LTM (1-5 candidates).
2. Patterns worth promoting to knowledge/ or procedural/ notes.
3. Any STM slots that should be cleared.
4. One insight from this cycle worth appending to your evolution log (optional). If included, write a single self-contained paragraph — the framework will prepend a timestamp header and append it to your rolling appendix. Your starter prompt is immutable; this appendix is how you evolve.

Return a JSON object matching this schema: {review_schema}
```

- [ ] **Step 2: Delete the old template**

```bash
git rm region_template/sleep_prompts/default_review.md
```

- [ ] **Step 3: Commit**

```bash
git add region_template/sleep_prompts/default_review_user.md
git commit -m "$(cat <<'EOF'
feat(sleep_prompts): split review template into system + user halves

New user-side default_review_user.md focuses on the STM/events
snapshot and the review JSON schema. The system half is now assembled
at call time by region_template.prompt_assembly.load_system_prompt
(starter prompt + rolling appendix). The old merged default_review.md
is removed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Wire system/user split into `_review_events`

Swap `_load_review_prompt` for two helpers: `load_system_prompt(region_root)` (already built in Task 3) for the system half, and `_render_review_user_prompt(snap)` for the user half. Send both as separate `Message`s. Default `cache_strategy="system"` already caches the starter+appendix prefix.

**Files:**
- Modify: `region_template/sleep.py:370-390, 560-585`
- Modify: `tests/unit/test_sleep.py` (any test that asserts on `_load_review_prompt` output)

- [ ] **Step 1: Add a `_render_review_user_prompt` test**

Append to the existing `test_sleep.py` parser/helper block:

```python
@pytest.mark.asyncio
async def test_render_review_user_prompt_has_stm_and_schema(
    tmp_path: Path,
) -> None:
    root = _make_region_root(tmp_path)
    coord = _make_sleep_coordinator(root)
    snap = {
        "slots": {"recent_text": {"value": "hello"}},
        "recent_events": [{"topic": "hive/sensory/input/text"}],
    }
    rendered = coord._render_review_user_prompt(snap)
    assert "hello" in rendered
    assert "hive/sensory/input/text" in rendered
    assert '"appendix_entry": "str or null"' in rendered
    # System-side content must NOT leak into the user prompt.
    assert "# Evolution appendix" not in rendered
```

- [ ] **Step 2: Add a `_review_events` wiring test**

Still in `test_sleep.py`, add a test that captures the `CompletionRequest` passed to the fake LLM and asserts both a system and a user message are present, with the system text containing the starter prompt's opening line:

```python
@pytest.mark.asyncio
async def test_review_events_sends_system_plus_user_messages(
    tmp_path: Path,
) -> None:
    root = _make_region_root(tmp_path)
    (root / "prompt.md").write_text(
        "You are the test region.\nConstitutional content.\n",
        encoding="utf-8",
    )

    captured: list[CompletionRequest] = []

    class _CapturingLlm:
        async def complete(self, req: CompletionRequest) -> CompletionResult:
            captured.append(req)
            return CompletionResult(
                text=json.dumps(
                    {
                        "ltm_candidates": [],
                        "prune_keys": [],
                        "appendix_entry": None,
                        "handler_edits": [],
                        "needs_restart": False,
                        "reason": "nothing",
                    }
                ),
                tool_calls=(),
                finish_reason="stop",
                usage=TokenUsage(0, 0, 0, 0),
                model="fake",
                cached_prefix_tokens=0,
                elapsed_ms=1,
            )

    coord = _make_sleep_coordinator(root, llm=_CapturingLlm())
    await coord._review_events({"slots": {}, "recent_events": []})

    assert len(captured) == 1
    msgs = captured[0].messages
    assert len(msgs) == 2
    assert msgs[0].role == "system"
    assert msgs[1].role == "user"
    assert "You are the test region." in msgs[0].content
    assert "Return a JSON object" in msgs[1].content
```

(Adjust `_make_sleep_coordinator`'s signature to accept an `llm=` kwarg if it doesn't already; keep the existing default.)

- [ ] **Step 3: Run the new tests — expect FAIL**

```bash
python -m pytest tests/unit/test_sleep.py -v -k "render_review_user_prompt or review_events_sends_system_plus_user"
```
Expected: FAIL — `_render_review_user_prompt` doesn't exist; `_review_events` only sends one user message.

- [ ] **Step 4: Add the import + helper method**

In `region_template/sleep.py`, at the top imports block, add:

```python
from region_template.prompt_assembly import load_system_prompt
```

Replace `_load_review_prompt` with `_render_review_user_prompt` (same body, different name + docstring reflecting that it's only the user half):

```python
    def _render_review_user_prompt(self, snap: dict[str, Any]) -> str:
        """Render the user-side review prompt (STM + events + schema).

        The system-side (starter prompt + rolling appendix) is assembled
        by :func:`region_template.prompt_assembly.load_system_prompt` and
        attached to the :class:`CompletionRequest` as a separate
        ``Message(role="system", ...)``.
        """
        template_path = (
            Path(__file__).parent / "sleep_prompts" / "default_review_user.md"
        )
        template = template_path.read_text(encoding="utf-8")
        stm_summary = json.dumps(
            snap.get("slots", {}), ensure_ascii=False
        )[:2000]
        recent = json.dumps(
            snap.get("recent_events", []), ensure_ascii=False
        )[:2000]
        return template.format(
            stm_summary=stm_summary,
            recent_events=recent,
            modulator_snapshot="{}",
            self_state="{}",
            review_schema=_REVIEW_SCHEMA_STR,
        )
```

- [ ] **Step 5: Update `_review_events` to send system + user**

Replace:

```python
    async def _review_events(self, snap: dict[str, Any]) -> _ReviewOutput:
        """Step 2: LLM review of recent events. Returns parsed proposals.

        Reads ``region_template/sleep_prompts/default_review.md`` as the base
        prompt; formats with stm snapshot + recent events (modulator /
        self-state placeholders are empty strings until the runtime fills
        them).
        """
        prompt_text = self._load_review_prompt(snap)
        req = CompletionRequest(
            messages=[Message(role="user", content=prompt_text)],
            purpose="sleep_review",
        )
        result = await self._runtime.llm.complete(req)
        return self._parse_review_output(result.text)
```

with:

```python
    async def _review_events(self, snap: dict[str, Any]) -> _ReviewOutput:
        """Step 2: LLM review of recent events. Returns parsed proposals.

        The system message is assembled by ``load_system_prompt``:
        starter ``prompt.md`` + optional rolling appendix. The user
        message is rendered from ``sleep_prompts/default_review_user.md``
        with the STM snapshot + recent events + schema. Keeping the
        large, stable half in ``role="system"`` enables prompt caching
        (``cache_strategy="system"`` is the default).
        """
        system_text = load_system_prompt(self._runtime.region_root)
        user_text = self._render_review_user_prompt(snap)
        req = CompletionRequest(
            messages=[
                Message(role="system", content=system_text),
                Message(role="user", content=user_text),
            ],
            purpose="sleep_review",
        )
        result = await self._runtime.llm.complete(req)
        return self._parse_review_output(result.text)
```

- [ ] **Step 6: Run the new tests — verify PASS**

```bash
python -m pytest tests/unit/test_sleep.py -v -k "render_review_user_prompt or review_events_sends_system_plus_user"
```
Expected: PASS.

- [ ] **Step 7: Run the full sleep test module to catch regressions from the helper rename**

```bash
python -m pytest tests/unit/test_sleep.py -v
```
Expected: all PASS. If any test still references `_load_review_prompt` by name, rename it inline to `_render_review_user_prompt` and re-run.

- [ ] **Step 8: Ruff**

```bash
python -m ruff check region_template/sleep.py tests/unit/test_sleep.py
```
Expected: no issues.

- [ ] **Step 9: Commit**

```bash
git add region_template/sleep.py tests/unit/test_sleep.py
git commit -m "$(cat <<'EOF'
feat(sleep): inject starter prompt + rolling appendix as system message

_review_events now builds the LLM request from two messages: a system
message assembled by load_system_prompt (prompt.md + rolling.md) and a
user message rendered from default_review_user.md (STM + events +
schema). The stable half lives in role="system", so cache_strategy's
default "system" setting starts paying caching dividends.

Previously the sleep LLM never saw the region's own starter prompt —
this is a real behavior change, not just a rename.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Replace `_apply_prompt_edit` with `_append_appendix`; rename commit-message bool

The sleep pipeline branch that used to persist a new `prompt.md` now calls `AppendixStore.append`. The `prompt_changed` bool in `_format_commit_message` becomes `appendix_appended`.

**Files:**
- Modify: `region_template/sleep.py:210-260, 454-470, 646-710`
- Modify: `tests/unit/test_sleep.py` — replace oversized-prompt recovery test with a `AppendixStore.append` recovery test.

- [ ] **Step 1: Write a failing recovery test**

The existing `tests/unit/test_sleep.py:587` test asserts that when `edit_prompt` raises (oversized), LTM writes already on disk are reverted. We need the equivalent for the appendix path. In `tests/unit/test_sleep.py`, locate the `test_*_oversized_prompt_*` test (around line 587) and **replace** it with:

```python
@pytest.mark.asyncio
async def test_append_appendix_failure_reverts_prior_ltm_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If AppendixStore.append raises after LTM writes have landed, the
    outer try/except in ``SleepCoordinator.run`` must revert the working
    tree so nothing partial escapes (Principle XIV)."""
    root = _make_region_root(tmp_path)
    # Scripted review: one LTM candidate + an appendix entry.
    llm = _make_fake_llm(
        _review_payload(
            ltm_candidates=[
                {
                    "filename": "episode.md",
                    "content": "episode body",
                    "topic": "episode",
                    "importance": 0.5,
                    "tags": [],
                    "reason": "worth remembering",
                }
            ],
            appendix_entry="an appendix insight",
        )
    )
    coord = _make_sleep_coordinator(root, llm=llm)

    async def _boom(self, *a, **kw):
        raise RuntimeError("disk full")

    monkeypatch.setattr(AppendixStore, "append", _boom)

    with pytest.raises(RuntimeError, match="disk full"):
        await coord.run(trigger="explicit_request")

    # LTM episode must have been reverted — no file on disk.
    assert not (root / "memory" / "ltm" / "episode.md").exists()
```

(Adjust helper names to match what already exists in the file. `AppendixStore` is imported from `region_template.appendix`; add the import at the top.)

- [ ] **Step 2: Run the new test — expect FAIL**

```bash
python -m pytest tests/unit/test_sleep.py::test_append_appendix_failure_reverts_prior_ltm_writes -v
```
Expected: FAIL — `_apply_prompt_edit` is still called (no such method `_append_appendix`), review.appendix_entry never reached, test collapses.

- [ ] **Step 3: Replace `_apply_prompt_edit` with `_append_appendix`**

In `region_template/sleep.py`, add the AppendixStore import at the top:

```python
from region_template.appendix import AppendixStore
```

Replace:

```python
    async def _apply_prompt_edit(self, new_text: str, reason: str) -> None:
        """Step 6: persist a revised prompt via SelfModifyTools.

        Spec §A.7.1 requires ``reason`` to be 1..200 chars — any
        non-whitespace string is valid, so a simple ``bool`` fallback
        is sufficient here. Long narrative reasons from the LLM are
        truncated to the 200-char cap with an ellipsis so they don't
        fail the whole sleep cycle.
        """
        effective_reason = (
            _clamp_reason(reason) if reason and reason.strip() else "sleep_revision"
        )
        await self._runtime.tools.edit_prompt(
            new_text=new_text, reason=effective_reason
        )
```

with:

```python
    async def _append_appendix(
        self, entry: str, *, trigger: SleepTrigger
    ) -> None:
        """Step 6: append an evolution-appendix section to rolling.md.

        The LLM emits only the entry body; the framework prepends the
        ISO-timestamped H2 header via
        :class:`region_template.appendix.AppendixStore`. The starter
        ``prompt.md`` is never rewritten — this is the sole prompt-
        evolution surface post-v0 (§A.7.1 divergence, see
        ``docs/HANDOFF.md``).
        """
        store = AppendixStore(self._runtime.region_root)
        await store.append(entry, trigger=trigger)
```

- [ ] **Step 4: Update the call site in `run()`**

Replace:

```python
            if review.prompt_edit:
                await self._apply_prompt_edit(
                    review.prompt_edit, reason=review.reason
                )
                prompt_changed = True
```

with:

```python
            appendix_appended = False
            if review.appendix_entry:
                await self._append_appendix(
                    review.appendix_entry, trigger=trigger
                )
                appendix_appended = True
```

Remove the `prompt_changed = False` initializer earlier in the function; replace every later reference to `prompt_changed` (commit-message call, log fields if any) with `appendix_appended`.

- [ ] **Step 5: Update `_format_commit_message` signature + body**

Rename its `prompt_changed: bool` parameter to `appendix_appended: bool`. Update the message body so the corresponding commit-line reads e.g. `appendix appended` rather than `prompt updated`. Update the caller in `run()`.

Exact search-replace inside `_format_commit_message` (find the current text referencing `prompt_changed` or `prompt updated`):

```python
    def _format_commit_message(
        self,
        *,
        trigger: SleepTrigger,
        events_reviewed: int,
        ltm_writes: int,
        ltm_files: list[str],
        stm_pruned: int,
        prompt_changed: bool,
        handlers_changed: bool,
        restart: bool,
        reason: str,
    ) -> str:
```

becomes:

```python
    def _format_commit_message(
        self,
        *,
        trigger: SleepTrigger,
        events_reviewed: int,
        ltm_writes: int,
        ltm_files: list[str],
        stm_pruned: int,
        appendix_appended: bool,
        handlers_changed: bool,
        restart: bool,
        reason: str,
    ) -> str:
```

and every `prompt_changed` occurrence inside the body becomes `appendix_appended`. Adjust the string literal describing the change (e.g. `"prompt: updated"` → `"appendix: +1 section"`) — grep inside the function to find the exact text.

- [ ] **Step 6: Run the recovery test — verify PASS**

```bash
python -m pytest tests/unit/test_sleep.py::test_append_appendix_failure_reverts_prior_ltm_writes -v
```
Expected: PASS.

- [ ] **Step 7: Run the full sleep module**

```bash
python -m pytest tests/unit/test_sleep.py -v
```
Expected: all PASS. Fix any fallout — likely existing tests that asserted on commit-message text or on `prompt_changed` fields.

- [ ] **Step 8: Ruff**

```bash
python -m ruff check region_template/sleep.py tests/unit/test_sleep.py
```
Expected: no issues.

- [ ] **Step 9: Commit**

```bash
git add region_template/sleep.py tests/unit/test_sleep.py
git commit -m "$(cat <<'EOF'
refactor(sleep): replace _apply_prompt_edit with _append_appendix

Sleep step 6 now appends to the rolling evolution appendix via
AppendixStore.append instead of rewriting prompt.md. prompt.md is no
longer a writable surface for regions — this is the §A.7.1 divergence
documented in docs/HANDOFF.md.

_format_commit_message's prompt_changed flag becomes appendix_appended,
and the oversized-prompt recovery test is replaced with one that
stubs AppendixStore.append to raise and confirms LTM writes are
reverted.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Delete `SelfModifyTools.edit_prompt`

With sleep no longer calling it, there are no production callers. Delete cleanly — no deprecation shim.

**Files:**
- Modify: `region_template/self_modify.py:71-72, 213-235`
- Modify: `tests/unit/test_self_modify.py:10-20, 54, 140-195, 550-600`

- [ ] **Step 1: Delete the `edit_prompt` test block**

In `tests/unit/test_self_modify.py`, delete:
- the `_PROMPT_FIXTURE` constant (line 54).
- the `# edit_prompt` section header and its five tests (`test_edit_prompt_phase_wake_raises`, `test_edit_prompt_missing_capability_raises`, `test_edit_prompt_happy_path`, `test_edit_prompt_empty_reason_rejected`, `test_edit_prompt_too_long_reason_rejected`, `test_edit_prompt_text_too_large_rejected`).
- the leading module docstring bullet referencing `edit_prompt` (line 13).
- any remaining `(root / "prompt.md").write_text("changed\n")` etc. lines inside unrelated tests — those seed prompt.md for git's initial commit and should stay; keep them. Remove only lines that are unreachable once `edit_prompt` is gone (search for the string `edit_prompt` to be sure).

(If `tests/unit/test_self_modify.py` has a fixture for `_PROMPT_FIXTURE` used elsewhere, update those callers to use a local literal.)

- [ ] **Step 2: Delete `edit_prompt` from `SelfModifyTools`**

In `region_template/self_modify.py`, delete lines:
- the `_PROMPT_MAX_BYTES = 64 * 1024` constant (line 72) and its comment.
- the entire `edit_prompt` method block (lines 213–235), including the section comment banner.

- [ ] **Step 3: Run unit tests**

```bash
python -m pytest tests/unit/test_self_modify.py tests/unit/test_sleep.py -v
```
Expected: all PASS. No references to `edit_prompt` or `_PROMPT_MAX_BYTES` should remain — if ruff or pytest flags a reference, grep for it and clean up.

- [ ] **Step 4: Grep to confirm nothing references `edit_prompt` production-side**

```bash
grep -rn "edit_prompt\|_PROMPT_MAX_BYTES\|_PROMPT_FIXTURE" --include="*.py" region_template/ glia/ tools/ shared/ tests/
```
Expected: empty output.

- [ ] **Step 5: Ruff**

```bash
python -m ruff check region_template/self_modify.py tests/unit/test_self_modify.py
```
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add region_template/self_modify.py tests/unit/test_self_modify.py
git commit -m "$(cat <<'EOF'
feat(self_modify)!: remove edit_prompt tool — prompt.md is now immutable DNA

Regions no longer have a self-mod surface for prompt.md. Evolution
happens via the append-only rolling appendix
(region_template.appendix.AppendixStore). Sleep stopped calling
edit_prompt in the prior task, so this deletion has no production
callers to break.

Divergence from spec §A.7.1 is documented in docs/HANDOFF.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Integration test — two consecutive sleeps grow rolling.md

End-to-end: two `SleepCoordinator.run()` calls with scripted LLM responses, each emitting a distinct `appendix_entry`. Assert rolling.md contains two dated H2 sections in order and that `prompt.md` is byte-identical to its git-HEAD state.

**Files:**
- Create: `tests/integration/test_sleep_appendix_growth.py`

- [ ] **Step 1: Write the integration test**

Create `tests/integration/test_sleep_appendix_growth.py`:

```python
"""Integration: two consecutive sleep cycles grow rolling.md chronologically
while prompt.md stays byte-identical."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from region_template.appendix import AppendixStore
from region_template.sleep import SleepCoordinator


@pytest.mark.asyncio
async def test_two_sleeps_produce_two_appendix_sections(
    tmp_path: Path,
) -> None:
    # --- Build a region with a real prompt.md + scripted LLM. ---
    from tests.integration._helpers import (  # reuse the integration test harness
        build_region_runtime,
        scripted_review_payload,
    )

    region_root = tmp_path / "regions" / "pfc_test"
    runtime = await build_region_runtime(
        region_root,
        starter_prompt="You are pfc_test.\nConstitutional DNA.\n",
        scripted_reviews=[
            scripted_review_payload(
                appendix_entry="first cycle insight",
                reason="cycle one",
            ),
            scripted_review_payload(
                appendix_entry="second cycle insight",
                reason="cycle two",
            ),
        ],
    )
    coord = SleepCoordinator(runtime)

    prompt_before = (region_root / "prompt.md").read_bytes()
    prompt_hash_before = hashlib.sha256(prompt_before).hexdigest()

    await coord.run(trigger="explicit_request")
    await coord.run(trigger="explicit_request")

    # prompt.md byte-identical.
    prompt_after = (region_root / "prompt.md").read_bytes()
    assert hashlib.sha256(prompt_after).hexdigest() == prompt_hash_before

    # rolling.md has two dated H2 sections in order.
    rolling = (region_root / "memory" / "appendices" / "rolling.md").read_text(
        encoding="utf-8"
    )
    first_idx = rolling.index("first cycle insight")
    second_idx = rolling.index("second cycle insight")
    assert first_idx < second_idx
    assert rolling.count("## ") == 2
```

If `tests/integration/_helpers.py` doesn't yet expose `build_region_runtime` / `scripted_review_payload`, add the test alongside whatever harness the existing integration tests already use (check `tests/integration/conftest.py`). The point is: exercise real `SleepCoordinator.run()` twice against a real `AppendixStore` backed by real disk, with scripted LLM responses.

- [ ] **Step 2: Run the integration test**

```bash
python -m pytest tests/integration/test_sleep_appendix_growth.py -v
```
Expected: PASS. If the helper harness needs light extension, extend it (keep changes minimal and consistent with the style of the other integration tests — check `tests/integration/` for precedent).

- [ ] **Step 3: Ruff**

```bash
python -m ruff check tests/integration/test_sleep_appendix_growth.py
```

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_sleep_appendix_growth.py
git commit -m "$(cat <<'EOF'
test(integration): two sleep cycles grow rolling.md, prompt.md stays byte-identical

End-to-end assertion that the append-only evolution surface works
across consecutive cycles: two dated H2 sections in rolling.md in the
right order, prompt.md sha256 unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: Update `docs/HANDOFF.md`

Record the design decision under Phase 11, call out the §A.7.1 divergence explicitly, and note the new files future sessions need to know about.

**Files:**
- Modify: `docs/HANDOFF.md` (header + Phase 11 section)

- [ ] **Step 1: Bump `Last updated` and update `Current phase`**

Replace the existing line:

```
**Last updated:** 2026-04-21 (v0 COMPLETE — all 10 phases ✅; Phase 11 runtime evolution next)
```

with (use today's actual date if writing later):

```
**Last updated:** 2026-04-21 (Phase 11 — append-only prompt evolution landed; prompt.md now immutable DNA)
```

- [ ] **Step 2: Append a Phase 11 subsection**

Immediately after the `## Phase 11 — Runtime evolution` section's final paragraph (look for the `### What this means for the repo` block), append:

```markdown
### 2026-04-21 — Append-only prompt evolution (§A.7.1 divergence)

**Decision.** Regions no longer self-modify ``prompt.md``. The starter
prompt is now truly immutable constitutional DNA, written once at
region birth by ``glia/spawn_executor.py`` and never overwritten.
Evolution happens via a per-region append-only appendix at
``regions/<name>/memory/appendices/rolling.md`` managed by
``region_template.appendix.AppendixStore``.

**Why.** The first real PFC self-mod cycle in the prior observation
session replaced the 200-line constitutional starter prompt with a
4-item TODO list — the pipeline worked, but the LLM's judgment on
rewriting its own DNA was self-destructive. Rather than add fragile
guardrails around prompt rewrites, we remove the footgun entirely.

**Mechanism.**
- ``region_template.appendix.AppendixStore`` — single writer of
  ``rolling.md``. Lazy-creates on first append. Dated H2 headers
  (``## <ISO-timestamp> — <trigger>``). Atomic read-modify-write.
- ``region_template.prompt_assembly.load_system_prompt`` — joins
  starter prompt + explicit ``# Evolution appendix`` delimiter +
  rolling appendix. Called at every LLM call that builds a system
  prompt (today: sleep review; future: handler-driven LLM calls).
- Sleep review schema: ``prompt_edit`` is gone, replaced by
  ``appendix_entry``. LLM emits only the new section body; framework
  prepends the timestamp header.
- ``SelfModifyTools.edit_prompt`` is **deleted**. No deprecation shim —
  zero production callers remain after the sleep wiring swap.

**Spec divergence from §A.7.1.** The spec lists ``edit_prompt`` as one
of the self-modification tools. It no longer exists. ``prompt.md`` is
not a writable surface for regions at all. Any future spec revision
should reframe §A.7.1 around the rolling appendix.

**What to check on resume.**
- ``regions/<name>/memory/appendices/rolling.md`` — grows over time.
- ``regions/<name>/prompt.md`` — should be byte-identical to its
  git-HEAD state across every sleep cycle. A non-zero diff here is a
  regression.
- Every ``SleepCoordinator.run()`` that appends commits the new
  rolling.md section through the region's per-region git.

**Follow-ups (explicitly deferred).**
- Consolidation pass: summarize older appendix sections into a gist
  so rolling.md doesn't grow unbounded over months. Out of scope for
  this session; revisit once we have real multi-week appendix data.
- Token-budget check on the assembled system prompt. No hard cap
  today (biology as tiebreaker, Principle I). Anthropic prompt
  caching on the stable system half is the first-line mitigation.
```

- [ ] **Step 3: Run the full test suite as the final gate**

```bash
python -m pytest tests/unit/ -q
python -m pytest tests/integration/ -q
python -m ruff check region_template/ glia/ tools/ tests/ shared/
```
Expected:
- unit: 707+ passed (the three new appendix/prompt-assembly suites added tests; the three `edit_prompt` tests were deleted). Count net-delta; if you drop a few more than you add, confirm the deletions were intentional.
- integration: prior baseline + 1 new test (`test_sleep_appendix_growth`).
- ruff: clean.

- [ ] **Step 4: Commit HANDOFF update**

```bash
git add docs/HANDOFF.md
git commit -m "$(cat <<'EOF'
docs(HANDOFF): record append-only prompt evolution + §A.7.1 divergence

Phase 11 subsection explains why prompt.md is now immutable DNA, what
AppendixStore / load_system_prompt / appendix_entry replace, and what
future sessions should verify on resume (rolling.md growth, prompt.md
byte-parity with git HEAD). Deferred follow-ups (consolidation,
system-prompt token cap) called out explicitly.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-review (run after plan is drafted)

**Spec coverage — did every decision get a task?**
- [x] Single rolling file per region (`memory/appendices/rolling.md`) — Task 1.
- [x] Mechanism shared DNA (region_template/) — Tasks 1, 3.
- [x] Dated H2 headers, chronological, append-only — Task 1, 2.
- [x] Sleep schema drops `prompt_edit`, adds `appendix_entry` — Task 4.
- [x] Framework (not LLM) prepends timestamp header — Task 1 + Task 7.
- [x] Context assembly: `prompt.md` + `rolling.md` concatenated at every system-prompt call — Task 3 (helper) + Task 6 (wired into sleep).
- [x] No artificial size limits — covered implicitly (no size check added).
- [x] `edit_prompt` tool goes away — Task 8.
- [x] §A.7.1 divergence documented — Task 10.
- [x] Lazy-create `rolling.md` on first append — Task 1.
- [x] Explicit delimiter between starter and rolling — Task 3.
- [x] System/user split in the review call — Tasks 5, 6.
- [x] Integration coverage: two consecutive sleeps → two dated sections — Task 9.

**Placeholders scan.** No `TBD`, no "add validation", no "fill in details", no "similar to Task N". Every step has exact code or exact commands.

**Type consistency.**
- `AppendixStore.append(entry, *, when=None, trigger="sleep")` — signature used in Task 1 test, Task 1 impl, Task 7 call site, Task 9 test. Consistent.
- `load_system_prompt(region_root: Path) -> str` — Task 3 impl, Task 6 call site. Consistent.
- `_ReviewOutput.appendix_entry: str | None` — Task 4. Referenced in Task 6 test + Task 7 impl. Consistent.
- `_format_commit_message(..., appendix_appended: bool, ...)` — Task 7. Single definition site.
- `_render_review_user_prompt(snap)` — Task 6 test, Task 6 impl.
- `_append_appendix(self, entry: str, *, trigger: SleepTrigger)` — Task 7 impl, Task 7 `run()` call site.

**Sequencing sanity.** Tasks 1–3 introduce new modules with no dependencies on sleep. Task 4 changes the parser + dataclass. Task 5 writes new templates. Task 6 wires system/user into `_review_events` and uses Task 3's `load_system_prompt` plus Task 4's `appendix_entry`. Task 7 replaces the sleep branch that used to call `edit_prompt`; it depends on Tasks 1 (AppendixStore) and 4 (schema). Task 8 deletes `edit_prompt` — safe only after Task 7 removes the last caller. Task 9 is integration, depends on all prior tasks. Task 10 is docs.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-21-append-only-prompt-evolution.md`.

Two execution options:

1. **Subagent-Driven (recommended per CLAUDE.md's execution model — fresh implementer per task + two-stage review).**
2. **Inline execution via superpowers:executing-plans — batch execution with checkpoints.**
