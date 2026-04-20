"""Tests for region_template.self_modify — spec §A.7.

Exercises :class:`SelfModifyTools` with a stub runtime and a real per-region
git repo under ``tmp_path``. Each tool is tested for:

  (a) Sandbox escape → :class:`SandboxEscape` (if it takes a path).
  (b) Wrong phase → :class:`PhaseViolation`.
  (c) Missing capability → :class:`CapabilityDenied`.
  (d) Happy path.

Per-tool specifics (per spec §A.7):

  - ``edit_prompt``     — writes ``prompt.md`` atomically; reason length
                           bounded; UTF-8 budget enforced.
  - ``edit_subscriptions`` — YAML dump; invalid topic rejected.
  - ``edit_handlers``  — writes + deletes; syntax error in any resulting
                          file rolls back and returns ``ok=False``.
  - ``write_stm``       — callable in WAKE (no ``@sleep_only``); delegates
                          to :class:`MemoryStore`.
  - ``write_ltm``       — sleep-only; delegates to :class:`MemoryStore`.
  - ``commit_changes``  — delegates to :class:`GitTools`.
  - ``request_restart`` — precondition checks (clean tree + sha
                           differs from bootstrap sha).
  - ``spawn_new_region`` — privileged; non-ACC raises ``CapabilityDenied``;
                            ACC path awaits runtime future; 30s timeout.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from region_template import self_modify as sm_module
from region_template.errors import (
    CapabilityDenied,
    ConfigError,
    PhaseViolation,
    SandboxEscape,
)
from region_template.git_tools import CommitResult, GitTools
from region_template.memory import LtmMetadata, LtmWriteResult, MemoryStore
from region_template.self_modify import (
    HandlerWrite,
    SelfModifyTools,
    SpawnProposal,
    SpawnResult,
    SubscriptionEntry,
)
from region_template.types import CapabilityProfile, LifecyclePhase

_SHA_LEN = 40
_PRE_CHECK_VALUE = 42
_PROMPT_FIXTURE = "hello world\nsecond line\n"
_DEFAULT_IMPORTANCE = 0.5
_CUSTOM_IMPORTANCE = 0.9


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeRuntime:
    """Stub runtime — exposes ``.phase`` and publish/shutdown hooks."""

    def __init__(self, phase: LifecyclePhase = LifecyclePhase.SLEEP) -> None:
        self.phase = phase
        self.published_restart: list[str] = []
        self.published_spawn: list[tuple[SpawnProposal, str]] = []
        self.shutdown_calls: list[str] = []
        # If set, publish_spawn_request returns this Future.
        self.spawn_future: asyncio.Future[SpawnResult] | None = None

    async def publish_restart_request(self, reason: str) -> None:
        self.published_restart.append(reason)

    async def publish_spawn_request(
        self,
        proposal: SpawnProposal,
        correlation_id: str,
    ) -> asyncio.Future[SpawnResult]:
        self.published_spawn.append((proposal, correlation_id))
        if self.spawn_future is None:
            # Default: a Future that never resolves (used for timeout tests).
            self.spawn_future = asyncio.get_running_loop().create_future()
        return self.spawn_future

    async def shutdown(self, reason: str) -> None:
        self.shutdown_calls.append(reason)


def _region_root(tmp_path: Path, name: str = "test_region") -> Path:
    root = tmp_path / "regions" / name
    root.mkdir(parents=True)
    # Seed a prompt.md so GitTools has content for its initial commit.
    (root / "prompt.md").write_text("seed\n", encoding="utf-8")
    return root


_CAPS_FULL: dict[str, bool] = {
    "self_modify": True,
    "can_spawn": True,
}

_CAPS_STANDARD: dict[str, bool] = {
    "self_modify": True,
    "can_spawn": False,
}


def _build(
    tmp_path: Path,
    *,
    phase: LifecyclePhase = LifecyclePhase.SLEEP,
    caps: dict[str, bool] | None = None,
    region_name: str = "test_region",
) -> tuple[SelfModifyTools, _FakeRuntime, GitTools, Path]:
    root = _region_root(tmp_path, region_name)
    runtime = _FakeRuntime(phase=phase)
    git = GitTools(root, region_name=region_name)
    # MemoryStore expects its own subdirectory.
    memory = MemoryStore(
        root=root / "memory",
        region_name=region_name,
        runtime=runtime,
    )
    bootstrap_sha = git.current_head_sha()
    tools = SelfModifyTools(
        region_name=region_name,
        region_root=root,
        capabilities=caps if caps is not None else _CAPS_STANDARD,
        runtime=runtime,
        git_tools=git,
        memory=memory,
        bootstrap_sha=bootstrap_sha,
    )
    return tools, runtime, git, root


# ---------------------------------------------------------------------------
# edit_prompt
# ---------------------------------------------------------------------------


async def test_edit_prompt_phase_wake_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation):
        await tools.edit_prompt("new", "reason")


async def test_edit_prompt_missing_capability_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(
        tmp_path,
        caps={"self_modify": False, "can_spawn": False},
    )
    with pytest.raises(CapabilityDenied):
        await tools.edit_prompt("new", "reason")


async def test_edit_prompt_happy_path(tmp_path: Path) -> None:
    tools, _, _, root = _build(tmp_path)
    result = await tools.edit_prompt(_PROMPT_FIXTURE, "update prompt")
    assert result.ok
    assert result.path == root / "prompt.md"
    assert result.bytes_written == len(_PROMPT_FIXTURE.encode("utf-8"))
    assert result.diff_lines >= 1
    assert (root / "prompt.md").read_text(encoding="utf-8") == _PROMPT_FIXTURE


async def test_edit_prompt_empty_reason_rejected(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    with pytest.raises(ConfigError):
        await tools.edit_prompt("new", "")


async def test_edit_prompt_too_long_reason_rejected(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    with pytest.raises(ConfigError):
        await tools.edit_prompt("new", "x" * 201)


async def test_edit_prompt_text_too_large_rejected(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    oversized = "a" * (64 * 1024 + 1)
    with pytest.raises(ConfigError):
        await tools.edit_prompt(oversized, "too big")


# ---------------------------------------------------------------------------
# edit_subscriptions
# ---------------------------------------------------------------------------


async def test_edit_subscriptions_phase_wake_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation):
        await tools.edit_subscriptions(
            [SubscriptionEntry(topic="a/b", qos=1, description="")],
            "reason",
        )


async def test_edit_subscriptions_missing_capability_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(
        tmp_path,
        caps={"self_modify": False, "can_spawn": False},
    )
    with pytest.raises(CapabilityDenied):
        await tools.edit_subscriptions(
            [SubscriptionEntry(topic="a/b", qos=1, description="")],
            "reason",
        )


async def test_edit_subscriptions_happy_path(tmp_path: Path) -> None:
    tools, _, _, root = _build(tmp_path)
    entries = [
        SubscriptionEntry(topic="hive/a/b", qos=1, description="one"),
        SubscriptionEntry(topic="hive/x/+/y", qos=0, description="wild"),
    ]
    result = await tools.edit_subscriptions(entries, "add subs")
    assert result.ok
    assert result.path == root / "subscriptions.yaml"
    text = (root / "subscriptions.yaml").read_text(encoding="utf-8")
    assert "hive/a/b" in text
    assert "hive/x/+/y" in text


@pytest.mark.parametrize(
    "bad_topic",
    [
        "trailing/",             # trailing slash
        "has space/foo",         # whitespace
        "bad/+/in/middle",       # + is not in last or last-but-one
        "a/#/b",                 # # before last segment
        "",                      # empty
    ],
)
async def test_edit_subscriptions_rejects_bad_topic(tmp_path: Path, bad_topic: str) -> None:
    tools, _, _, _ = _build(tmp_path)
    with pytest.raises(ConfigError):
        await tools.edit_subscriptions(
            [SubscriptionEntry(topic=bad_topic, qos=1, description="")],
            "reason",
        )


# ---------------------------------------------------------------------------
# edit_handlers
# ---------------------------------------------------------------------------


async def test_edit_handlers_phase_wake_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation):
        await tools.edit_handlers(
            writes=[HandlerWrite(path="h.py", content="x = 1\n")],
            deletes=[],
            reason="long enough reason",
        )


async def test_edit_handlers_missing_capability_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(
        tmp_path,
        caps={"self_modify": False, "can_spawn": False},
    )
    with pytest.raises(CapabilityDenied):
        await tools.edit_handlers(
            writes=[HandlerWrite(path="h.py", content="x = 1\n")],
            deletes=[],
            reason="long enough reason",
        )


async def test_edit_handlers_sandbox_escape_write(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    with pytest.raises(SandboxEscape):
        await tools.edit_handlers(
            writes=[HandlerWrite(path="../outside.py", content="x = 1\n")],
            deletes=[],
            reason="escape attempt now",
        )


async def test_edit_handlers_sandbox_escape_delete(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    with pytest.raises(SandboxEscape):
        await tools.edit_handlers(
            writes=[],
            deletes=["../other.py"],
            reason="escape attempt now",
        )


async def test_edit_handlers_reason_too_short(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    with pytest.raises(ConfigError):
        await tools.edit_handlers(
            writes=[HandlerWrite(path="h.py", content="x = 1\n")],
            deletes=[],
            reason="short",
        )


async def test_edit_handlers_non_py_rejected(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    with pytest.raises(ConfigError):
        await tools.edit_handlers(
            writes=[HandlerWrite(path="notes.txt", content="oops")],
            deletes=[],
            reason="long enough reason",
        )


async def test_edit_handlers_happy_path_creates_file(tmp_path: Path) -> None:
    tools, _, _, root = _build(tmp_path)
    result = await tools.edit_handlers(
        writes=[HandlerWrite(path="on_audio.py", content="x = 1\n")],
        deletes=[],
        reason="add audio handler",
    )
    assert result.ok
    assert (root / "handlers" / "on_audio.py").read_text(encoding="utf-8") == (
        "x = 1\n"
    )


async def test_edit_handlers_deletes_existing(tmp_path: Path) -> None:
    tools, _, _, root = _build(tmp_path)
    # Pre-seed a handler file.
    handlers = root / "handlers"
    handlers.mkdir()
    (handlers / "old.py").write_text("y = 2\n", encoding="utf-8")
    result = await tools.edit_handlers(
        writes=[],
        deletes=["old.py"],
        reason="remove stale handler",
    )
    assert result.ok
    assert not (handlers / "old.py").exists()


async def test_edit_handlers_syntax_error_rolls_back(tmp_path: Path) -> None:
    tools, _, _, root = _build(tmp_path)
    handlers = root / "handlers"
    handlers.mkdir()
    original = "z = 3\n"
    (handlers / "pre.py").write_text(original, encoding="utf-8")

    # Stage an overwrite + a new bad file.
    result = await tools.edit_handlers(
        writes=[
            HandlerWrite(path="pre.py", content="z = 99\n"),
            HandlerWrite(path="bad.py", content="def oops(:\n"),
        ],
        deletes=[],
        reason="syntax rollback test ok",
    )
    assert not result.ok
    assert result.error is not None
    assert "syntax" in result.error.lower()
    # Pre-existing file untouched; bad file not created.
    assert (handlers / "pre.py").read_text(encoding="utf-8") == original
    assert not (handlers / "bad.py").exists()


async def test_edit_handlers_init_file_allowed(tmp_path: Path) -> None:
    tools, _, _, root = _build(tmp_path)
    result = await tools.edit_handlers(
        writes=[HandlerWrite(path="__init__.py", content="")],
        deletes=[],
        reason="create handlers package",
    )
    assert result.ok
    assert (root / "handlers" / "__init__.py").exists()


# ---------------------------------------------------------------------------
# write_stm
# ---------------------------------------------------------------------------


async def test_write_stm_callable_in_wake(tmp_path: Path) -> None:
    """write_stm has no @sleep_only — WAKE is allowed."""
    tools, _, _, _ = _build(tmp_path, phase=LifecyclePhase.WAKE)
    await tools.write_stm("focus", {"goal": "paint"})


async def test_write_stm_missing_capability_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(
        tmp_path,
        caps={"self_modify": False, "can_spawn": False},
        phase=LifecyclePhase.WAKE,
    )
    with pytest.raises(CapabilityDenied):
        await tools.write_stm("k", "v")


async def test_write_stm_delegates_to_memory(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    await tools.write_stm("alpha", _PRE_CHECK_VALUE)
    # Verify by reading back through the memory store.
    slot = await tools._memory.read_stm("alpha")  # type: ignore[attr-defined]
    assert slot is not None
    assert slot.value == _PRE_CHECK_VALUE


# ---------------------------------------------------------------------------
# write_ltm
# ---------------------------------------------------------------------------


async def test_write_ltm_phase_wake_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation):
        await tools.write_ltm("core/x.md", "body", "reason")


async def test_write_ltm_missing_capability_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(
        tmp_path,
        caps={"self_modify": False, "can_spawn": False},
    )
    with pytest.raises(CapabilityDenied):
        await tools.write_ltm("core/x.md", "body", "reason")


async def test_write_ltm_sandbox_escape(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    with pytest.raises(SandboxEscape):
        await tools.write_ltm("../out.md", "body", "reason")


async def test_write_ltm_non_md_rejected(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    with pytest.raises(ConfigError):
        await tools.write_ltm("core/notes.txt", "body", "reason")


async def test_write_ltm_happy_path(tmp_path: Path) -> None:
    tools, _, _, root = _build(tmp_path)
    result = await tools.write_ltm(
        "core/identity.md",
        "I am the test region.",
        "seed identity",
    )
    assert result.ok
    target = root / "memory" / "ltm" / "core" / "identity.md"
    assert target.exists()
    assert "I am the test region." in target.read_text(encoding="utf-8")


async def test_write_ltm_custom_metadata_flows_through(tmp_path: Path) -> None:
    """Caller-supplied metadata must reach MemoryStore.write_ltm unchanged."""
    tools, _, _, _ = _build(tmp_path)
    captured: dict[str, object] = {}

    async def _spy(
        path: str,
        content: str,
        metadata: object,
        reason: str,
    ) -> object:
        captured["path"] = path
        captured["content"] = content
        captured["metadata"] = metadata
        captured["reason"] = reason
        return LtmWriteResult(path=path, created=True, summary=reason)

    tools._memory.write_ltm = _spy  # type: ignore[assignment,method-assign]

    result = await tools.write_ltm(
        "core/reflection.md",
        "I felt grateful today.",
        "journal entry",
        topic="reflection",
        importance=_CUSTOM_IMPORTANCE,
        tags=["gratitude"],
        emotional_tag="positive",
    )
    assert result.ok
    meta = captured["metadata"]
    assert isinstance(meta, LtmMetadata)
    assert meta.topic == "reflection"
    assert meta.importance == _CUSTOM_IMPORTANCE
    assert meta.tags == ["gratitude"]
    assert meta.emotional_tag == "positive"


async def test_write_ltm_defaults_unchanged(tmp_path: Path) -> None:
    """Without metadata kwargs, MemoryStore receives the synthesized defaults."""
    tools, _, _, _ = _build(tmp_path)
    captured: dict[str, object] = {}

    async def _spy(
        path: str,
        content: str,
        metadata: object,
        reason: str,
    ) -> object:
        captured["metadata"] = metadata
        return LtmWriteResult(path=path, created=True, summary=reason)

    tools._memory.write_ltm = _spy  # type: ignore[assignment,method-assign]

    result = await tools.write_ltm(
        "core/identity.md",
        "I am the test region.",
        "seed identity",
    )
    assert result.ok
    meta = captured["metadata"]
    assert isinstance(meta, LtmMetadata)
    assert meta.topic == "self_modify"
    assert meta.importance == _DEFAULT_IMPORTANCE
    assert meta.tags == []
    assert meta.emotional_tag is None


# ---------------------------------------------------------------------------
# commit_changes
# ---------------------------------------------------------------------------


async def test_commit_changes_phase_wake_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation):
        await tools.commit_changes("msg")


async def test_commit_changes_missing_capability_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(
        tmp_path,
        caps={"self_modify": False, "can_spawn": False},
    )
    with pytest.raises(CapabilityDenied):
        await tools.commit_changes("msg")


async def test_commit_changes_delegates_to_git(tmp_path: Path) -> None:
    tools, _, git, root = _build(tmp_path)
    # Dirty the tree so commit isn't empty.
    (root / "prompt.md").write_text("changed\n", encoding="utf-8")
    result = await tools.commit_changes("update prompt")
    assert isinstance(result, CommitResult)
    assert len(result.sha) == _SHA_LEN
    assert git.status_clean()


# ---------------------------------------------------------------------------
# request_restart
# ---------------------------------------------------------------------------


async def test_request_restart_phase_wake_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path, phase=LifecyclePhase.WAKE)
    with pytest.raises(PhaseViolation):
        await tools.request_restart("reason")


async def test_request_restart_missing_capability_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(
        tmp_path,
        caps={"self_modify": False, "can_spawn": False},
    )
    with pytest.raises(CapabilityDenied):
        await tools.request_restart("reason")


async def test_request_restart_uncommitted_changes_returns_false(tmp_path: Path) -> None:
    tools, _, _, root = _build(tmp_path)
    # Dirty the tree without committing.
    (root / "prompt.md").write_text("dirty\n", encoding="utf-8")
    result = await tools.request_restart("want restart")
    assert result == {"ok": False, "reason": "uncommitted_changes"}


async def test_request_restart_no_change_since_boot(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    # Clean tree, no commits since bootstrap.
    result = await tools.request_restart("want restart")
    assert result == {"ok": False, "reason": "no_change_since_boot"}


async def test_request_restart_happy_path(tmp_path: Path) -> None:
    tools, runtime, git, root = _build(tmp_path)
    # Make a real change + commit so HEAD advances.
    (root / "prompt.md").write_text("updated\n", encoding="utf-8")
    git.commit_all("update prompt")
    result = await tools.request_restart("ready")
    assert result == {"ok": True}
    assert runtime.published_restart == ["ready"]
    assert runtime.shutdown_calls == ["restart"]


# ---------------------------------------------------------------------------
# spawn_new_region
# ---------------------------------------------------------------------------


def _valid_proposal(name: str = "new_region") -> SpawnProposal:
    return SpawnProposal(
        name=name,
        role="test",
        modality=None,
        llm={"provider": "anthropic", "model": "claude-3-opus", "params": {}},
        capabilities=CapabilityProfile(
            self_modify=True,
            tool_use="none",
            vision=False,
            audio=False,
        ),
        starter_prompt="I am new.",
        initial_subscriptions=[],
    )


async def test_spawn_new_region_non_acc_raises(tmp_path: Path) -> None:
    # Standard caps have can_spawn=False.
    tools, _, _, _ = _build(tmp_path, caps=_CAPS_STANDARD)
    with pytest.raises(CapabilityDenied):
        await tools.spawn_new_region(_valid_proposal())


async def test_spawn_new_region_phase_wake_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(
        tmp_path,
        caps=_CAPS_FULL,
        phase=LifecyclePhase.WAKE,
    )
    with pytest.raises(PhaseViolation):
        await tools.spawn_new_region(_valid_proposal())


async def test_spawn_new_region_invalid_name_raises(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path, caps=_CAPS_FULL)
    with pytest.raises(ConfigError):
        await tools.spawn_new_region(_valid_proposal(name="Bad-Name"))


async def test_spawn_new_region_happy_path(tmp_path: Path) -> None:
    tools, runtime, _, _ = _build(tmp_path, caps=_CAPS_FULL)
    # Pre-seed the runtime's future with a success result.
    loop = asyncio.get_running_loop()
    fut: asyncio.Future[SpawnResult] = loop.create_future()
    runtime.spawn_future = fut
    fut.set_result(SpawnResult(ok=True, sha="cafebabe"))

    result = await tools.spawn_new_region(_valid_proposal())
    assert result.ok is True
    assert result.sha == "cafebabe"
    assert runtime.published_spawn, "proposal should have been published"


async def test_spawn_new_region_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools, runtime, _, _ = _build(tmp_path, caps=_CAPS_FULL)
    # Future that never resolves; we compress the timeout for testability.
    loop = asyncio.get_running_loop()
    runtime.spawn_future = loop.create_future()
    # Compress the module-level timeout so the test is fast.
    monkeypatch.setattr(sm_module, "_SPAWN_TIMEOUT_S", 0.05)
    result = await tools.spawn_new_region(_valid_proposal())
    assert result.ok is False
    assert result.reason == "timeout"


# ---------------------------------------------------------------------------
# sandbox helper — unit coverage
# ---------------------------------------------------------------------------


async def test_sandboxed_path_rejects_parent_escape(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    with pytest.raises(SandboxEscape):
        tools._sandboxed_path("../../../etc/passwd")  # type: ignore[attr-defined]


async def test_sandboxed_path_rejects_absolute(tmp_path: Path) -> None:
    tools, _, _, _ = _build(tmp_path)
    # Use a path that is definitely outside the region root.
    outside = (tmp_path / "outside").resolve()
    with pytest.raises(SandboxEscape):
        tools._sandboxed_path(str(outside))  # type: ignore[attr-defined]


async def test_sandboxed_path_accepts_nested(tmp_path: Path) -> None:
    tools, _, _, root = _build(tmp_path)
    resolved = tools._sandboxed_path("handlers/on_x.py")  # type: ignore[attr-defined]
    assert resolved == (root / "handlers" / "on_x.py").resolve()
