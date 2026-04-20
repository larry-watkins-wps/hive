"""Unit tests for glia.spawn_executor — Task 5.7a.

Covers the 8-step pipeline from spec §E.11 + the query responder.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from ruamel.yaml import YAML

from glia.acl_manager import AclManager, ApplyResult
from glia.launcher import GliaError, Launcher
from glia.registry import RegionRegistry
from glia.spawn_executor import (
    METACOG_ERROR_DETECTED,
    TOPIC_SPAWN_COMPLETE,
    TOPIC_SPAWN_FAILED,
    TOPIC_SPAWN_QUERY_RESPONSE,
    SpawnExecutor,
    SpawnLogEntry,
)
from shared.message_envelope import Envelope

# Avoid magic-value ruff noise.
LOG_CAP = 100
OVERFLOW = 101
THREE_ENTRIES = 3

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _make_runner(*results: subprocess.CompletedProcess[str]) -> MagicMock:
    mock = MagicMock()
    mock.side_effect = list(results)
    return mock


def _default_git_runner() -> MagicMock:
    """Four git calls: init, add, commit, rev-parse -> sha."""
    return _make_runner(
        _completed(returncode=0),
        _completed(returncode=0),
        _completed(returncode=0),
        _completed(returncode=0, stdout="cafef00d\n"),
    )


def _valid_payload(name: str = "new_region") -> dict:
    return {
        "name": name,
        "role": "a freshly spawned region for testing purposes",
        "llm": {"provider": "anthropic", "model": "claude-haiku-4-5"},
        "capabilities": {
            "self_modify": True,
            "tool_use": "basic",
            "vision": False,
            "audio": False,
        },
        "starter_prompt": (
            "You are a newly spawned region. "
            + "Fulfil your role by observing and responding to relevant topics. "
            + "Start modestly; learn from feedback."
        ),
        "initial_subscriptions": [
            {
                "topic": "hive/cognitive/new_region/#",
                "qos": 1,
                "description": "own inbox",
            }
        ],
        "approved_by_acc": "00000000-0000-0000-0000-000000000001",
    }


def _spawn_envelope(
    data: dict | None = None, correlation_id: str = "corr-xyz"
) -> Envelope:
    return Envelope.new(
        source_region="anterior_cingulate",
        topic="hive/system/spawn/request",
        content_type="application/hive+spawn-request",
        data=data if data is not None else _valid_payload(),
        correlation_id=correlation_id,
    )


def _query_envelope(data: dict, correlation_id: str = "q-1") -> Envelope:
    return Envelope.new(
        source_region="anterior_cingulate",
        topic="hive/system/spawn/query",
        content_type="application/json",
        data=data,
        correlation_id=correlation_id,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def publish() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def launcher() -> MagicMock:
    return MagicMock(spec=Launcher)


@pytest.fixture
def acl_manager() -> MagicMock:
    mgr = MagicMock(spec=AclManager)
    mgr.render_and_apply = AsyncMock(return_value=ApplyResult(ok=True))
    return mgr


@pytest.fixture
def registry() -> RegionRegistry:
    return RegionRegistry.load()


@pytest.fixture
def acl_templates(tmp_path: Path) -> Path:
    """Create a tmp acl_templates dir containing the stub."""
    d = tmp_path / "bus" / "acl_templates"
    d.mkdir(parents=True)
    (d / "_new_region_stub.j2").write_text(
        "topic read  hive/cognitive/{{ region }}/#\n"
        "topic write hive/cognitive/{{ region }}/#\n",
        encoding="utf-8",
    )
    return d


@pytest.fixture
def regions_root(tmp_path: Path) -> Path:
    root = tmp_path / "regions"
    root.mkdir()
    return root


@pytest.fixture
def executor(
    launcher: MagicMock,
    registry: RegionRegistry,
    acl_manager: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
    acl_templates: Path,
) -> SpawnExecutor:
    return SpawnExecutor(
        launcher=launcher,
        registry=registry,
        acl_manager=acl_manager,
        publish=publish,
        regions_root=regions_root,
        acl_templates_dir=acl_templates,
        runner=_default_git_runner(),
    )


# ---------------------------------------------------------------------------
# 1-2. Schema / pattern validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schema_invalid_publishes_failed_and_metacog(
    launcher: MagicMock,
    registry: RegionRegistry,
    acl_manager: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
    acl_templates: Path,
) -> None:
    payload = _valid_payload()
    del payload["role"]  # required field
    envelope = _spawn_envelope(payload)

    ex = SpawnExecutor(
        launcher=launcher,
        registry=registry,
        acl_manager=acl_manager,
        publish=publish,
        regions_root=regions_root,
        acl_templates_dir=acl_templates,
        runner=_default_git_runner(),
    )

    entry = await ex.handle_request(envelope)

    assert entry.ok is False
    assert entry.reason is not None and "role" in entry.reason

    # Should have published: failed + metacog error.
    topics = [call.args[0].topic for call in publish.await_args_list]
    assert TOPIC_SPAWN_FAILED in topics
    assert METACOG_ERROR_DETECTED in topics

    # No scaffolding occurred.
    assert not (regions_root / "new_region").exists()
    assert not (acl_templates / "new_region.j2").exists()
    launcher.launch_region.assert_not_called()


@pytest.mark.asyncio
async def test_name_pattern_invalid_rejected(
    executor: SpawnExecutor, publish: AsyncMock
) -> None:
    payload = _valid_payload(name="BadName")
    entry = await executor.handle_request(_spawn_envelope(payload))

    assert entry.ok is False
    topics = [call.args[0].topic for call in publish.await_args_list]
    assert TOPIC_SPAWN_FAILED in topics


# ---------------------------------------------------------------------------
# 3-5. Name uniqueness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_name_exists_on_disk_rejected(
    executor: SpawnExecutor, regions_root: Path, publish: AsyncMock
) -> None:
    (regions_root / "fresh_one").mkdir()
    payload = _valid_payload(name="fresh_one")
    entry = await executor.handle_request(_spawn_envelope(payload))

    assert entry.ok is False
    assert entry.reason is not None
    assert "exists" in entry.reason.lower() or "uniq" in entry.reason.lower()


@pytest.mark.asyncio
async def test_name_in_registry_rejected(executor: SpawnExecutor) -> None:
    payload = _valid_payload(name="amygdala")
    entry = await executor.handle_request(_spawn_envelope(payload))

    assert entry.ok is False
    assert entry.reason is not None
    assert "registry" in entry.reason.lower() or "exists" in entry.reason.lower()


@pytest.mark.asyncio
async def test_name_reserved_rejected(executor: SpawnExecutor) -> None:
    payload = _valid_payload(name="raphe_nuclei")
    entry = await executor.handle_request(_spawn_envelope(payload))

    assert entry.ok is False


# ---------------------------------------------------------------------------
# 6-7. Scaffold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scaffold_creates_all_expected_files(
    executor: SpawnExecutor, regions_root: Path
) -> None:
    payload = _valid_payload()
    await executor.handle_request(_spawn_envelope(payload))

    region_dir = regions_root / "new_region"
    assert region_dir.is_dir()
    assert (region_dir / "config.yaml").is_file()
    assert (region_dir / "prompt.md").is_file()
    assert (region_dir / "subscriptions.yaml").is_file()
    assert (region_dir / "handlers" / "__init__.py").is_file()
    assert (region_dir / "memory" / "stm.json").is_file()
    assert (region_dir / "memory" / "ltm" / ".gitkeep").is_file()

    stm = json.loads((region_dir / "memory" / "stm.json").read_text("utf-8"))
    assert stm["schema_version"] == 1
    assert stm["region"] == "new_region"
    assert stm["slots"] == {}
    assert stm["recent_events"] == []
    assert "updated_at" in stm

    prompt = (region_dir / "prompt.md").read_text("utf-8")
    assert prompt == payload["starter_prompt"]


@pytest.mark.asyncio
async def test_scaffold_runs_git_init_and_commit(
    launcher: MagicMock,
    registry: RegionRegistry,
    acl_manager: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
    acl_templates: Path,
) -> None:
    runner = _make_runner(
        _completed(returncode=0),
        _completed(returncode=0),
        _completed(returncode=0),
        _completed(returncode=0, stdout="abc1234\n"),
    )
    ex = SpawnExecutor(
        launcher=launcher,
        registry=registry,
        acl_manager=acl_manager,
        publish=publish,
        regions_root=regions_root,
        acl_templates_dir=acl_templates,
        runner=runner,
    )
    entry = await ex.handle_request(_spawn_envelope())

    assert entry.ok is True
    assert entry.commit_sha == "abc1234"

    # Inspect runner invocations
    call_cmds = [c.args[0] for c in runner.call_args_list]
    assert call_cmds[0][:2] == ["git", "init"]
    assert call_cmds[1][:2] == ["git", "add"]
    assert call_cmds[2][:2] == ["git", "commit"]
    assert call_cmds[3] == ["git", "rev-parse", "HEAD"]


# ---------------------------------------------------------------------------
# 8-9. ACL template + apply
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acl_template_copied_to_new_region_filename(
    executor: SpawnExecutor, acl_templates: Path
) -> None:
    await executor.handle_request(_spawn_envelope())
    assert (acl_templates / "new_region.j2").is_file()
    content = (acl_templates / "new_region.j2").read_text("utf-8")
    assert "{{ region }}" in content


@pytest.mark.asyncio
async def test_acl_manager_render_and_apply_called(
    executor: SpawnExecutor, acl_manager: MagicMock
) -> None:
    await executor.handle_request(_spawn_envelope())
    acl_manager.render_and_apply.assert_awaited_once()


# ---------------------------------------------------------------------------
# 10-11. Launcher + complete event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_launcher_launch_region_called(
    executor: SpawnExecutor, launcher: MagicMock
) -> None:
    await executor.handle_request(_spawn_envelope())
    launcher.launch_region.assert_called_once_with("new_region")


@pytest.mark.asyncio
async def test_complete_event_published(
    executor: SpawnExecutor, publish: AsyncMock
) -> None:
    entry = await executor.handle_request(
        _spawn_envelope(correlation_id="corr-abc")
    )

    assert entry.ok is True
    complete_calls = [
        c.args[0]
        for c in publish.await_args_list
        if c.args[0].topic == TOPIC_SPAWN_COMPLETE
    ]
    assert len(complete_calls) == 1
    env = complete_calls[0]
    assert env.source_region == "glia"
    assert env.correlation_id == "corr-abc"
    data = env.payload.data
    assert data["name"] == "new_region"
    assert data["commit_sha"] == "cafef00d"
    assert data["approved_by_acc"] == "00000000-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# 12. Failure cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_event_cleans_up_and_publishes(
    launcher: MagicMock,
    registry: RegionRegistry,
    acl_manager: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
    acl_templates: Path,
) -> None:
    launcher.launch_region.side_effect = GliaError("no image")
    ex = SpawnExecutor(
        launcher=launcher,
        registry=registry,
        acl_manager=acl_manager,
        publish=publish,
        regions_root=regions_root,
        acl_templates_dir=acl_templates,
        runner=_default_git_runner(),
    )
    entry = await ex.handle_request(_spawn_envelope(correlation_id="corr-fail"))

    assert entry.ok is False
    assert entry.reason is not None

    # Cleanup happened
    assert not (regions_root / "new_region").exists()
    assert not (acl_templates / "new_region.j2").exists()

    topics = [call.args[0].topic for call in publish.await_args_list]
    assert TOPIC_SPAWN_FAILED in topics

    # failed event carries correlation_id
    failed_env = next(
        c.args[0]
        for c in publish.await_args_list
        if c.args[0].topic == TOPIC_SPAWN_FAILED
    )
    assert failed_env.correlation_id == "corr-fail"
    assert "reason" in failed_env.payload.data


@pytest.mark.asyncio
async def test_acl_render_failure_cleans_up(
    launcher: MagicMock,
    registry: RegionRegistry,
    acl_manager: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
    acl_templates: Path,
) -> None:
    """I-1: ApplyResult(ok=False) triggers cleanup + spawn/failed, no spawn/complete."""
    acl_manager.render_and_apply = AsyncMock(
        return_value=ApplyResult(ok=False, reason="acl conflict: duplicate topic")
    )
    ex = SpawnExecutor(
        launcher=launcher,
        registry=registry,
        acl_manager=acl_manager,
        publish=publish,
        regions_root=regions_root,
        acl_templates_dir=acl_templates,
        runner=_default_git_runner(),
    )
    entry = await ex.handle_request(_spawn_envelope(correlation_id="corr-acl"))

    assert entry.ok is False
    assert entry.reason is not None
    assert "ACL render_and_apply failed" in entry.reason or "acl conflict" in entry.reason

    # (a) region dir removed
    assert not (regions_root / "new_region").exists()
    # (b) ACL template removed
    assert not (acl_templates / "new_region.j2").exists()

    topics = [call.args[0].topic for call in publish.await_args_list]
    # (c) spawn/failed published
    assert TOPIC_SPAWN_FAILED in topics
    # (d) no spawn/complete published
    assert TOPIC_SPAWN_COMPLETE not in topics


@pytest.mark.asyncio
async def test_cancellation_cleans_up_but_does_not_publish(
    launcher: MagicMock,
    registry: RegionRegistry,
    acl_manager: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
    acl_templates: Path,
) -> None:
    """I-2: CancelledError during pipeline cleans up scaffold without publishing."""
    # Use an Event that never fires so the task can be cancelled mid-pipeline.
    block_event = asyncio.Event()

    async def _blocking_render_and_apply() -> None:
        await block_event.wait()  # will never resolve; task is cancelled first

    acl_manager.render_and_apply = AsyncMock(side_effect=_blocking_render_and_apply)

    ex = SpawnExecutor(
        launcher=launcher,
        registry=registry,
        acl_manager=acl_manager,
        publish=publish,
        regions_root=regions_root,
        acl_templates_dir=acl_templates,
        runner=_default_git_runner(),
    )

    task = asyncio.create_task(ex.handle_request(_spawn_envelope()))

    # Wait for the task to reach the blocking point, then cancel.
    # 50 ms deadline is more than enough for the synchronous scaffold steps.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), timeout=0.05)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # region dir removed
    assert not (regions_root / "new_region").exists()
    # ACL template removed (was written before render_and_apply was called)
    assert not (acl_templates / "new_region.j2").exists()
    # No spawn/complete or spawn/failed published
    spawn_topics = [
        call.args[0].topic
        for call in publish.await_args_list
        if call.args[0].topic in (TOPIC_SPAWN_COMPLETE, TOPIC_SPAWN_FAILED)
    ]
    assert spawn_topics == []


# ---------------------------------------------------------------------------
# 13-15. Log behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_log_entry_appended_on_success(executor: SpawnExecutor) -> None:
    await executor.handle_request(_spawn_envelope(correlation_id="corr-1"))
    last = executor.log_entries()[-1]
    assert last.ok is True
    assert last.name == "new_region"
    assert last.commit_sha == "cafef00d"
    assert last.correlation_id == "corr-1"


@pytest.mark.asyncio
async def test_log_entry_appended_on_failure(
    launcher: MagicMock,
    registry: RegionRegistry,
    acl_manager: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
    acl_templates: Path,
) -> None:
    launcher.launch_region.side_effect = GliaError("boom")
    ex = SpawnExecutor(
        launcher=launcher,
        registry=registry,
        acl_manager=acl_manager,
        publish=publish,
        regions_root=regions_root,
        acl_templates_dir=acl_templates,
        runner=_default_git_runner(),
    )
    await ex.handle_request(_spawn_envelope())

    last = ex.log_entries()[-1]
    assert last.ok is False
    assert last.reason is not None


def test_log_rolling_at_size(
    launcher: MagicMock,
    registry: RegionRegistry,
    acl_manager: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
    acl_templates: Path,
) -> None:
    ex = SpawnExecutor(
        launcher=launcher,
        registry=registry,
        acl_manager=acl_manager,
        publish=publish,
        regions_root=regions_root,
        acl_templates_dir=acl_templates,
        runner=MagicMock(),
    )
    # Seed 101 entries directly.
    for i in range(OVERFLOW):
        ex._log.append(  # noqa: SLF001
            SpawnLogEntry(
                name=f"r{i}",
                ok=True,
                change_id=None,
                correlation_id=None,
                commit_sha="x",
                reason=None,
                timestamp="2026-04-20T00:00:00Z",
            )
        )
    assert len(ex.log_entries()) == LOG_CAP
    assert ex.log_entries()[0].name == "r1"  # r0 dropped


# ---------------------------------------------------------------------------
# 16-19. Query responder
# ---------------------------------------------------------------------------


def _seed_log(ex: SpawnExecutor) -> None:
    entries = [
        SpawnLogEntry(
            name="alpha",
            ok=True,
            change_id=None,
            correlation_id="c-1",
            commit_sha="sha1",
            reason=None,
            timestamp="2026-04-20T00:00:01Z",
        ),
        SpawnLogEntry(
            name="beta",
            ok=False,
            change_id=None,
            correlation_id="c-2",
            commit_sha=None,
            reason="boom",
            timestamp="2026-04-20T00:00:02Z",
        ),
        SpawnLogEntry(
            name="gamma",
            ok=True,
            change_id=None,
            correlation_id="c-3",
            commit_sha="sha3",
            reason=None,
            timestamp="2026-04-20T00:00:03Z",
        ),
    ]
    for e in entries:
        ex._log.append(e)  # noqa: SLF001


@pytest.mark.asyncio
async def test_query_returns_matching_entry_by_name(
    executor: SpawnExecutor, publish: AsyncMock
) -> None:
    _seed_log(executor)
    publish.reset_mock()
    await executor.handle_query(_query_envelope({"name": "beta"}))

    publish.assert_awaited_once()
    env = publish.await_args.args[0]
    assert env.topic == TOPIC_SPAWN_QUERY_RESPONSE
    assert env.correlation_id == "q-1"
    entries = env.payload.data["entries"]
    assert len(entries) == 1
    assert entries[0]["name"] == "beta"


@pytest.mark.asyncio
async def test_query_returns_all_when_no_filter(
    executor: SpawnExecutor, publish: AsyncMock
) -> None:
    _seed_log(executor)
    publish.reset_mock()
    await executor.handle_query(_query_envelope({}))

    env = publish.await_args.args[0]
    entries = env.payload.data["entries"]
    assert len(entries) == THREE_ENTRIES


@pytest.mark.asyncio
async def test_query_correlation_id_matching(
    executor: SpawnExecutor, publish: AsyncMock
) -> None:
    _seed_log(executor)
    publish.reset_mock()
    await executor.handle_query(_query_envelope({"correlation_id": "c-3"}))
    env = publish.await_args.args[0]
    entries = env.payload.data["entries"]
    assert len(entries) == 1
    assert entries[0]["name"] == "gamma"


@pytest.mark.asyncio
async def test_query_unknown_name_returns_empty_list(
    executor: SpawnExecutor, publish: AsyncMock
) -> None:
    _seed_log(executor)
    publish.reset_mock()
    await executor.handle_query(_query_envelope({"name": "ghost"}))
    env = publish.await_args.args[0]
    assert env.payload.data["entries"] == []


# ---------------------------------------------------------------------------
# 20. config.yaml shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_config_yaml_shape(
    executor: SpawnExecutor, regions_root: Path
) -> None:
    await executor.handle_request(_spawn_envelope())

    yaml = YAML(typ="safe")
    with (regions_root / "new_region" / "config.yaml").open(
        "r", encoding="utf-8"
    ) as fh:
        cfg = yaml.load(fh)

    assert cfg["schema_version"] == 1
    assert cfg["name"] == "new_region"
    assert cfg["role"] == "a freshly spawned region for testing purposes"
    assert cfg["llm"]["provider"] == "anthropic"
    assert cfg["llm"]["model"] == "claude-haiku-4-5"
    assert cfg["capabilities"]["self_modify"] is True
    assert cfg["capabilities"]["tool_use"] == "basic"


@pytest.mark.asyncio
async def test_subscriptions_yaml_written_verbatim(
    executor: SpawnExecutor, regions_root: Path
) -> None:
    await executor.handle_request(_spawn_envelope())
    yaml = YAML(typ="safe")
    with (regions_root / "new_region" / "subscriptions.yaml").open(
        "r", encoding="utf-8"
    ) as fh:
        subs = yaml.load(fh)

    assert isinstance(subs, list)
    assert subs[0]["topic"] == "hive/cognitive/new_region/#"
    assert subs[0]["qos"] == 1
