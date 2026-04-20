"""Unit tests for glia.codechange_executor — Task 5.7.

Covers spec §E.10 happy path + rejection + rollback paths.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from glia.codechange_executor import (
    CodeChangeExecutor,
    CodeChangeResult,
)
from glia.launcher import GliaError, Launcher
from glia.registry import RegionRegistry
from shared.message_envelope import Envelope
from shared.topics import (
    METACOGNITION_ERROR_DETECTED,
    SYSTEM_CODECHANGE_APPROVED,
)

# Named constants to keep ruff PLR2004 quiet.
EXPECTED_ACTIVE_REGION_COUNT = 14
MIN_RESTART_SLEEP_CALLS_TWO_REGIONS = 1
EXPECTED_RESTART_CALLS_TWO = 2
MIN_ARGV_LEN_WITH_FLAG = 3  # ["git", "apply", "--check"] minimum len
STAGGER_EPSILON = 1e-6


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _completed(
    returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class _RunnerRecorder:
    """Subprocess runner that matches args against a dispatch table.

    Dispatch keys are tuples — the first N elements of the invoked argv.
    Any unrecognised call raises AssertionError so tests fail loudly on
    unexpected subprocess invocations.
    """

    def __init__(self, dispatch: dict[tuple[str, ...], subprocess.CompletedProcess[str]]) -> None:
        self._dispatch = dispatch
        self.calls: list[Any] = []

    def __call__(self, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        argv = tuple(args[0]) if args else ()
        self.calls.append({"args": args, "kwargs": kwargs})
        # Longer key prefixes win (so "git apply --check" matches before "git apply").
        for key in sorted(self._dispatch, key=len, reverse=True):
            if argv[: len(key)] == key:
                return self._dispatch[key]
        raise AssertionError(f"unexpected runner invocation: argv={argv}")


def _default_runner() -> _RunnerRecorder:
    """Runner that green-lights every git operation used by the executor."""
    return _RunnerRecorder(
        {
            ("git", "apply", "--check"): _completed(returncode=0),
            ("git", "apply"): _completed(returncode=0),
            ("git", "checkout"): _completed(returncode=0),
        }
    )


@pytest.fixture
def mock_launcher() -> MagicMock:
    lm = MagicMock(spec=Launcher)
    lm.restart_region = MagicMock(return_value=MagicMock())
    return lm


@pytest.fixture
def registry() -> RegionRegistry:
    return RegionRegistry.load()


@pytest.fixture
def publish() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def mock_docker_client() -> MagicMock:
    client = MagicMock()
    client.images.build.return_value = (MagicMock(), iter([]))
    client.api.tag.return_value = None
    return client


@pytest.fixture
def repo_dirs(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path
    region_template = repo_root / "region_template"
    region_template.mkdir()
    return repo_root, region_template


def _make_executor(
    *,
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
    runner: _RunnerRecorder | None = None,
    cosign_result: bool = True,
) -> CodeChangeExecutor:
    repo_root, region_template = repo_dirs
    return CodeChangeExecutor(
        mock_launcher,
        registry,
        publish=publish,
        cosign_verifier=lambda _p, _s: cosign_result,
        docker_client=mock_docker_client,
        region_template_dir=region_template,
        repo_root=repo_root,
        runner=runner if runner is not None else _default_runner(),
        restart_stagger_s=0.0,
    )


def _envelope(data: dict[str, Any]) -> Envelope:
    return Envelope.new(
        source_region="anterior_cingulate",
        topic=SYSTEM_CODECHANGE_APPROVED,
        content_type="application/hive+code-change-proposal",
        data=data,
    )


def _valid_payload(affected: list[str] | None = None) -> dict[str, Any]:
    return {
        "change_id": "11111111-2222-3333-4444-555555555555",
        "patch": "--- a/foo\n+++ b/foo\n@@ -1 +1 @@\n-a\n+b\n",
        "approver_region": "anterior_cingulate",
        "human_cosigner": "alice@example.com",
        "cosign_signature": "BASE64SIG",
        "justification": "tune threshold",
        "affected_regions": affected if affected is not None else ["*"],
    }


# ---------------------------------------------------------------------------
# 1. missing patch field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_patch_field_rejects(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
    )
    data = _valid_payload()
    data.pop("patch")

    result = await ex.apply_change(_envelope(data))

    assert result.ok is False
    assert result.reason is not None
    assert "missing_field" in result.reason
    assert "patch" in result.reason
    publish.assert_awaited_once()
    env = publish.await_args.args[0]
    assert env.payload.data["kind"] == "codechange_rejected"
    mock_launcher.restart_region.assert_not_called()


# ---------------------------------------------------------------------------
# 2. missing change_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_change_id_rejects(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
    )
    data = _valid_payload()
    data.pop("change_id")

    result = await ex.apply_change(_envelope(data))

    assert result.ok is False
    assert result.reason is not None
    assert "missing_field" in result.reason
    assert "change_id" in result.reason


# ---------------------------------------------------------------------------
# 3. missing signature
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_signature_rejects(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
    )
    data = _valid_payload()
    data.pop("cosign_signature")

    result = await ex.apply_change(_envelope(data))

    assert result.ok is False
    assert "missing_field" in (result.reason or "")
    assert "cosign_signature" in (result.reason or "")
    publish.assert_awaited_once()


# ---------------------------------------------------------------------------
# 4. invalid cosign
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalid_cosign_rejects(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
        cosign_result=False,
    )
    result = await ex.apply_change(_envelope(_valid_payload()))

    assert result.ok is False
    assert result.reason == "invalid_cosign"
    publish.assert_awaited_once()
    env = publish.await_args.args[0]
    assert env.payload.data["kind"] == "codechange_rejected"
    assert env.payload.data["context"]["reason"] == "invalid_cosign"
    mock_launcher.restart_region.assert_not_called()
    mock_docker_client.images.build.assert_not_called()


# ---------------------------------------------------------------------------
# 5. malformed patch (git apply --check fails)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_malformed_patch_rejects(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    runner = _RunnerRecorder(
        {
            ("git", "apply", "--check"): _completed(returncode=1, stderr="bad"),
        }
    )
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
        runner=runner,
    )
    result = await ex.apply_change(_envelope(_valid_payload()))

    assert result.ok is False
    assert result.reason == "malformed_patch"
    # Only the --check call should have been made — no real apply.
    dry_run_calls = [
        c for c in runner.calls if c["args"][0][:3] == ["git", "apply", "--check"]
    ]
    real_apply_calls = [
        c for c in runner.calls
        if c["args"][0][:2] == ["git", "apply"]
        and (
            len(c["args"][0]) < MIN_ARGV_LEN_WITH_FLAG
            or c["args"][0][2] != "--check"
        )
    ]
    assert len(dry_run_calls) == 1
    assert real_apply_calls == []
    mock_docker_client.images.build.assert_not_called()
    mock_launcher.restart_region.assert_not_called()
    publish.assert_awaited_once()
    env = publish.await_args.args[0]
    assert env.payload.data["kind"] == "codechange_rejected"


# ---------------------------------------------------------------------------
# 6. happy path — restart all active regions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_restart_all_regions(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
    )
    result = await ex.apply_change(_envelope(_valid_payload(["*"])))

    assert result.ok is True
    assert mock_launcher.restart_region.call_count == len(registry.active())
    mock_docker_client.images.build.assert_called_once()
    mock_docker_client.api.tag.assert_called()  # previous tag

    # Final publish is codechange_complete, published to metacog.
    complete_calls = [
        c for c in publish.await_args_list
        if c.args[0].payload.data.get("kind") == "codechange_complete"
    ]
    assert len(complete_calls) == 1
    env = complete_calls[0].args[0]
    assert env.topic == METACOGNITION_ERROR_DETECTED
    assert env.payload.data["context"]["change_id"] == _valid_payload()["change_id"]


# ---------------------------------------------------------------------------
# 7. wildcard "*" expands to registry.active()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_affected_regions_star_expands_to_registry_active(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
    )
    await ex.apply_change(_envelope(_valid_payload(["*"])))

    assert mock_launcher.restart_region.call_count == EXPECTED_ACTIVE_REGION_COUNT
    called_names = [c.args[0] for c in mock_launcher.restart_region.call_args_list]
    active_names = [e.name for e in registry.active()]
    assert called_names == active_names


# ---------------------------------------------------------------------------
# 8. specific list of affected regions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_specific_affected_regions_list(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
    )
    await ex.apply_change(_envelope(_valid_payload(["amygdala", "hippocampus"])))

    assert mock_launcher.restart_region.call_count == EXPECTED_RESTART_CALLS_TWO
    names = [c.args[0] for c in mock_launcher.restart_region.call_args_list]
    assert names == ["amygdala", "hippocampus"]


# ---------------------------------------------------------------------------
# 9. build failure triggers patch revert + rollback event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_failure_triggers_patch_revert_and_rollback_event(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    runner = _default_runner()
    mock_docker_client.images.build.side_effect = RuntimeError("build broke")

    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
        runner=runner,
    )
    result = await ex.apply_change(_envelope(_valid_payload(["amygdala"])))

    assert result.ok is False
    # git checkout . was called on region_template to revert.
    checkout_calls = [
        c for c in runner.calls
        if c["args"][0][:2] == ["git", "checkout"]
    ]
    assert len(checkout_calls) >= 1
    mock_launcher.restart_region.assert_not_called()
    # published rollback event
    rollback_calls = [
        c for c in publish.await_args_list
        if c.args[0].payload.data.get("kind") == "codechange_rollback"
    ]
    assert len(rollback_calls) == 1
    env = rollback_calls[0].args[0]
    assert env.payload.data["context"]["reason"] == "build_failed"


# ---------------------------------------------------------------------------
# 10. restart failure triggers image rollback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_failure_triggers_image_rollback(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    affected = ["amygdala", "hippocampus", "thalamus", "insula"]

    # Third call raises; subsequent calls during rollback-relaunch succeed.
    call_count = {"n": 0}

    def side(_name: str) -> Any:
        call_count["n"] += 1
        if call_count["n"] == 3:  # noqa: PLR2004
            raise GliaError("launch boom")
        return MagicMock()

    mock_launcher.restart_region.side_effect = side

    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
    )
    result = await ex.apply_change(_envelope(_valid_payload(affected)))

    assert result.ok is False
    # docker.api.tag was called at least twice: initial prev tag + rollback tag.
    tag_calls = mock_docker_client.api.tag.call_args_list
    # Look for a call restoring -prev to :v0.
    restores = [
        c for c in tag_calls
        if "v0-prev" in " ".join(str(a) for a in c.args)
        and c != tag_calls[0]
    ]
    assert len(restores) >= 1
    # rollback event published
    rollback_calls = [
        c for c in publish.await_args_list
        if c.args[0].payload.data.get("kind") == "codechange_rollback"
    ]
    assert len(rollback_calls) == 1


# ---------------------------------------------------------------------------
# 10b. rollback relaunches ALL affected regions (spec §E.10 step 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_restart_failure_rollback_relaunches_all_affected(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    """Restart fails at index 2 of 5 regions; rollback must bounce ALL 5.

    Call accounting:
      - initial attempt restarts region 0 (1 call), region 1 (2 calls), then
        region 2 raises (3 calls)
      - rollback relaunches all 5 regions (3 + 5 = 8 calls)
    """
    affected = ["amygdala", "hippocampus", "thalamus", "insula", "cerebellum"]
    n_affected = 5
    fail_at_call = 3  # 1-based
    expected_total = fail_at_call + n_affected  # 3 + 5 = 8

    call_count = {"n": 0}

    def side(_name: str) -> Any:
        call_count["n"] += 1
        if call_count["n"] == fail_at_call:
            raise GliaError("boom at index 2")
        return MagicMock()

    mock_launcher.restart_region.side_effect = side

    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
    )
    result = await ex.apply_change(_envelope(_valid_payload(affected)))

    assert result.ok is False
    assert mock_launcher.restart_region.call_count == expected_total

    names_called = [c.args[0] for c in mock_launcher.restart_region.call_args_list]
    # First 3 calls: initial restart attempts 0, 1, 2 (2 fails).
    assert names_called[:fail_at_call] == affected[:fail_at_call]
    # Next 5 calls: rollback relaunches ALL of 0..4, not just the failed tail.
    assert names_called[fail_at_call:] == affected

    # Rollback event published.
    rollback_calls = [
        c for c in publish.await_args_list
        if c.args[0].payload.data.get("kind") == "codechange_rollback"
    ]
    assert len(rollback_calls) == 1


# ---------------------------------------------------------------------------
# 11. dry-run subprocess args
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_subprocess_args(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    runner = _default_runner()
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
        runner=runner,
    )
    await ex.apply_change(_envelope(_valid_payload(["amygdala"])))

    dry_run_calls = [
        c for c in runner.calls if c["args"][0][:3] == ["git", "apply", "--check"]
    ]
    assert len(dry_run_calls) == 1
    call = dry_run_calls[0]
    argv = call["args"][0]
    assert argv == ["git", "apply", "--check", "-"]
    # patch text on stdin
    assert call["kwargs"].get("input") == _valid_payload()["patch"]


# ---------------------------------------------------------------------------
# 12. real-apply subprocess args
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_subprocess_args(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    runner = _default_runner()
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
        runner=runner,
    )
    await ex.apply_change(_envelope(_valid_payload(["amygdala"])))

    real_apply = [
        c for c in runner.calls
        if c["args"][0][:2] == ["git", "apply"]
        and "--check" not in c["args"][0]
    ]
    assert len(real_apply) == 1
    argv = real_apply[0]["args"][0]
    assert argv == ["git", "apply", "-"]


# ---------------------------------------------------------------------------
# 13. stagger between restarts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stagger_between_restarts(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    repo_root, region_template = repo_dirs
    ex = CodeChangeExecutor(
        mock_launcher,
        registry,
        publish=publish,
        cosign_verifier=lambda _p, _s: True,
        docker_client=mock_docker_client,
        region_template_dir=region_template,
        repo_root=repo_root,
        runner=_default_runner(),
        restart_stagger_s=0.01,
    )

    sleep_calls: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleep_calls.append(d)

    with patch("glia.codechange_executor.asyncio.sleep", new=fake_sleep):
        await ex.apply_change(_envelope(_valid_payload(["amygdala", "hippocampus"])))

    # Between the two restarts we expect at least one stagger sleep.
    assert any(abs(d - 0.01) < STAGGER_EPSILON for d in sleep_calls)


# ---------------------------------------------------------------------------
# 14. default cosign verifier without pubkey returns False
# ---------------------------------------------------------------------------


def test_default_cosign_verifier_without_pubkey_returns_false() -> None:
    env_clean = {
        k: v for k, v in os.environ.items()
        if k not in {"HIVE_HUMAN_COSIGN_PUBKEY_PATH", "HIVE_HUMAN_COSIGN_PUBKEY"}
    }
    with patch.dict(os.environ, env_clean, clear=True):
        assert CodeChangeExecutor._default_cosign_verifier("patch", "sig") is False


# ---------------------------------------------------------------------------
# 15. metacog envelope shape on rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metacog_envelope_shape(
    mock_launcher: MagicMock,
    registry: RegionRegistry,
    publish: AsyncMock,
    mock_docker_client: MagicMock,
    repo_dirs: tuple[Path, Path],
) -> None:
    ex = _make_executor(
        mock_launcher=mock_launcher,
        registry=registry,
        publish=publish,
        mock_docker_client=mock_docker_client,
        repo_dirs=repo_dirs,
        cosign_result=False,
    )
    await ex.apply_change(_envelope(_valid_payload()))

    publish.assert_awaited_once()
    env = publish.await_args.args[0]
    assert env.topic == METACOGNITION_ERROR_DETECTED
    assert env.source_region == "glia"
    assert env.payload.content_type == "application/json"
    data = env.payload.data
    assert data["kind"] == "codechange_rejected"
    assert data["context"]["change_id"] == _valid_payload()["change_id"]


# ---------------------------------------------------------------------------
# 16. CodeChangeResult frozen
# ---------------------------------------------------------------------------


def test_code_change_result_is_frozen() -> None:
    r = CodeChangeResult(ok=True, change_id="abc")
    with pytest.raises((AttributeError, Exception)):
        r.ok = False  # type: ignore[misc]
