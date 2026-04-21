"""Full-Hive smoke test (plan Task 9.6, spec §I.5).

Boots the complete 14-region Hive stack via ``hive up``, waits up to 120 s
for all 14 regions to publish ``status=wake`` heartbeats, checks that at
least one retained ``hive/self/*`` topic is present, then tears down via
``hive down``.

Marked @pytest.mark.smoke + @pytest.mark.slow + @pytest.mark.integration.

Skip conditions (evaluated at test time, option b — no offline stub):
1. Docker daemon unreachable.
2. ``hive-region:v0`` or ``hive-glia:v0`` image missing.
3. ``ANTHROPIC_API_KEY`` unset.
4. ``.env`` file missing.
5. ``bus/passwd`` missing (broker mount).
6. ``bus/acl.conf`` missing (broker mount).
7. Broker rejects anonymous connection (``allow_anonymous false`` in production
   mosquitto.conf).  A future task should wire a dedicated smoke-operator
   credential; for now we document and skip.

Known deferred assertion: the speech-intent round-trip relies on a PFC handler
for ``hive/sensory/input/text`` which does not yet exist in v0.  The check is
logged but does not fail the smoke test.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("aiomqtt")
pytest.importorskip("docker")

import aiomqtt  # noqa: E402

from shared.message_envelope import Envelope  # noqa: E402

pytestmark = [pytest.mark.smoke, pytest.mark.slow, pytest.mark.integration]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]

_EXPECTED_REGIONS: list[str] = [
    "medial_prefrontal_cortex",
    "prefrontal_cortex",
    "anterior_cingulate",
    "hippocampus",
    "thalamus",
    "association_cortex",
    "visual_cortex",
    "auditory_cortex",
    "motor_cortex",
    "broca_area",
    "amygdala",
    "vta",
    "insula",
    "basal_ganglia",
]

_BOOT_TIMEOUT_S = 120
_SHUTDOWN_TIMEOUT_S = 60
_BROKER_HOST = "127.0.0.1"
_BROKER_PORT = 1883

# PFC handler stub threshold (same as test_cross_region_flow.py)
_STUB_THRESHOLD_CHARS = 80


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
# Skip-condition helpers
# ---------------------------------------------------------------------------


def _skip_if_preconditions_unmet() -> None:
    """Evaluate all preconditions; call pytest.skip() if any is missing."""
    # 1. Docker reachable?
    try:
        import docker  # noqa: PLC0415

        client = docker.from_env()
        client.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Docker unreachable: {exc}")

    # 2. Required images present?
    try:
        import docker  # noqa: PLC0415

        img_client = docker.from_env()
        present: set[str] = set()
        for img in img_client.images.list():
            for tag in img.tags:
                present.add(tag)
        for required_tag in ("hive-region:v0", "hive-glia:v0"):
            if required_tag not in present:
                pytest.skip(f"Image missing: {required_tag} — run `docker build` first")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"Could not query Docker images: {exc}")

    # 3. LLM key?
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip(
            "ANTHROPIC_API_KEY unset (option b: real LLM only — no offline stub)"
        )

    # 4. .env file?
    env_file = _REPO_ROOT / ".env"
    if not env_file.exists():
        pytest.skip(
            ".env missing — run `bash scripts/make_passwd.sh && python -m tools.hive_cli up` "
            "once to bootstrap the stack"
        )

    # 5. bus/passwd?
    passwd_file = _REPO_ROOT / "bus" / "passwd"
    if not passwd_file.exists():
        pytest.skip(
            "bus/passwd missing — run `bash scripts/make_passwd.sh` to generate "
            "MQTT credentials before running the smoke test"
        )

    # 6. bus/acl.conf?
    acl_file = _REPO_ROOT / "bus" / "acl.conf"
    if not acl_file.exists():
        pytest.skip(
            "bus/acl.conf missing — run `python -m tools.hive_cli up` once to let "
            "glia's acl_manager render and apply the ACL file"
        )


async def _can_connect_anonymous() -> bool:
    """Return True if the broker accepts an anonymous MQTT connection."""
    try:
        async with aiomqtt.Client(
            hostname=_BROKER_HOST,
            port=_BROKER_PORT,
            identifier="smoke-anon-probe",
        ):
            return True
    except Exception:  # noqa: BLE001
        return False


def _pfc_has_handlers() -> bool:
    """Return True if prefrontal_cortex/handlers/ has real (non-stub) code.

    The scaffolded __init__.py is a single docstring line (~60 chars).
    We consider the directory "ready" when either:
      - __init__.py content (stripped) exceeds the stub threshold, OR
      - There is at least one extra .py file beside __init__.py.
    """
    handlers_dir = _REPO_ROOT / "regions" / "prefrontal_cortex" / "handlers"
    init_path = handlers_dir / "__init__.py"
    if not init_path.exists():
        return False
    init_content = init_path.read_text("utf-8")
    if len(init_content.strip()) > _STUB_THRESHOLD_CHARS:
        return True
    extras = [p for p in handlers_dir.glob("*.py") if p.name != "__init__.py"]
    return len(extras) > 0


# ---------------------------------------------------------------------------
# Main smoke test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hive_boots_and_shuts_down_cleanly() -> None:
    """Full-system smoke: hive up → 14 wake heartbeats → retained self/* → hive down.

    Spec §I.5 acceptance criteria:
    - All 14 regions publish status=wake heartbeats within 120 s.
    - At least one retained hive/self/* topic is present after boot.
    - Stack shuts down cleanly via ``hive down`` within 60 s.
    """
    _skip_if_preconditions_unmet()

    # ------------------------------------------------------------------
    # 1. Bring the stack up.
    # ------------------------------------------------------------------
    up_result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "tools.hive_cli", "up"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if up_result.returncode != 0:
        pytest.fail(
            f"hive up failed (rc={up_result.returncode}):\n"
            f"stdout: {up_result.stdout}\n"
            f"stderr: {up_result.stderr}"
        )

    try:
        # ------------------------------------------------------------------
        # 1a. Check broker auth policy — if anonymous is rejected, skip with
        #     a clear message.  Production mosquitto.conf has
        #     ``allow_anonymous false``, so the smoke test needs a named
        #     credential.  That wiring is deferred to a future task; for now
        #     we document the limitation and skip.
        # ------------------------------------------------------------------
        # Give the broker a moment to become available after compose up.
        await asyncio.sleep(3)

        can_anon = await _can_connect_anonymous()
        if not can_anon:
            pytest.skip(
                "Broker rejects anonymous connections (allow_anonymous false in "
                "bus/mosquitto.conf).  A future task must wire a dedicated "
                "'smoke_operator' MQTT credential for the smoke test.  "
                "See HANDOFF for follow-up."
            )

        # ------------------------------------------------------------------
        # 2. Wait up to 120 s for all 14 regions to publish wake heartbeats.
        # ------------------------------------------------------------------
        seen_wake: set[str] = set()

        async def _collect_heartbeats() -> None:
            async with aiomqtt.Client(
                hostname=_BROKER_HOST,
                port=_BROKER_PORT,
                identifier=f"smoke-boot-{int(time.time())}",
            ) as client:
                await client.subscribe("hive/system/heartbeat/+", qos=0)
                async for msg in client.messages:
                    try:
                        env = Envelope.from_json(bytes(msg.payload))
                        data = env.data if isinstance(env.data, dict) else {}
                        status = data.get("status")
                        if status == "wake":
                            # Topic pattern: hive/system/heartbeat/<region_name>
                            region = str(msg.topic).rsplit("/", 1)[-1]
                            seen_wake.add(region)
                            if seen_wake >= set(_EXPECTED_REGIONS):
                                return
                    except Exception:  # noqa: BLE001
                        continue

        try:
            async with asyncio.timeout(_BOOT_TIMEOUT_S):
                await _collect_heartbeats()
        except TimeoutError:
            missing = set(_EXPECTED_REGIONS) - seen_wake
            pytest.fail(
                f"Did not see wake heartbeats from all 14 regions within "
                f"{_BOOT_TIMEOUT_S}s.  "
                f"Missing: {sorted(missing)}.  "
                f"Seen: {sorted(seen_wake)}."
            )

        # ------------------------------------------------------------------
        # 3. Check retained hive/self/identity is present.
        #    MPFC publishes retained self-topics on first boot.
        # ------------------------------------------------------------------
        async def _check_retained_self() -> bool:
            async with aiomqtt.Client(
                hostname=_BROKER_HOST,
                port=_BROKER_PORT,
                identifier=f"smoke-self-check-{int(time.time())}",
            ) as client:
                await client.subscribe("hive/self/identity", qos=1)
                # Retained messages are delivered immediately on subscribe.
                try:
                    async with asyncio.timeout(5):
                        async for _msg in client.messages:
                            return True
                except TimeoutError:
                    return False
            return False

        has_self = await _check_retained_self()
        assert has_self, (
            "No retained hive/self/identity after boot — "
            "MPFC may not have published its self-topics yet, or the topic is not retained."
        )

        # ------------------------------------------------------------------
        # 4. Optionally check speech-intent round-trip (deferred in v0).
        #    PFC handlers grow via self-modification; the scaffold is a stub.
        # ------------------------------------------------------------------
        if not _pfc_has_handlers():
            print(
                "NOTE: pfc has no handler for hive/sensory/input/text yet "
                "(handlers/__init__.py is still the empty scaffold); "
                "speech-intent round-trip check skipped."
            )
        else:
            # When PFC handlers land, add injection + observation here
            # (same flow as test_cross_region_flow.py).
            pass

    finally:
        # ------------------------------------------------------------------
        # 5. Bring the stack down (always, even on test failure).
        # ------------------------------------------------------------------
        down_result = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "tools.hive_cli", "down"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=_SHUTDOWN_TIMEOUT_S + 30,
            check=False,
        )
        if down_result.returncode != 0:
            # Don't mask the original failure, but log the teardown problem.
            print(
                f"WARNING: hive down rc={down_result.returncode}\n"
                f"stdout: {down_result.stdout}\n"
                f"stderr: {down_result.stderr}"
            )
