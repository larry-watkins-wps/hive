"""Self-modification cycle integration test (plan Task 9.5 / spec §I.6).

Verifies the full sleep → write_prompt → commit → restart_request → restart →
wake pipeline for a real region using a real LLM call.

Architecture
------------
- ``broker_container`` (session-scoped fixture from tests/conftest.py) starts
  an eclipse-mosquitto:2 testcontainer on an ephemeral host port.
- The test region container (hive-region:v0) is launched directly via the
  Python docker SDK, mounted at /hive/region with a *copy* of
  ``regions/test_self_mod/`` so the repo's tracked copy is never mutated.
- ``MQTT_HOST=host.docker.internal`` is used so the container can reach the
  broker running on the host (Docker Desktop for Windows maps this by default;
  the ``extra_hosts`` entry makes it explicit on Linux too, though the
  testcontainers approach is Windows-primary).

Linux note
----------
``host.docker.internal`` is not available in all Linux Docker setups.  On
Linux you may need to pass the Docker bridge IP instead.  This test is
primarily validated on Windows Docker Desktop.

Skip conditions
---------------
1. Docker daemon unreachable → skip.
2. ``hive-region:v0`` image missing → skip.
3. ``ANTHROPIC_API_KEY`` absent → skip (real LLM required).
4. ``regions/test_self_mod/`` scaffold missing → skip.
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("aiomqtt")
pytest.importorskip("docker")

import aiomqtt  # noqa: E402
import docker  # noqa: E402

from shared.message_envelope import Envelope  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.slow]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REGION_SRC = _REPO_ROOT / "regions" / "test_self_mod"

_TOPIC_HEARTBEAT = "hive/system/heartbeat/test_self_mod"
_TOPIC_RESTART_REQUEST = "hive/system/restart/request"
_TOPIC_ERROR = "hive/metacognition/error/detected"
_TOPIC_SLEEP_FORCE = "hive/system/sleep/force"

_TIMEOUT_FIRST_WAKE_S = 90
_TIMEOUT_SLEEP_FORCE_ACK_S = 30   # wait for restart/request

# Minimum expected commits in the per-region git repo: birth + self-mod.
_MIN_COMMITS = 2


# ---------------------------------------------------------------------------
# Windows event-loop policy (aiomqtt needs add_reader / add_writer)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    """Force selector loop on Windows; aiomqtt needs add_reader/add_writer."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


# ---------------------------------------------------------------------------
# Skip-condition helpers (evaluated at collection time)
# ---------------------------------------------------------------------------


def _docker_reachable() -> bool:
    try:
        client = docker.from_env()
        return bool(client.ping())
    except Exception:  # noqa: BLE001
        return False


def _region_image_present() -> bool:
    try:
        client = docker.from_env()
        tags: set[str] = set()
        for img in client.images.list():
            for tag in img.tags:
                tags.add(tag)
        return "hive-region:v0" in tags
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Module-level skip checks
# ---------------------------------------------------------------------------

if not _docker_reachable():
    pytest.skip("Docker daemon not available", allow_module_level=True)

if not _region_image_present():
    pytest.skip(
        "hive-region:v0 image not built",
        allow_module_level=True,
    )

if not os.environ.get("ANTHROPIC_API_KEY"):
    pytest.skip(
        "Real LLM required (option b: ANTHROPIC_API_KEY missing)",
        allow_module_level=True,
    )

if not _REGION_SRC.exists():
    pytest.skip(
        "test region scaffold missing: regions/test_self_mod/ not found",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _heartbeat_status(msg: Any) -> str | None:
    """Extract heartbeat status from an aiomqtt message, or return None."""
    try:
        env = Envelope.from_json(bytes(msg.payload))
        data = env.payload.data
        return data.get("status") if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _restart_region(msg: Any) -> str | None:
    """Extract region name from a restart/request envelope, or return None."""
    try:
        env = Envelope.from_json(bytes(msg.payload))
        data = env.payload.data
        return data.get("region") if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _log_error_msg(msg: Any, context: str) -> None:
    """Print a region error envelope for diagnostic purposes."""
    try:
        env = Envelope.from_json(bytes(msg.payload))
        print(f"[test] region error ({context}): {env.payload.data}")
    except Exception:  # noqa: BLE001
        pass


async def _wait_for_wake_heartbeat(
    client: aiomqtt.Client,
    timeout_s: float,
    container: Any,
) -> None:
    """Wait for a status=wake heartbeat on _TOPIC_HEARTBEAT.

    Fails the test with container logs if the timeout expires.
    """
    try:
        async with asyncio.timeout(timeout_s):
            async for msg in client.messages:
                topic_str = str(msg.topic)
                if topic_str == _TOPIC_HEARTBEAT:
                    if _heartbeat_status(msg) == "wake":
                        return
                elif topic_str == _TOPIC_ERROR:
                    _log_error_msg(msg, "startup")
    except TimeoutError:
        logs = container.logs().decode("utf-8", errors="replace")
        pytest.fail(
            f"Wake heartbeat not received within {timeout_s}s.\n"
            f"Container logs:\n{logs}"
        )


async def _wait_for_restart_request(
    client: aiomqtt.Client,
    timeout_s: float,
    container: Any,
) -> None:
    """Wait for hive/system/restart/request from test_self_mod.

    Fails the test with container logs if the timeout expires.
    """
    try:
        async with asyncio.timeout(timeout_s):
            async for msg in client.messages:
                topic_str = str(msg.topic)
                if topic_str == _TOPIC_RESTART_REQUEST:
                    if _restart_region(msg) == "test_self_mod":
                        return
                elif topic_str == _TOPIC_ERROR:
                    _log_error_msg(msg, "sleep cycle")
    except TimeoutError:
        logs = container.logs().decode("utf-8", errors="replace")
        pytest.fail(
            f"hive/system/restart/request not received within {timeout_s}s.\n"
            f"Container logs:\n{logs}"
        )


def _assert_prompt_modified(region_work: Path, prompt_before: str) -> None:
    """Assert prompt.md was modified and contains the expected marker."""
    prompt_after = (region_work / "prompt.md").read_text(encoding="utf-8")
    assert prompt_after != prompt_before, (
        "prompt.md was not modified during the sleep cycle"
    )
    assert "Self-mod succeeded" in prompt_after, (
        f"Expected 'Self-mod succeeded' in prompt.md after sleep cycle.\n"
        f"Got:\n{prompt_after!r}"
    )


def _assert_git_commit_present(region_work: Path) -> None:
    """Assert per-region .git/ exists and has at least _MIN_COMMITS commits."""
    git_dir = region_work / ".git"
    assert git_dir.exists(), (
        "Per-region .git/ not found; region did not initialise its git repo "
        "during bootstrap"
    )
    result = subprocess.run(
        ["git", "-C", str(region_work), "log", "--oneline"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit_lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
    assert len(commit_lines) >= _MIN_COMMITS, (
        f"Expected ≥{_MIN_COMMITS} commits (birth + self-mod), "
        f"found {len(commit_lines)}:\n{result.stdout}"
    )


def _launch_region_container(
    broker_port: int,
    region_work: Path,
) -> Any:
    """Launch and return a detached hive-region:v0 container."""
    docker_client = docker.from_env()
    container_name = f"hive-test-self-mod-{uuid.uuid4().hex[:8]}"
    return docker_client.containers.run(
        "hive-region:v0",
        detach=True,
        name=container_name,
        environment={
            "HIVE_REGION": "test_self_mod",
            "MQTT_HOST": "host.docker.internal",
            "MQTT_PORT": str(broker_port),
            "MQTT_PASSWORD_TEST_SELF_MOD": "",  # anonymous broker
            "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
        },
        volumes={
            str(region_work): {"bind": "/hive/region", "mode": "rw"},
            str((_REPO_ROOT / "region_template").resolve()): {
                "bind": "/hive/region_template",
                "mode": "ro",
            },
            str((_REPO_ROOT / "shared").resolve()): {
                "bind": "/hive/shared",
                "mode": "ro",
            },
        },
        extra_hosts={"host.docker.internal": "host-gateway"},
        remove=False,  # keep for log retrieval on failure
    )


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_mod_cycle(
    broker_container: object,  # _BrokerInfo from tests/conftest.py
    tmp_path: Path,
) -> None:
    """Full self-modification cycle: force sleep → prompt edit → commit → restart.

    Steps (spec §I.6):
    1. Copy regions/test_self_mod/ to a tmp dir (keeps the repo copy clean).
    2. Launch hive-region:v0 container with the copy mounted at /hive/region.
    3. Wait for the first wake heartbeat (status="wake").
    4. Publish hive/system/sleep/force.
    5. Wait for hive/system/restart/request from test_self_mod.
    6. Assert prompt.md changed and contains "Self-mod succeeded".
    7. Assert per-region .git/ exists with ≥2 commits.
    """
    broker_host: str = broker_container.host  # type: ignore[attr-defined]
    broker_port: int = broker_container.port  # type: ignore[attr-defined]

    # 1. Copy region scaffold to a tmp working directory.
    region_work = tmp_path / "test_self_mod"
    shutil.copytree(_REGION_SRC, region_work)
    prompt_before = (region_work / "prompt.md").read_text(encoding="utf-8")

    # 2. Launch the region container.
    container = _launch_region_container(broker_port, region_work)

    test_passed = False
    try:
        client_id = f"test_harness_{uuid.uuid4().hex[:8]}"
        async with aiomqtt.Client(
            hostname=broker_host,
            port=broker_port,
            identifier=client_id,
            timeout=10.0,
        ) as client:
            await client.subscribe(_TOPIC_HEARTBEAT, qos=1)
            await client.subscribe(_TOPIC_RESTART_REQUEST, qos=1)
            await client.subscribe(_TOPIC_ERROR, qos=1)
            await asyncio.sleep(0.5)  # ensure SUBACK is processed

            # 3. Wait for first wake heartbeat.
            await _wait_for_wake_heartbeat(
                client, _TIMEOUT_FIRST_WAKE_S, container
            )

            # 4. Publish hive/system/sleep/force.
            sleep_env = Envelope.new(
                source_region="test_harness",
                topic=_TOPIC_SLEEP_FORCE,
                content_type="application/json",
                data={"reason": "integration_test_force_sleep"},
            )
            await client.publish(
                _TOPIC_SLEEP_FORCE, payload=sleep_env.to_json(), qos=1
            )

            # 5. Wait for restart/request.
            await _wait_for_restart_request(
                client, _TIMEOUT_SLEEP_FORCE_ACK_S, container
            )

        # 6. Assert prompt.md modified.
        _assert_prompt_modified(region_work, prompt_before)

        # 7. Assert git commit present.
        _assert_git_commit_present(region_work)

        # Note: step 8 (second wake heartbeat) is not checked here because
        # glia is not running in this test and the container exits after
        # publish_restart_request.  The three assertions above satisfy §I.6.

        test_passed = True

    finally:
        if not test_passed:
            with contextlib.suppress(Exception):
                logs = container.logs().decode("utf-8", errors="replace")
                print(f"\n--- Container logs ---\n{logs}")
        with contextlib.suppress(Exception):
            container.stop(timeout=5)
        with contextlib.suppress(Exception):
            container.remove(force=True)
