"""Tests for :mod:`region_template.sleep` — spec §D.5.

Exercises :class:`SleepCoordinator` with a stub runtime, a
:class:`FakeLlmAdapter`, and real :class:`MemoryStore` / :class:`GitTools`
/ :class:`SelfModifyTools` on a tmp_path region.

The 9-step pipeline is covered via:

  - happy-path ``no_change`` (empty review JSON)
  - happy-path ``committed_in_place`` (LTM writes only)
  - happy-path ``committed_restart`` (handler edits + ``needs_restart``)
  - LLM failure during review → :class:`LlmError`, git clean
  - handler gate failure (ast.parse rejects) → ``no_change``, git clean
  - ``abort()`` reverts staged edits and never raises
  - commit message format matches §D.5.6 template
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from region_template.errors import ConfigError, LlmError
from region_template.git_tools import GitTools
from region_template.llm_adapter import (
    CompletionRequest,
    CompletionResult,
)
from region_template.memory import MemoryStore
from region_template.self_modify import SelfModifyTools
from region_template.sleep import (
    _REVIEW_SCHEMA_STR,
    SleepCoordinator,
    SleepResult,
    _clamp_reason,
)
from region_template.token_ledger import TokenUsage
from region_template.types import LifecyclePhase
from tests.fakes.llm import FakeLlmAdapter

_SHA_LEN = 40


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeRuntime:
    """Stub runtime exposing what SleepCoordinator + SelfModifyTools need."""

    region_name: str
    region_root: Path
    memory: MemoryStore
    llm: Any
    tools: SelfModifyTools
    git: GitTools
    phase: LifecyclePhase = LifecyclePhase.SLEEP


def _completion(text: str) -> CompletionResult:
    return CompletionResult(
        text=text,
        tool_calls=(),
        finish_reason="stop",
        usage=TokenUsage(0, 0, 0, 0),
        model="fake",
        cached_prefix_tokens=0,
        elapsed_ms=1,
    )


def _build_region(tmp_path: Path, region_name: str = "test_region") -> Path:
    """Create a region directory + prompt.md seed (for git's initial commit)."""
    root = tmp_path / "regions" / region_name
    root.mkdir(parents=True)
    (root / "prompt.md").write_text("seed\n", encoding="utf-8")
    return root


def _build_coordinator(
    tmp_path: Path,
    *,
    scripted_llm_responses: list[CompletionResult] | None = None,
    region_name: str = "test_region",
) -> tuple[SleepCoordinator, _FakeRuntime]:
    """Wire up a SleepCoordinator with real memory/git/self_modify.

    Construction order matters: MemoryStore creates ``memory/stm.json`` +
    ``ltm/`` subdirs on ``__init__``. We build it BEFORE GitTools so those
    paths are staged in the initial bootstrap commit — otherwise the tree
    is "dirty" from untracked ``memory/`` artefacts the moment a test
    starts. Same applies after ``build_index()`` writes ``index.json``.
    """
    root = _build_region(tmp_path, region_name=region_name)

    # A deferred-phase runtime proxy — SelfModifyTools stores a reference
    # and consults ``.phase`` on each tool call, but we need to construct
    # tools BEFORE the real runtime (which references tools) exists.
    runtime_holder: dict[str, Any] = {}

    class _RuntimeProxy:
        @property
        def phase(self) -> LifecyclePhase:
            return runtime_holder["runtime"].phase

    proxy = _RuntimeProxy()

    # 1. Build MemoryStore FIRST. Its __init__ creates memory/stm.json (empty
    #    slots) and the ltm/ subdirs. Persist an initial empty stm so those
    #    files exist on disk before git's initial commit includes them.
    memory = MemoryStore(
        root=root / "memory",
        region_name=region_name,
        runtime=proxy,
    )

    # 2. Seed initial stm.json + index.json on disk so they're part of the
    #    bootstrap commit. Both are simple JSON blobs; writing them by hand
    #    avoids the async-inside-sync-helper dance. The pipeline's build_index
    #    call rewrites index.json with a fresh timestamp on each sleep, but
    #    SleepCoordinator reverts when there's no substantive change, so the
    #    spurious dirty state doesn't leak across test assertions.
    (root / "memory" / "stm.json").write_text(
        '{"schema_version":1,"region":"'
        + region_name
        + '","updated_at":"seed","slots":{},"recent_events":[]}\n',
        encoding="utf-8",
    )
    (root / "memory" / "index.json").write_text(
        '{"schema_version":1,"built_at":"seed","documents":{},"postings":{}}\n',
        encoding="utf-8",
    )

    # 3. NOW init git — the initial commit picks up prompt.md + memory/.
    git = GitTools(root, region_name=region_name)
    bootstrap_sha = git.current_head_sha()

    tools = SelfModifyTools(
        region_name=region_name,
        region_root=root,
        capabilities={"self_modify": True, "can_spawn": False},
        runtime=proxy,
        git_tools=git,
        memory=memory,
        bootstrap_sha=bootstrap_sha,
    )
    llm = FakeLlmAdapter(scripted_responses=scripted_llm_responses or [])
    runtime = _FakeRuntime(
        region_name=region_name,
        region_root=root,
        memory=memory,
        llm=llm,
        tools=tools,
        git=git,
        phase=LifecyclePhase.SLEEP,
    )
    runtime_holder["runtime"] = runtime

    # Sanity: tree must be clean before the sleep starts.
    assert git.status_clean()

    coord = SleepCoordinator(runtime)
    return coord, runtime


def _review_json(
    *,
    ltm_candidates: list[dict] | None = None,
    prune_keys: list[str] | None = None,
    appendix_entry: str | None = None,
    handler_edits: list[dict] | None = None,
    needs_restart: bool = False,
    reason: str = "",
) -> str:
    payload = {
        "ltm_candidates": ltm_candidates or [],
        "prune_keys": prune_keys or [],
        "appendix_entry": appendix_entry,
        "handler_edits": handler_edits or [],
        "needs_restart": needs_restart,
        "reason": reason,
    }
    return json.dumps(payload)


# ---------------------------------------------------------------------------
# 1. Happy path: no_change
# ---------------------------------------------------------------------------


async def test_run_no_change_empty_review(tmp_path: Path) -> None:
    """LLM returns an empty review → no writes, no commit, status=no_change."""
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[_completion(_review_json())],
    )
    head_before = runtime.git.current_head_sha()

    result = await coord.run(trigger="quiet_window")

    assert isinstance(result, SleepResult)
    assert result.status == "no_change"
    assert result.restart is False
    assert result.sha is None
    # Git tree unchanged.
    assert runtime.git.status_clean()
    assert runtime.git.current_head_sha() == head_before


# ---------------------------------------------------------------------------
# 2. Happy path: committed_in_place (LTM writes only)
# ---------------------------------------------------------------------------


async def test_run_commits_ltm_writes(tmp_path: Path) -> None:
    """LLM returns 1 ltm_candidate → coordinator writes LTM + commits."""
    ltm = {
        "filename": "episodes/first_day.md",
        "content": "I woke up and learned how to blink.",
        "topic": "episode",
        "importance": 0.7,
        "tags": ["first", "milestone"],
        "reason": "first-day recap",
    }
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[
            _completion(_review_json(ltm_candidates=[ltm], reason="first day"))
        ],
    )
    head_before = runtime.git.current_head_sha()

    result = await coord.run(trigger="quiet_window")

    assert result.status == "committed_in_place"
    assert result.restart is False
    assert result.sha is not None
    assert len(result.sha) == _SHA_LEN
    # A new commit landed.
    assert runtime.git.current_head_sha() != head_before
    # The LTM file now exists.
    assert (
        runtime.region_root
        / "memory"
        / "ltm"
        / "episodes"
        / "first_day.md"
    ).exists()
    assert runtime.git.status_clean()


# ---------------------------------------------------------------------------
# 3. Happy path: committed_restart (handler edits + needs_restart)
# ---------------------------------------------------------------------------


async def test_run_handler_edits_triggers_restart(tmp_path: Path) -> None:
    """Handler edits + needs_restart=True → committed_restart + restart=True."""
    handler_edit = {
        "path": "on_audio.py",
        "content": "def on_audio(event, ctx):\n    return None\n",
        "delete": False,
    }
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[
            _completion(
                _review_json(
                    handler_edits=[handler_edit],
                    needs_restart=True,
                    reason="new audio handler",
                )
            )
        ],
    )
    result = await coord.run(trigger="heartbeat_cycle")

    assert result.status == "committed_restart"
    assert result.restart is True
    assert result.sha is not None
    assert (
        runtime.region_root / "handlers" / "on_audio.py"
    ).read_text(encoding="utf-8").startswith("def on_audio")
    assert runtime.git.status_clean()


# ---------------------------------------------------------------------------
# 4. LLM failure during review → LlmError, git clean
# ---------------------------------------------------------------------------


async def test_run_llm_review_failure_reverts_and_raises(tmp_path: Path) -> None:
    """FakeLlmAdapter with empty scripted_responses → RuntimeError bubbles up.

    Then we override with an LLM that explicitly raises LlmError, verify git
    tree stays clean.
    """

    class _FailingLlm:
        async def complete(self, req: CompletionRequest) -> CompletionResult:
            raise LlmError("bad_request", retryable=False)

    coord, runtime = _build_coordinator(tmp_path)
    runtime.llm = _FailingLlm()  # swap in the failing adapter

    head_before = runtime.git.current_head_sha()
    with pytest.raises(LlmError):
        await coord.run()

    # Git still clean — no partial writes.
    assert runtime.git.status_clean()
    assert runtime.git.current_head_sha() == head_before


# ---------------------------------------------------------------------------
# 5. Handler gate fails (bad syntax) → no_change, tree reverted
# ---------------------------------------------------------------------------


async def test_run_handler_syntax_error_returns_no_change(tmp_path: Path) -> None:
    """Bad handler syntax → edit_handlers returns ok=False; coordinator reverts."""
    handler_edit = {
        "path": "on_broken.py",
        "content": "def broken(:\n",  # deliberate syntax error
        "delete": False,
    }
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[
            _completion(
                _review_json(
                    handler_edits=[handler_edit],
                    reason="bad syntax handler",
                )
            )
        ],
    )
    head_before = runtime.git.current_head_sha()
    result = await coord.run()

    assert result.status == "no_change"
    assert result.restart is False
    assert result.sha is None
    # The bad file must NOT be on disk.
    assert not (runtime.region_root / "handlers" / "on_broken.py").exists()
    # Git tree clean, no new commits.
    assert runtime.git.status_clean()
    assert runtime.git.current_head_sha() == head_before


# ---------------------------------------------------------------------------
# 6. abort() rolls back uncommitted changes, never raises
# ---------------------------------------------------------------------------


async def test_abort_reverts_staged_changes_and_does_not_raise(
    tmp_path: Path,
) -> None:
    """abort() must drop uncommitted edits and return without raising."""
    coord, runtime = _build_coordinator(tmp_path)
    head_before = runtime.git.current_head_sha()

    # Simulate a mid-sleep edit: write a file directly so the working tree
    # is now dirty (mimics a partial write before abort fires).
    dirty = runtime.region_root / "handlers" / "partial.py"
    dirty.parent.mkdir(parents=True, exist_ok=True)
    dirty.write_text("x = 1\n", encoding="utf-8")
    assert not runtime.git.status_clean()

    # Abort should NOT raise, and should reset the tree.
    await coord.abort("nightmare_cortisol_spike")

    assert runtime.git.status_clean()
    assert runtime.git.current_head_sha() == head_before
    # The partial file is gone (git reset --hard removes tracked+untracked).
    assert not dirty.exists()


async def test_abort_tolerates_clean_tree(tmp_path: Path) -> None:
    """abort() on an already-clean tree is a no-op and does not raise."""
    coord, runtime = _build_coordinator(tmp_path)
    assert runtime.git.status_clean()
    # Just verify no exception.
    await coord.abort("cautious_abort")
    assert runtime.git.status_clean()


# ---------------------------------------------------------------------------
# 7. Commit message format matches §D.5.6 template
# ---------------------------------------------------------------------------


async def test_commit_message_format_matches_spec(tmp_path: Path) -> None:
    """After a committed_in_place run, read back the commit message and
    assert every §D.5.6 line appears in order."""
    ltm = {
        "filename": "episodes/recap.md",
        "content": "Recap.",
        "topic": "episode",
        "importance": 0.5,
        "tags": [],
        "reason": "recap",
    }
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[
            _completion(
                _review_json(
                    ltm_candidates=[ltm],
                    reason="why it matters",
                )
            )
        ],
    )

    result = await coord.run(trigger="quiet_window")
    assert result.status == "committed_in_place"
    assert result.sha is not None

    # Pull the commit message off the SHA via the region's git directory.
    log_result = subprocess.run(
        ["git", "log", "-1", "--pretty=%B", result.sha],
        cwd=runtime.region_root,
        capture_output=True,
        text=True,
        check=True,
    )
    message = log_result.stdout
    assert message.startswith("sleep: quiet_window @ ")
    assert "events reviewed: 0" in message
    assert "ltm writes: 1" in message
    # Filename should appear in the file list.
    assert "episodes/recap.md" in message
    assert "stm pruned: 0 slots" in message
    assert "prompt: unchanged" in message
    assert "handlers: unchanged" in message
    assert "restart required: no" in message
    assert "reason: why it matters" in message


# ---------------------------------------------------------------------------
# 8. JSON parsing robustness — code fences
# ---------------------------------------------------------------------------


async def test_run_handles_json_in_code_fence(tmp_path: Path) -> None:
    """LLMs often wrap JSON in ```json ... ``` fences — strip before parsing."""
    body = _review_json()
    fenced = f"Here is the review:\n```json\n{body}\n```\n"
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[_completion(fenced)],
    )
    result = await coord.run()
    assert result.status == "no_change"
    assert runtime.git.status_clean()


# ---------------------------------------------------------------------------
# 9. LLM returns non-JSON → LlmError (review_json_decode_error)
# ---------------------------------------------------------------------------


async def test_run_llm_non_json_raises_llm_error(tmp_path: Path) -> None:
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[_completion("not json at all")],
    )
    head_before = runtime.git.current_head_sha()
    with pytest.raises(LlmError):
        await coord.run()
    assert runtime.git.status_clean()
    assert runtime.git.current_head_sha() == head_before


# ---------------------------------------------------------------------------
# 10. STM prune path — review requests prune; slots are removed & committed
# ---------------------------------------------------------------------------


async def test_run_prunes_stm_slots(tmp_path: Path) -> None:
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[
            _completion(
                _review_json(
                    prune_keys=["temp_goal"],
                    reason="clear transient goal",
                )
            )
        ],
    )
    # Pre-seed an STM slot the review will ask us to prune.
    await runtime.memory.write_stm("temp_goal", {"x": 1})
    slot = await runtime.memory.read_stm("temp_goal")
    assert slot is not None

    result = await coord.run(trigger="stm_pressure")
    assert result.status == "committed_in_place"
    assert result.stm_pruned == 1
    # Slot is gone.
    assert await runtime.memory.read_stm("temp_goal") is None


# ---------------------------------------------------------------------------
# 11. Short LLM reason uses fallback (regression)
# ---------------------------------------------------------------------------


async def test_short_llm_reason_uses_fallback(tmp_path: Path) -> None:
    """A handler edit with a too-short LLM reason must use the fallback.

    Spec §A.7.3 requires handler-edit ``reason`` to be >= 10 chars
    (see ``self_modify._HANDLER_REASON_MIN``). If the LLM returns
    something truthy but under that threshold (e.g. ``"ok"``), the old
    ``reason or fallback`` short-circuit kept the two-char string,
    ``edit_handlers`` rejected it with ``ConfigError("reason too short")``,
    the coordinator caught it as a gate failure, and the pipeline silently
    returned ``no_change`` — dropping the legitimate handler edit.

    With the length-aware fallback, the short LLM reason is replaced by
    ``"sleep_handler_revision"`` (>= 10 chars), ``edit_handlers`` accepts
    it, the edit lands, and the cycle commits as usual.
    """
    handler_edit = {
        "path": "on_audio.py",
        "content": "def on_audio(event, ctx):\n    return None\n",
        "delete": False,
    }
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[
            _completion(
                _review_json(
                    handler_edits=[handler_edit],
                    needs_restart=True,
                    reason="ok",  # 2 chars — below _HANDLER_REASON_MIN=10
                )
            )
        ],
    )
    result = await coord.run(trigger="heartbeat_cycle")

    # Pipeline must NOT silently degrade to no_change — the handler edit
    # should land and the cycle should request a restart.
    assert result.status == "committed_restart"
    assert result.restart is True
    assert result.sha is not None
    assert (
        runtime.region_root / "handlers" / "on_audio.py"
    ).read_text(encoding="utf-8").startswith("def on_audio")
    assert runtime.git.status_clean()

    # The sleep commit message (§D.5.6) carries the LLM's review reason
    # verbatim in the "reason:" line — that's distinct from the
    # self_modify reason we substituted. The presence of a commit at all
    # (status=committed_restart above) is the definitive signal that the
    # fallback fired on the self_modify path; without it, edit_handlers
    # would have raised and the coordinator would have reverted.
    log_result = subprocess.run(
        ["git", "log", "-1", "--pretty=%B", result.sha],
        cwd=runtime.region_root,
        capture_output=True,
        text=True,
        check=True,
    )
    message = log_result.stdout
    assert message.startswith("sleep: heartbeat_cycle @ ")
    assert "handlers: changed" in message
    assert "reason: ok" in message  # review reason, unchanged


# ---------------------------------------------------------------------------
# 12. Finding 1 — late-pipeline exception reverts (dirty tree)
# ---------------------------------------------------------------------------


async def test_late_pipeline_exception_reverts_working_tree(
    tmp_path: Path,
) -> None:
    """An oversized prompt-rewrite payload raises ``ConfigError`` from inside
    ``edit_prompt`` — AFTER LTM writes have landed on disk. The outer
    try/except must still revert the working tree so no partial state
    leaks across the sleep boundary.

    Regression: previously steps 6-8 ran OUTSIDE the try/except, so a
    raise here left LTM files staged with no commit — a dirty tree.

    Note: for Task 4 the field was renamed ``prompt_edit`` →
    ``appendix_entry`` but the review-branch still invokes
    ``_apply_prompt_edit`` with the value as-is; Task 7 replaces that
    call with ``AppendixStore.append`` and this test is then re-framed
    as an append-failure recovery test.
    """
    # 200 KB of ASCII — blows past _PROMPT_MAX_BYTES=64*1024.
    oversized_prompt = "x" * 200_000
    ltm = {
        "filename": "episodes/will_be_reverted.md",
        "content": "Written to disk but never committed.",
        "topic": "episode",
        "importance": 0.5,
        "tags": [],
        "reason": "late-raise regression",
    }
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[
            _completion(
                _review_json(
                    ltm_candidates=[ltm],
                    appendix_entry=oversized_prompt,
                    reason="oversize",
                )
            )
        ],
    )
    head_before = runtime.git.current_head_sha()

    # ConfigError comes from edit_prompt._validate_utf8_size.
    with pytest.raises(ConfigError):
        await coord.run()

    # Revert must have happened even though the raise came AFTER ltm writes.
    assert runtime.git.status_clean()
    assert runtime.git.current_head_sha() == head_before
    # The LTM file must not survive the revert.
    assert not (
        runtime.region_root
        / "memory"
        / "ltm"
        / "episodes"
        / "will_be_reverted.md"
    ).exists()


# ---------------------------------------------------------------------------
# 13. Finding 2 — _REVIEW_SCHEMA_STR is not double-braced
# ---------------------------------------------------------------------------


def test_review_schema_is_un_doubled_json() -> None:
    """The schema constant is a VALUE passed to ``template.format(...)``,
    not itself a format string — so its braces must be SINGLE. Doubled
    braces would be shown to the LLM verbatim as ``{{...}}``, producing
    malformed JSON the model has to reverse-engineer.
    """
    # Negative assertions — no double braces anywhere.
    assert "{{" not in _REVIEW_SCHEMA_STR
    assert "}}" not in _REVIEW_SCHEMA_STR
    # Positive: should parse as JSON (proves braces are balanced single-braces).
    json.loads(_REVIEW_SCHEMA_STR)


# ---------------------------------------------------------------------------
# 14. Finding 3 — compileall leaves no __pycache__ behind
# ---------------------------------------------------------------------------


async def test_compileall_does_not_leave_pycache(tmp_path: Path) -> None:
    """Handler edits trigger a compileall pass. With
    ``PYTHONDONTWRITEBYTECODE=1`` set on the subprocess and
    ``__pycache__/`` in the region's ``.gitignore``, a sleep commit that
    includes handler edits must NOT leave a pycache dir behind, and must
    NOT stage any ``.pyc`` files in the commit.
    """
    handler_edit = {
        "path": "on_audio.py",
        "content": "def on_audio(event, ctx):\n    return None\n",
        "delete": False,
    }
    coord, runtime = _build_coordinator(
        tmp_path,
        scripted_llm_responses=[
            _completion(
                _review_json(
                    handler_edits=[handler_edit],
                    reason="compileall bytecode test",
                )
            )
        ],
    )
    result = await coord.run(trigger="heartbeat_cycle")
    assert result.status == "committed_in_place"
    assert result.sha is not None

    # No pycache dir left on disk.
    assert not (
        runtime.region_root / "handlers" / "__pycache__"
    ).exists()

    # No .pyc files staged in the commit.
    show_result = subprocess.run(
        ["git", "show", "--name-only", "--pretty=", result.sha],
        cwd=runtime.region_root,
        capture_output=True,
        text=True,
        check=True,
    )
    committed_paths = show_result.stdout.splitlines()
    assert not any(p.endswith(".pyc") for p in committed_paths), committed_paths


# ---------------------------------------------------------------------------
# _parse_review_output — appendix_entry replaces the legacy prompt_edit field.
# ---------------------------------------------------------------------------


def test_parse_review_accepts_appendix_entry(tmp_path: Path) -> None:
    """New-shape review output: ``appendix_entry`` is surfaced on ``_ReviewOutput``."""
    coord, _ = _build_coordinator(tmp_path)
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


def test_parse_review_silently_ignores_legacy_prompt_edit(
    tmp_path: Path,
) -> None:
    """Legacy-shape review output: ``prompt_edit`` key is dropped without a warning.

    The field was renamed mid-rollout; an LLM might still emit the old
    shape for a cycle or two. No persisted sleep output depends on it, so
    silent-ignore is safe.
    """
    coord, _ = _build_coordinator(tmp_path)
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


# ---------------------------------------------------------------------------
# _clamp_reason — shrink long LLM narrative reasons to the §A.7.1 cap.
# ---------------------------------------------------------------------------


def test_clamp_reason_passthrough_when_short() -> None:
    assert _clamp_reason("short reason") == "short reason"


def test_clamp_reason_strips_whitespace() -> None:
    assert _clamp_reason("  padded  ") == "padded"


def test_clamp_reason_truncates_with_ellipsis() -> None:
    long = "x" * 500
    out = _clamp_reason(long)
    _EXPECTED_LEN = 200
    assert len(out) == _EXPECTED_LEN
    assert out.endswith("...")
    assert out[:-3] == "x" * (_EXPECTED_LEN - 3)


def test_clamp_reason_custom_max() -> None:
    out = _clamp_reason("abcdefghij", max_len=5)
    _CUSTOM_MAX = 5
    assert len(out) == _CUSTOM_MAX
    assert out == "ab..."
