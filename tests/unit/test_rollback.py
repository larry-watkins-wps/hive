"""Unit tests for glia.rollback — Task 5.6.

Covers:
  1.  rollback_region with no .git dir -> ok=False, reason="no git".
  2.  rev-parse returncode != 0 -> ok=False, reason="no parent commit".
  3.  rev-parse returncode=0 but empty stdout -> ok=False, reason="no parent commit".
  4.  git revert returncode != 0 -> ok=False, "git revert failed" in reason;
      launcher NOT called; publish NOT called.
  5.  Happy path -> rev-parse + revert ok; launcher stop+launch called; publish
      called once with region_rollback envelope; ok=True, reverted_to=<sha>.
  6.  launch_region raises GliaError -> ok=False, reason contains "relaunch
      failed"; publish called with kind="rollback_failed".
  7.  stop_region raises GliaError -> ok=False, reason contains "relaunch
      failed" (stop failure treated identically).
  8.  mark_region_dead -> publish called once with topic
      hive/metacognition/error/detected, kind="rollback_failed".
  9.  Publish failure during success-path does not raise (logged, return ok=True).
  10. Subprocess runner invoked with expected args/cwd.
  11. Two successive rollback_region calls — no module-level state carries.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from glia.launcher import GliaError, Launcher
from glia.rollback import Rollback, RollbackResult

# Named constants — keep ruff PLR2004 quiet on "magic values".
EXPECTED_RUNNER_CALLS = 2  # rev-parse + revert
EXPECTED_RELAUNCH_CALLS = 2  # two independent rollback_region invocations

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
def regions_root(tmp_path: Path) -> Path:
    """Create regions/amygdala/.git inside tmp_path and return regions/."""
    root = tmp_path / "regions" / "amygdala"
    (root / ".git").mkdir(parents=True)
    return tmp_path / "regions"


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _make_runner(
    *results: subprocess.CompletedProcess[str],
) -> MagicMock:
    """Build a MagicMock subprocess.run replacement with queued results."""
    mock = MagicMock()
    mock.side_effect = list(results)
    return mock


# ---------------------------------------------------------------------------
# 1. no .git
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_no_git_returns_error(
    launcher: MagicMock, publish: AsyncMock, tmp_path: Path
) -> None:
    # regions_root exists but no .git/ under amygdala
    regions_root = tmp_path / "regions"
    (regions_root / "amygdala").mkdir(parents=True)
    rb = Rollback(launcher, publish=publish, regions_root=regions_root)

    result = await rb.rollback_region("amygdala", reason="crash")

    assert result.ok is False
    assert result.reason == "no git"
    launcher.stop_region.assert_not_called()
    launcher.launch_region.assert_not_called()
    publish.assert_not_called()


# ---------------------------------------------------------------------------
# 2. rev-parse returncode != 0
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_no_parent_returns_error(
    launcher: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
) -> None:
    runner = _make_runner(_completed(returncode=128, stderr="fatal"))
    rb = Rollback(
        launcher, publish=publish, regions_root=regions_root, runner=runner
    )

    result = await rb.rollback_region("amygdala", reason="crash")

    assert result.ok is False
    assert result.reason == "no parent commit"
    launcher.stop_region.assert_not_called()
    launcher.launch_region.assert_not_called()
    publish.assert_not_called()


# ---------------------------------------------------------------------------
# 3. rev-parse returncode=0 but empty stdout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_empty_stdout_returns_no_parent(
    launcher: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
) -> None:
    runner = _make_runner(_completed(returncode=0, stdout="   \n"))
    rb = Rollback(
        launcher, publish=publish, regions_root=regions_root, runner=runner
    )

    result = await rb.rollback_region("amygdala", reason="crash")

    assert result.ok is False
    assert result.reason == "no parent commit"


# ---------------------------------------------------------------------------
# 4. git revert failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_git_revert_failed(
    launcher: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
) -> None:
    runner = _make_runner(
        _completed(returncode=0, stdout="abc123\n"),
        _completed(returncode=1, stderr="conflict"),
    )
    rb = Rollback(
        launcher, publish=publish, regions_root=regions_root, runner=runner
    )

    result = await rb.rollback_region("amygdala", reason="crash")

    assert result.ok is False
    assert result.reason is not None
    assert "git revert failed" in result.reason
    launcher.stop_region.assert_not_called()
    launcher.launch_region.assert_not_called()
    publish.assert_not_called()


# ---------------------------------------------------------------------------
# 5. happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_happy_path(
    launcher: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
) -> None:
    runner = _make_runner(
        _completed(returncode=0, stdout="abc123\n"),
        _completed(returncode=0, stdout=""),
    )
    rb = Rollback(
        launcher, publish=publish, regions_root=regions_root, runner=runner
    )

    result = await rb.rollback_region("amygdala", reason="heartbeat gap")

    assert result.ok is True
    assert result.reverted_to == "abc123"
    launcher.stop_region.assert_called_once_with("amygdala")
    launcher.launch_region.assert_called_once_with("amygdala")
    publish.assert_awaited_once()

    (envelope,) = publish.await_args.args
    assert envelope.source_region == "glia"
    assert envelope.topic == "hive/metacognition/error/detected"
    assert envelope.payload.content_type == "application/json"
    data = envelope.payload.data
    assert data["kind"] == "region_rollback"
    assert data["detail"] == "rolled back to abc123"
    assert data["context"] == {
        "region": "amygdala",
        "reason": "heartbeat gap",
        "reverted_sha": "abc123",
    }


# ---------------------------------------------------------------------------
# 6. launch_region raises GliaError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_relaunch_failure_returns_error(
    launcher: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
) -> None:
    runner = _make_runner(
        _completed(returncode=0, stdout="abc123\n"),
        _completed(returncode=0, stdout=""),
    )
    launcher.launch_region.side_effect = GliaError("boom")
    rb = Rollback(
        launcher, publish=publish, regions_root=regions_root, runner=runner
    )

    result = await rb.rollback_region("amygdala", reason="crash")

    assert result.ok is False
    assert result.reason is not None
    assert "relaunch failed" in result.reason

    publish.assert_awaited_once()
    (envelope,) = publish.await_args.args
    assert envelope.payload.data["kind"] == "rollback_failed"
    assert envelope.payload.data["context"]["region"] == "amygdala"


# ---------------------------------------------------------------------------
# 7. stop_region raises GliaError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_stop_failure_treated_as_relaunch_failure(
    launcher: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
) -> None:
    runner = _make_runner(
        _completed(returncode=0, stdout="abc123\n"),
        _completed(returncode=0, stdout=""),
    )
    launcher.stop_region.side_effect = GliaError("stop exploded")
    rb = Rollback(
        launcher, publish=publish, regions_root=regions_root, runner=runner
    )

    result = await rb.rollback_region("amygdala", reason="crash")

    assert result.ok is False
    assert result.reason is not None
    assert "relaunch failed" in result.reason
    launcher.launch_region.assert_not_called()
    publish.assert_awaited_once()
    (envelope,) = publish.await_args.args
    assert envelope.payload.data["kind"] == "rollback_failed"


# ---------------------------------------------------------------------------
# 8. mark_region_dead
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_region_dead_publishes_correct_envelope(
    launcher: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
) -> None:
    rb = Rollback(launcher, publish=publish, regions_root=regions_root)

    await rb.mark_region_dead("amygdala", reason="rollback exhausted")

    publish.assert_awaited_once()
    (envelope,) = publish.await_args.args
    assert envelope.source_region == "glia"
    assert envelope.topic == "hive/metacognition/error/detected"
    data = envelope.payload.data
    assert data["kind"] == "rollback_failed"
    assert data["context"]["region"] == "amygdala"
    assert data["context"]["reason"] == "rollback exhausted"


# ---------------------------------------------------------------------------
# 9. publish failure on success path is swallowed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_publish_failure_does_not_raise(
    launcher: MagicMock,
    regions_root: Path,
) -> None:
    # Design choice (documented in rollback.py): on success path, revert+relaunch
    # already happened, so publish errors must not invalidate that outcome.
    publish = AsyncMock(side_effect=RuntimeError("broker down"))
    runner = _make_runner(
        _completed(returncode=0, stdout="abc123\n"),
        _completed(returncode=0, stdout=""),
    )
    rb = Rollback(
        launcher, publish=publish, regions_root=regions_root, runner=runner
    )

    result = await rb.rollback_region("amygdala", reason="crash")

    assert result.ok is True
    assert result.reverted_to == "abc123"


# ---------------------------------------------------------------------------
# 10. subprocess runner invoked with correct args
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_runner_invoked_with_correct_args(
    launcher: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
) -> None:
    runner = _make_runner(
        _completed(returncode=0, stdout="deadbee\n"),
        _completed(returncode=0, stdout=""),
    )
    rb = Rollback(
        launcher, publish=publish, regions_root=regions_root, runner=runner
    )

    await rb.rollback_region("amygdala", reason="crash")

    assert runner.call_count == EXPECTED_RUNNER_CALLS
    first_call, second_call = runner.call_args_list

    assert first_call.args[0] == ["git", "rev-parse", "HEAD~1"]
    assert first_call.kwargs["cwd"] == regions_root / "amygdala"
    assert first_call.kwargs["capture_output"] is True
    assert first_call.kwargs["text"] is True
    assert first_call.kwargs.get("check", False) is False

    assert second_call.args[0] == ["git", "revert", "--no-edit", "HEAD"]
    assert second_call.kwargs["cwd"] == regions_root / "amygdala"


# ---------------------------------------------------------------------------
# 11. two calls — no shared state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rollback_no_retry_single_attempt(
    launcher: MagicMock,
    publish: AsyncMock,
    regions_root: Path,
) -> None:
    # Each call is independent; there is no internal attempt counter.
    runner = _make_runner(
        _completed(returncode=0, stdout="abc\n"),
        _completed(returncode=0, stdout=""),
        _completed(returncode=0, stdout="def\n"),
        _completed(returncode=0, stdout=""),
    )
    rb = Rollback(
        launcher, publish=publish, regions_root=regions_root, runner=runner
    )

    r1 = await rb.rollback_region("amygdala", reason="first")
    r2 = await rb.rollback_region("amygdala", reason="second")

    assert r1.ok is True and r1.reverted_to == "abc"
    assert r2.ok is True and r2.reverted_to == "def"
    assert launcher.launch_region.call_count == EXPECTED_RELAUNCH_CALLS


# ---------------------------------------------------------------------------
# 12. RollbackResult is immutable dataclass
# ---------------------------------------------------------------------------


def test_rollback_result_is_frozen() -> None:
    r = RollbackResult(ok=True, reverted_to="abc")
    with pytest.raises((AttributeError, Exception)):
        r.ok = False  # type: ignore[misc]
