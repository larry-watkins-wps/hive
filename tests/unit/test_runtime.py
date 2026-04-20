"""Tests for :mod:`region_template.runtime` — spec §A.3, §A.4.

Exercises :class:`RegionRuntime` via :class:`FakeMqttClient` +
:class:`FakeLlmAdapter`. Real :class:`MemoryStore` + :class:`GitTools` on
``tmp_path``. Configs are built directly as :class:`RegionConfig` (no YAML
round-trip) and injected via the test-only ``from_config`` classmethod.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path
from typing import Any

import pytest

from region_template.config_loader import (
    DispatchConfig,
    LifecycleConfig,
    LlmBudgets,
    LlmCaching,
    LlmConfig,
    LlmRetry,
    LoggingConfig,
    MemoryConfig,
    MqttConfig,
    RegionConfig,
)
from region_template.errors import ConfigError
from region_template.llm_adapter import CompletionResult
from region_template.runtime import RegionRuntime
from region_template.self_modify import SpawnProposal, SubscriptionEntry
from region_template.sleep import SleepResult
from region_template.token_ledger import TokenUsage
from region_template.types import CapabilityProfile, LifecyclePhase
from shared.message_envelope import Envelope
from shared.topics import (
    METACOGNITION_ERROR_DETECTED,
    SYSTEM_RESTART_REQUEST,
    SYSTEM_SLEEP_GRANTED,
    SYSTEM_SLEEP_REQUEST,
    SYSTEM_SPAWN_COMPLETE,
    fill,
)
from tests.fakes.llm import FakeLlmAdapter
from tests.fakes.mqtt import FakeMqttClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_config(
    *,
    name: str = "test_region",
    self_modify: bool = True,
    can_spawn: bool = False,
    heartbeat_interval_s: int = 1,
    sleep_quiet_window_s: int = 60,
    sleep_max_wake_s: int = 3600,
    handler_concurrency_limit: int = 4,
    provider: str = "anthropic",
) -> RegionConfig:
    """Build a RegionConfig directly — no YAML round-trip."""
    return RegionConfig(
        schema_version=1,
        name=name,
        role="a test region used exclusively for runtime integration tests",
        llm=LlmConfig(
            provider=provider,
            model="claude-3-5-sonnet-20241022",
            params={},
            budgets=LlmBudgets(),
            retry=LlmRetry(),
            caching=LlmCaching(),
        ),
        capabilities=CapabilityProfile(
            self_modify=self_modify,
            tool_use="basic",
            vision=False,
            audio=False,
            stream=False,
            can_spawn=can_spawn,
            modalities=["text"],
        ),
        lifecycle=LifecycleConfig(
            heartbeat_interval_s=heartbeat_interval_s,
            sleep_quiet_window_s=sleep_quiet_window_s,
            sleep_max_wake_s=sleep_max_wake_s,
            shutdown_timeout_s=5,
        ),
        memory=MemoryConfig(),
        dispatch=DispatchConfig(
            handler_concurrency_limit=handler_concurrency_limit,
            handler_default_timeout_s=1.0,
        ),
        mqtt=MqttConfig(),
        logging=LoggingConfig(),
    )


def _build_region_root(tmp_path: Path, region_name: str = "test_region") -> Path:
    """Create a minimal region directory layout on disk. Idempotent."""
    root = tmp_path / "regions" / region_name
    root.mkdir(parents=True, exist_ok=True)
    prompt = root / "prompt.md"
    if not prompt.exists():
        prompt.write_text("seed\n", encoding="utf-8")
    (root / "handlers").mkdir(exist_ok=True)
    return root


def _empty_review_response() -> CompletionResult:
    """A scripted LLM reply that triggers 'no_change' in SleepCoordinator."""
    payload = {
        "ltm_candidates": [],
        "prune_keys": [],
        "prompt_edit": None,
        "handler_edits": [],
        "needs_restart": False,
        "reason": "nothing to consolidate",
    }
    return CompletionResult(
        text=json.dumps(payload),
        tool_calls=(),
        finish_reason="stop",
        usage=TokenUsage(0, 0, 0, 0),
        model="fake",
        cached_prefix_tokens=0,
        elapsed_ms=1,
    )


async def _build_runtime(
    tmp_path: Path,
    *,
    config: RegionConfig | None = None,
    fake_mqtt: FakeMqttClient | None = None,
    fake_llm: FakeLlmAdapter | None = None,
    region_name: str = "test_region",
) -> Any:
    """Construct a RegionRuntime via the test-only from_config path."""
    cfg = config or _build_config(name=region_name)
    region_root = _build_region_root(tmp_path, region_name=region_name)
    mqtt = fake_mqtt or FakeMqttClient(region_name=region_name)
    llm = fake_llm or FakeLlmAdapter(
        scripted_responses=[_empty_review_response()],
    )
    runtime = RegionRuntime.from_config(
        config=cfg,
        region_root=region_root,
        mqtt_client=mqtt,
        llm_adapter=llm,
    )
    return runtime


# ---------------------------------------------------------------------------
# 1. Bootstrap happy path
# ---------------------------------------------------------------------------


async def test_bootstrap_transitions_to_wake(tmp_path: Path) -> None:
    """BOOTSTRAP → WAKE; mqtt entered; boot + wake heartbeats published."""
    mqtt = FakeMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)

    assert runtime.phase == LifecyclePhase.BOOTSTRAP

    await runtime.bootstrap()

    try:
        assert runtime.phase == LifecyclePhase.WAKE
        assert mqtt._entered is True
        # Heartbeat topic = hive/system/heartbeat/test_region
        hb_topic = fill("hive/system/heartbeat/{region}", region="test_region")
        hb_published = [
            (topic, env)
            for topic, env, _, _ in mqtt.published
            if topic == hb_topic
        ]
        # At least one boot heartbeat and one wake heartbeat.
        statuses = [
            env.payload.data.get("status") for _, env in hb_published
        ]
        assert "boot" in statuses
        assert "wake" in statuses
    finally:
        await runtime.shutdown("test_done")


# ---------------------------------------------------------------------------
# 2. Bootstrap fails on missing API key
# ---------------------------------------------------------------------------


async def test_bootstrap_raises_config_error_on_missing_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing ANTHROPIC_API_KEY → ConfigError at bootstrap."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cfg = _build_config(provider="anthropic")
    region_root = _build_region_root(tmp_path)
    mqtt = FakeMqttClient(region_name="test_region")

    # Don't preinject llm; let the runtime try to construct a real LlmAdapter,
    # which calls validate_provider_env → raises ConfigError.
    runtime = RegionRuntime.from_config(
        config=cfg,
        region_root=region_root,
        mqtt_client=mqtt,
        # No llm_adapter kwarg → real construction
    )

    with pytest.raises(ConfigError):
        await runtime.bootstrap()


# ---------------------------------------------------------------------------
# 3. Shutdown idempotent
# ---------------------------------------------------------------------------


async def test_shutdown_is_idempotent(tmp_path: Path) -> None:
    """Calling shutdown twice only runs the teardown once."""
    mqtt = FakeMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    await runtime.bootstrap()

    await runtime.shutdown("first")
    count_after_first = len(mqtt.published)
    await runtime.shutdown("second")
    count_after_second = len(mqtt.published)

    assert count_after_first == count_after_second
    assert runtime.phase == LifecyclePhase.SHUTDOWN


# ---------------------------------------------------------------------------
# 4. Shutdown clean disconnect (MQTT __aexit__ called)
# ---------------------------------------------------------------------------


async def test_shutdown_cleanly_disconnects_mqtt(tmp_path: Path) -> None:
    mqtt = FakeMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    await runtime.bootstrap()
    assert mqtt._entered is True

    await runtime.shutdown("planned")

    # _entered is set False on __aexit__.
    assert mqtt._entered is False


# ---------------------------------------------------------------------------
# 5. Handler dispatch
# ---------------------------------------------------------------------------


async def test_handler_dispatched_on_matching_topic(tmp_path: Path) -> None:
    """Inject an envelope on a subscribed topic → handler.handle called."""
    mqtt = FakeMqttClient(region_name="test_region")
    region_root = _build_region_root(tmp_path)

    # Write a handler that records calls into a module-global list.
    handler_file = region_root / "handlers" / "on_test.py"
    handler_file.write_text(
        'SUBSCRIPTIONS = ["hive/test/topic"]\n'
        "TIMEOUT_S = 5.0\n"
        "\n"
        "calls = []\n"
        "\n"
        "async def handle(envelope, ctx):\n"
        "    calls.append(envelope.id)\n",
        encoding="utf-8",
    )

    cfg = _build_config()
    runtime = await _build_runtime(
        tmp_path,
        config=cfg,
        fake_mqtt=mqtt,
    )
    await runtime.bootstrap()

    # Now inject a matching envelope via fake mqtt. The runtime must have
    # subscribed to the handler's topics during bootstrap.
    env = Envelope.new(
        source_region="other_region",
        topic="hive/test/topic",
        content_type="application/json",
        data={"hello": "world"},
    )
    try:
        await mqtt.inject("hive/test/topic", env)
        # Give async dispatch a moment
        await asyncio.sleep(0)

        handler_module = runtime._handlers[0]
        handler_py = __import__(
            handler_module.handle.__module__, fromlist=["calls"]
        )
        assert env.id in handler_py.calls
    finally:
        await runtime.shutdown("test_done")


# ---------------------------------------------------------------------------
# 6. Handler crash → metacog error, region keeps running
# ---------------------------------------------------------------------------


async def test_handler_crash_publishes_metacog_error(tmp_path: Path) -> None:
    mqtt = FakeMqttClient(region_name="test_region")
    region_root = _build_region_root(tmp_path)

    handler_file = region_root / "handlers" / "on_crash.py"
    handler_file.write_text(
        'SUBSCRIPTIONS = ["hive/test/crash"]\n'
        "TIMEOUT_S = 5.0\n"
        "\n"
        "async def handle(envelope, ctx):\n"
        "    raise RuntimeError('boom')\n",
        encoding="utf-8",
    )

    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    await runtime.bootstrap()

    env = Envelope.new(
        source_region="other_region",
        topic="hive/test/crash",
        content_type="application/json",
        data={},
    )
    try:
        await mqtt.inject("hive/test/crash", env)
        await asyncio.sleep(0.05)

        metacog = [
            (topic, e)
            for topic, e, _, _ in mqtt.published
            if topic == METACOGNITION_ERROR_DETECTED
        ]
        assert any(
            e.payload.data.get("kind") == "handler_crash" for _, e in metacog
        )
        # Region still runs.
        assert runtime.phase == LifecyclePhase.WAKE
    finally:
        await runtime.shutdown("test_done")


# ---------------------------------------------------------------------------
# 7. Handler timeout → metacog handler_timeout
# ---------------------------------------------------------------------------


async def test_handler_timeout_publishes_metacog_error(tmp_path: Path) -> None:
    mqtt = FakeMqttClient(region_name="test_region")
    region_root = _build_region_root(tmp_path)

    handler_file = region_root / "handlers" / "on_hang.py"
    handler_file.write_text(
        'SUBSCRIPTIONS = ["hive/test/hang"]\n'
        "TIMEOUT_S = 0.05\n"
        "\n"
        "import asyncio\n"
        "\n"
        "async def handle(envelope, ctx):\n"
        "    await asyncio.sleep(10)\n",
        encoding="utf-8",
    )

    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    await runtime.bootstrap()

    env = Envelope.new(
        source_region="other_region",
        topic="hive/test/hang",
        content_type="application/json",
        data={},
    )
    try:
        await mqtt.inject("hive/test/hang", env)
        # Allow time for timeout to fire
        await asyncio.sleep(0.2)

        metacog = [
            e.payload.data
            for topic, e, _, _ in mqtt.published
            if topic == METACOGNITION_ERROR_DETECTED
        ]
        assert any(m.get("kind") == "handler_timeout" for m in metacog)
    finally:
        await runtime.shutdown("test_done")


# ---------------------------------------------------------------------------
# 8. force_sleep trigger (test-only helper)
# ---------------------------------------------------------------------------


async def test_force_sleep_enters_sleep_and_returns_to_wake(
    tmp_path: Path,
) -> None:
    """force_sleep simulates an external trigger: publishes request, waits
    for granted (auto-granted by helper), runs SleepCoordinator, returns to
    WAKE on no_change."""
    mqtt = FakeMqttClient(region_name="test_region")
    llm = FakeLlmAdapter(scripted_responses=[_empty_review_response()])

    runtime = await _build_runtime(
        tmp_path, fake_mqtt=mqtt, fake_llm=llm
    )
    await runtime.bootstrap()

    # Spawn a task that grants sleep after we see the request published.
    async def grant_after_request() -> None:
        for _ in range(200):
            grant = any(
                topic == SYSTEM_SLEEP_REQUEST for topic, *_ in mqtt.published
            )
            if grant:
                granted = Envelope.new(
                    source_region="glia",
                    topic=SYSTEM_SLEEP_GRANTED,
                    content_type="application/json",
                    data={"region": "test_region"},
                )
                await mqtt.inject(SYSTEM_SLEEP_GRANTED, granted)
                return
            await asyncio.sleep(0.01)

    granter = asyncio.create_task(grant_after_request())
    try:
        await runtime.force_sleep("test_trigger")
        await granter
        # After sleep no_change, runtime returns to WAKE.
        assert runtime.phase == LifecyclePhase.WAKE
        # Saw the sleep/request publish.
        topics = [t for t, *_ in mqtt.published]
        assert SYSTEM_SLEEP_REQUEST in topics
    finally:
        await runtime.shutdown("test_done")


# ---------------------------------------------------------------------------
# 9. Restart flow — verify passes
# ---------------------------------------------------------------------------


async def test_restart_flow_publishes_restart_and_shuts_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SleepCoordinator returns restart=True → pre-verify passes → publish
    restart/request + shutdown('restart')."""
    mqtt = FakeMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    await runtime.bootstrap()

    # Monkey-patch SleepCoordinator.run to return restart=True directly.
    async def fake_run(trigger: str) -> SleepResult:
        return SleepResult(
            status="committed_restart",
            restart=True,
            sha="a" * 40,
            events_reviewed=0,
            ltm_writes=0,
            stm_pruned=0,
        )

    monkeypatch.setattr(runtime.sleep, "run", fake_run)

    # Monkeypatch pre-restart verify to always pass.
    async def fake_verify() -> bool:
        return True

    monkeypatch.setattr(runtime, "_pre_restart_verify", fake_verify)

    # Auto-grant sleep.
    async def grant_after_request() -> None:
        for _ in range(200):
            if any(t == SYSTEM_SLEEP_REQUEST for t, *_ in mqtt.published):
                granted = Envelope.new(
                    source_region="glia",
                    topic=SYSTEM_SLEEP_GRANTED,
                    content_type="application/json",
                    data={"region": "test_region"},
                )
                await mqtt.inject(SYSTEM_SLEEP_GRANTED, granted)
                return
            await asyncio.sleep(0.01)

    granter = asyncio.create_task(grant_after_request())
    await runtime.force_sleep("restart_trigger")
    await granter

    # Should have published restart_request and shutdown.
    topics = [t for t, *_ in mqtt.published]
    assert SYSTEM_RESTART_REQUEST in topics
    assert runtime.phase == LifecyclePhase.SHUTDOWN


# ---------------------------------------------------------------------------
# 10. Pre-restart verify failure → stay WAKE
# ---------------------------------------------------------------------------


async def test_pre_restart_verify_failure_reverts_and_stays_wake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mqtt = FakeMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    await runtime.bootstrap()

    async def fake_run(trigger: str) -> SleepResult:
        return SleepResult(
            status="committed_restart",
            restart=True,
            sha="b" * 40,
            events_reviewed=0,
            ltm_writes=0,
            stm_pruned=0,
        )

    monkeypatch.setattr(runtime.sleep, "run", fake_run)

    async def fake_verify() -> bool:
        return False

    monkeypatch.setattr(runtime, "_pre_restart_verify", fake_verify)

    revert_calls: list[str] = []

    def fake_revert(sha: str) -> None:
        revert_calls.append(sha)

    monkeypatch.setattr(runtime.git, "revert_to", fake_revert)

    async def grant_after_request() -> None:
        for _ in range(200):
            if any(t == SYSTEM_SLEEP_REQUEST for t, *_ in mqtt.published):
                granted = Envelope.new(
                    source_region="glia",
                    topic=SYSTEM_SLEEP_GRANTED,
                    content_type="application/json",
                    data={"region": "test_region"},
                )
                await mqtt.inject(SYSTEM_SLEEP_GRANTED, granted)
                return
            await asyncio.sleep(0.01)

    granter = asyncio.create_task(grant_after_request())
    try:
        await runtime.force_sleep("restart_trigger")
        await granter

        # Did NOT publish restart/request.
        topics = [t for t, *_ in mqtt.published]
        assert SYSTEM_RESTART_REQUEST not in topics
        # Metacog error published.
        metacog = [
            e.payload.data
            for topic, e, _, _ in mqtt.published
            if topic == METACOGNITION_ERROR_DETECTED
        ]
        assert any(
            m.get("kind") == "pre_restart_verify_failed" for m in metacog
        )
        # Revert invoked with the commit sha.
        assert revert_calls
        # Phase back to WAKE.
        assert runtime.phase == LifecyclePhase.WAKE
    finally:
        await runtime.shutdown("test_done")


# ---------------------------------------------------------------------------
# 11. Spawn reply correlation
# ---------------------------------------------------------------------------


async def test_publish_spawn_request_resolves_future_on_complete(
    tmp_path: Path,
) -> None:
    mqtt = FakeMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    await runtime.bootstrap()

    try:
        # Use a stub proposal — runtime only needs to publish + correlate.
        proposal = SpawnProposal(
            name="new_region",
            role="a spawned test region with enough role text",
            modality=None,
            llm={"provider": "anthropic", "model": "claude-3-5-sonnet-20241022"},
            capabilities=CapabilityProfile(
                self_modify=False,
                tool_use="none",
                vision=False,
                audio=False,
            ),
            starter_prompt="hello world",
            initial_subscriptions=[
                SubscriptionEntry(topic="hive/test/spawn", qos=1)
            ],
        )
        correlation_id = "corr-1234"
        future = await runtime.publish_spawn_request(proposal, correlation_id)
        assert isinstance(future, asyncio.Future)
        assert not future.done()

        # Simulate glia completion reply with matching correlation_id.
        complete_env = Envelope.new(
            source_region="glia",
            topic=SYSTEM_SPAWN_COMPLETE,
            content_type="application/json",
            data={"ok": True, "sha": "c" * 40},
            correlation_id=correlation_id,
        )
        await mqtt.inject(SYSTEM_SPAWN_COMPLETE, complete_env)
        await asyncio.sleep(0)

        # Future should now be resolved with SpawnResult(ok=True).
        result = await asyncio.wait_for(future, timeout=1.0)
        assert result.ok is True
    finally:
        await runtime.shutdown("test_done")


# ---------------------------------------------------------------------------
# 12. Quiet-window trigger
# ---------------------------------------------------------------------------


async def test_quiet_window_triggers_sleep(tmp_path: Path) -> None:
    """With tiny sleep_quiet_window_s, quiet time triggers _sleep_monitor."""
    mqtt = FakeMqttClient(region_name="test_region")
    llm = FakeLlmAdapter(scripted_responses=[_empty_review_response()])
    cfg = _build_config(sleep_quiet_window_s=30)  # min allowed; we'll bypass
    runtime = await _build_runtime(
        tmp_path,
        config=cfg,
        fake_mqtt=mqtt,
        fake_llm=llm,
    )
    await runtime.bootstrap()

    try:
        # Override the quiet window to a very short duration AFTER bootstrap
        # so we don't violate config validation at schema time.
        runtime._sleep_quiet_window_s = 0.1
        # Ensure _last_inbound_ts is in the past.
        runtime._last_inbound_ts = time.monotonic() - 5.0

        # Auto-grant sleep requests.
        async def grant_worker() -> None:
            for _ in range(500):
                if any(
                    t == SYSTEM_SLEEP_REQUEST for t, *_ in mqtt.published
                ):
                    granted = Envelope.new(
                        source_region="glia",
                        topic=SYSTEM_SLEEP_GRANTED,
                        content_type="application/json",
                        data={"region": "test_region"},
                    )
                    await mqtt.inject(SYSTEM_SLEEP_GRANTED, granted)
                    return
                await asyncio.sleep(0.02)

        granter = asyncio.create_task(grant_worker())
        # Kick off run() as a task so the sleep monitor can fire.
        run_task = asyncio.create_task(runtime.run())
        # Wait for a sleep transition.
        for _ in range(200):
            topics = [t for t, *_ in mqtt.published]
            if SYSTEM_SLEEP_REQUEST in topics:
                break
            await asyncio.sleep(0.02)
        await granter
        # After sleep completes (no_change), runtime returns to WAKE.
        for _ in range(200):
            if runtime.phase == LifecyclePhase.WAKE:
                break
            await asyncio.sleep(0.02)
        assert SYSTEM_SLEEP_REQUEST in [t for t, *_ in mqtt.published]
    finally:
        await runtime.shutdown("test_done")
        # Clean up the run task
        if not run_task.done():
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task
