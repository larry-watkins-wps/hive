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
from region_template.errors import ConfigError, GitError
from region_template.errors import ConnectionError as HiveConnectionError
from region_template.llm_adapter import CompletionResult
from region_template.runtime import RegionRuntime
from region_template.self_modify import SpawnProposal, SubscriptionEntry
from region_template.sleep import SleepResult
from region_template.token_ledger import TokenUsage
from region_template.types import CapabilityProfile, LifecyclePhase
from shared.message_envelope import Envelope
from shared.topics import (
    BROADCAST_SHUTDOWN,
    METACOGNITION_ERROR_DETECTED,
    MODULATOR_CORTISOL,
    SYSTEM_RESTART_REQUEST,
    SYSTEM_SLEEP_FORCE,
    SYSTEM_SLEEP_GRANTED,
    SYSTEM_SLEEP_REQUEST,
    SYSTEM_SPAWN_COMPLETE,
    fill,
)
from tests.fakes.llm import FakeLlmAdapter
from tests.fakes.mqtt import FakeMqttClient

# Constants used in assertions (silences ruff PLR2004 on "magic values").
_MIN_HEARTBEAT_TICKS = 2

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


async def test_subscriptions_yaml_wrapped_format(tmp_path: Path) -> None:
    """Scaffold shape ``{schema_version, subscriptions: [...]}`` subscribes correctly.

    Every v0 region ships this wrapper shape; earlier the loader only accepted
    a bare list and silently warned ``subscriptions_yaml_not_a_list`` leaving
    the region deaf.
    """
    mqtt = FakeMqttClient(region_name="test_region")
    region_root = _build_region_root(tmp_path)
    (region_root / "subscriptions.yaml").write_text(
        "schema_version: 1\n"
        "subscriptions:\n"
        "  - topic: hive/self/#\n"
        "    qos: 1\n"
        "  - topic: hive/modulator/#\n"
        "    qos: 0\n",
        encoding="utf-8",
    )

    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    try:
        await runtime.bootstrap()
        assert "hive/self/#" in mqtt._subscriptions
        assert "hive/modulator/#" in mqtt._subscriptions
    finally:
        await runtime.shutdown("test_done")


async def test_subscriptions_yaml_bare_list_format(tmp_path: Path) -> None:
    """Bare top-level list remains valid for backward compat."""
    mqtt = FakeMqttClient(region_name="test_region")
    region_root = _build_region_root(tmp_path)
    (region_root / "subscriptions.yaml").write_text(
        "- topic: hive/sensory/#\n"
        "  qos: 0\n"
        "- topic: hive/motor/complete\n"
        "  qos: 1\n",
        encoding="utf-8",
    )

    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    try:
        await runtime.bootstrap()
        assert "hive/sensory/#" in mqtt._subscriptions
        assert "hive/motor/complete" in mqtt._subscriptions
    finally:
        await runtime.shutdown("test_done")


async def test_subscriptions_yaml_dict_without_subscriptions_key_is_skipped(
    tmp_path: Path,
) -> None:
    """A wrapper dict missing the ``subscriptions`` key is skipped (no crash)."""
    mqtt = FakeMqttClient(region_name="test_region")
    region_root = _build_region_root(tmp_path)
    (region_root / "subscriptions.yaml").write_text(
        "schema_version: 1\nnote: no subscriptions key here\n",
        encoding="utf-8",
    )

    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    try:
        await runtime.bootstrap()
        # Bootstrap succeeded; no yaml-derived subscriptions added.
        assert "hive/self/#" not in mqtt._subscriptions
    finally:
        await runtime.shutdown("test_done")


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


# ---------------------------------------------------------------------------
# Helpers for sleep-trigger tests
# ---------------------------------------------------------------------------


async def _auto_grant_sleep(mqtt: FakeMqttClient, region: str) -> None:
    """Spin until a sleep/request is published, then inject sleep/granted."""
    for _ in range(500):
        if any(t == SYSTEM_SLEEP_REQUEST for t, *_ in mqtt.published):
            granted = Envelope.new(
                source_region="glia",
                topic=SYSTEM_SLEEP_GRANTED,
                content_type="application/json",
                data={"region": region},
            )
            await mqtt.inject(SYSTEM_SLEEP_GRANTED, granted)
            return
        await asyncio.sleep(0.01)


async def _wait_for(predicate: Any, *, max_iters: int = 200, step: float = 0.02) -> None:
    """Yield until ``predicate()`` returns truthy, or give up."""
    for _ in range(max_iters):
        if predicate():
            return
        await asyncio.sleep(step)


# ---------------------------------------------------------------------------
# 13. ON_HEARTBEAT handlers invoked on each heartbeat tick (§A.6.1)
# ---------------------------------------------------------------------------


async def test_on_heartbeat_handler_called_on_tick(tmp_path: Path) -> None:
    """Handlers with ``ON_HEARTBEAT=True`` fire once per heartbeat interval.

    Uses heartbeat_interval_s=1 (config floor). Verify the counter grows
    via tick dispatch — not via the normal message path (the handler's
    SUBSCRIPTIONS use a sentinel topic that never fires).
    """
    mqtt = FakeMqttClient(region_name="test_region")
    region_root = _build_region_root(tmp_path)

    handler_file = region_root / "handlers" / "on_tick.py"
    handler_file.write_text(
        'SUBSCRIPTIONS = ["hive/_stub/never_fires"]\n'
        "TIMEOUT_S = 5.0\n"
        "ON_HEARTBEAT = True\n"
        "\n"
        "calls = []\n"
        "\n"
        "async def handle(envelope, ctx):\n"
        "    calls.append(envelope.topic)\n",
        encoding="utf-8",
    )

    cfg = _build_config(heartbeat_interval_s=1)
    runtime = await _build_runtime(tmp_path, config=cfg, fake_mqtt=mqtt)
    await runtime.bootstrap()

    run_task = asyncio.create_task(runtime.run())
    try:
        # Allow ~2.5 heartbeat intervals for at least 2 ticks.
        await asyncio.sleep(2.5)
        handler_module = runtime._handlers[0]
        assert handler_module.on_heartbeat is True
        handler_py = __import__(
            handler_module.handle.__module__, fromlist=["calls"]
        )
        # At least 2 ticks fired.
        assert len(handler_py.calls) >= _MIN_HEARTBEAT_TICKS, (
            f"expected >= {_MIN_HEARTBEAT_TICKS} tick calls, "
            f"got {handler_py.calls}"
        )
        # Every call received a heartbeat-shaped topic (not the sentinel).
        for topic in handler_py.calls:
            assert topic.startswith("hive/system/heartbeat/")
    finally:
        await runtime.shutdown("test_done")
        if not run_task.done():
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task


# ---------------------------------------------------------------------------
# 14. SLEEP unsubscribes normal topics; WAKE resume re-subscribes (§A.4.4.1)
# ---------------------------------------------------------------------------


async def test_sleep_unsubscribes_normal_topics(tmp_path: Path) -> None:
    """SLEEP pauses user-level subscriptions; WAKE resume re-adds them."""
    mqtt = FakeMqttClient(region_name="test_region")
    region_root = _build_region_root(tmp_path)

    handler_file = region_root / "handlers" / "on_live.py"
    handler_file.write_text(
        'SUBSCRIPTIONS = ["hive/test/topic"]\n'
        "TIMEOUT_S = 5.0\n"
        "\n"
        "async def handle(envelope, ctx):\n"
        "    pass\n",
        encoding="utf-8",
    )

    llm = FakeLlmAdapter(scripted_responses=[_empty_review_response()])
    runtime = await _build_runtime(
        tmp_path, fake_mqtt=mqtt, fake_llm=llm
    )
    await runtime.bootstrap()

    try:
        # Bootstrap subscribed hive/test/topic.
        assert "hive/test/topic" in mqtt._subscriptions

        granter = asyncio.create_task(
            _auto_grant_sleep(mqtt, "test_region")
        )
        # Drive into SLEEP via force_sleep.
        sleep_task = asyncio.create_task(runtime.force_sleep("test"))

        # Once phase is SLEEP, normal handler filter must be gone.
        await _wait_for(lambda: runtime.phase == LifecyclePhase.SLEEP)
        assert "hive/test/topic" not in mqtt._subscriptions

        # Wait for sleep to complete (empty review → back to WAKE).
        await sleep_task
        await granter

        assert runtime.phase == LifecyclePhase.WAKE
        # Re-subscribed on WAKE resume.
        assert "hive/test/topic" in mqtt._subscriptions
    finally:
        await runtime.shutdown("test_done")


# ---------------------------------------------------------------------------
# 15. STM-pressure sleep trigger
# ---------------------------------------------------------------------------


async def test_stm_pressure_triggers_sleep(tmp_path: Path) -> None:
    """Exceed ``stm_max_bytes`` → monitor fires stm_pressure trigger."""
    mqtt = FakeMqttClient(region_name="test_region")
    llm = FakeLlmAdapter(scripted_responses=[_empty_review_response()])
    cfg = _build_config()
    runtime = await _build_runtime(
        tmp_path, config=cfg, fake_mqtt=mqtt, fake_llm=llm
    )
    await runtime.bootstrap()

    try:
        # Inflate STM past the (post-bootstrap overridden) threshold.
        # stm_max_bytes in MemoryConfig has floor 1024; override in place
        # for the trigger check (runtime reads config.memory.stm_max_bytes).
        runtime.config.memory.stm_max_bytes = 1024
        await runtime.memory.write_stm(
            "big_payload", "x" * 2000, tags=("test",)
        )
        # Force the throttle to let stm check fire immediately.
        runtime._last_stm_check_ts = 0.0

        granter = asyncio.create_task(
            _auto_grant_sleep(mqtt, "test_region")
        )
        run_task = asyncio.create_task(runtime.run())
        await _wait_for(
            lambda: any(
                t == SYSTEM_SLEEP_REQUEST for t, *_ in mqtt.published
            )
        )
        await granter

        # Confirm the sleep/request payload's reason tag matches trigger.
        sleep_requests = [
            e for t, e, *_ in mqtt.published if t == SYSTEM_SLEEP_REQUEST
        ]
        assert sleep_requests
        reasons = [
            e.payload.data.get("reason", "") for e in sleep_requests
        ]
        # reason may be "stm_pressure" or "stm size X > Y" — check either.
        assert any(
            "stm" in r or r == "stm_pressure" for r in reasons
        ), f"no stm_pressure trigger seen: {reasons}"
    finally:
        await runtime.shutdown("test_done")
        if not run_task.done():
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task


# ---------------------------------------------------------------------------
# 16. Heartbeat-cycle (max_wake) sleep trigger
# ---------------------------------------------------------------------------


async def test_heartbeat_cycle_triggers_sleep(tmp_path: Path) -> None:
    """sleep_max_wake_s elapsed since last WAKE → heartbeat_cycle trigger."""
    mqtt = FakeMqttClient(region_name="test_region")
    llm = FakeLlmAdapter(scripted_responses=[_empty_review_response()])
    # Config floor is 60s; bypass after bootstrap.
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt, fake_llm=llm)
    await runtime.bootstrap()

    try:
        # Override threshold + backdate wake start so the check fires.
        runtime._sleep_max_wake_s = 0.1
        runtime._wake_start_time = time.monotonic() - 5.0
        # Suppress the quiet-window trigger so we know it's this one.
        runtime._sleep_quiet_window_s = 0.0
        runtime._last_inbound_ts = time.monotonic()

        granter = asyncio.create_task(
            _auto_grant_sleep(mqtt, "test_region")
        )
        run_task = asyncio.create_task(runtime.run())

        await _wait_for(
            lambda: any(
                t == SYSTEM_SLEEP_REQUEST for t, *_ in mqtt.published
            )
        )
        await granter

        sleep_requests = [
            e for t, e, *_ in mqtt.published if t == SYSTEM_SLEEP_REQUEST
        ]
        reasons = [
            e.payload.data.get("reason", "") for e in sleep_requests
        ]
        # reason is "awake for 0s" or the trigger literal.
        assert any(
            "awake" in r or r == "heartbeat_cycle" for r in reasons
        ), f"no heartbeat_cycle trigger seen: {reasons}"
    finally:
        await runtime.shutdown("test_done")
        if not run_task.done():
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task


# ---------------------------------------------------------------------------
# 17. External-command sleep trigger via hive/system/sleep/force
# ---------------------------------------------------------------------------


async def test_external_command_triggers_sleep(tmp_path: Path) -> None:
    """A ``hive/system/sleep/force`` envelope with matching region → sleep."""
    mqtt = FakeMqttClient(region_name="test_region")
    llm = FakeLlmAdapter(scripted_responses=[_empty_review_response()])
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt, fake_llm=llm)
    await runtime.bootstrap()

    try:
        # Start the run loop (it subscribes to sleep/force at monitor start).
        run_task = asyncio.create_task(runtime.run())
        # Give monitor a beat to subscribe.
        await _wait_for(
            lambda: SYSTEM_SLEEP_FORCE in mqtt._subscriptions
        )

        granter = asyncio.create_task(
            _auto_grant_sleep(mqtt, "test_region")
        )
        force_env = Envelope.new(
            source_region="glia",
            topic=SYSTEM_SLEEP_FORCE,
            content_type="application/json",
            data={"region": "test_region", "reason": "operator_shutdown"},
        )
        await mqtt.inject(SYSTEM_SLEEP_FORCE, force_env)

        await _wait_for(
            lambda: any(
                t == SYSTEM_SLEEP_REQUEST for t, *_ in mqtt.published
            )
        )
        await granter

        sleep_requests = [
            e for t, e, *_ in mqtt.published if t == SYSTEM_SLEEP_REQUEST
        ]
        assert sleep_requests
        reasons = [
            e.payload.data.get("reason", "") for e in sleep_requests
        ]
        # The _on_sleep_force callback forwards payload.reason, so
        # reason == "operator_shutdown" (or "external_command" fallback).
        assert any(
            r in ("operator_shutdown", "external_command") for r in reasons
        ), f"no external_command trigger seen: {reasons}"
    finally:
        await runtime.shutdown("test_done")
        if not run_task.done():
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await run_task


# ---------------------------------------------------------------------------
# 18. hive/broadcast/shutdown delivered during WAKE triggers shutdown (§E.13)
# ---------------------------------------------------------------------------


async def test_broadcast_shutdown_during_wake_triggers_shutdown(
    tmp_path: Path,
) -> None:
    """An operator broadcast during WAKE must transition the region to SHUTDOWN.

    Regression for review finding I1: previously the runtime only subscribed
    to ``hive/broadcast/shutdown`` inside ``_subscribe_sleep_phase_listener``,
    so WAKE regions silently ignored operator shutdown. §E.13 and §A.4.4.1
    both expect delivery in WAKE (the "during sleep" wording in §A.4.4.1 is
    additive, not exclusive).
    """
    mqtt = FakeMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    await runtime.bootstrap()

    # Confirm the bootstrap path added the subscription during WAKE.
    assert BROADCAST_SHUTDOWN in mqtt._subscriptions, (
        "WAKE bootstrap must subscribe to hive/broadcast/shutdown"
    )
    assert runtime.phase == LifecyclePhase.WAKE

    env = Envelope.new(
        source_region="glia",
        topic=BROADCAST_SHUTDOWN,
        content_type="application/json",
        data={"reason": "operator_halt"},
    )
    await mqtt.inject(BROADCAST_SHUTDOWN, env)
    # _on_broadcast_shutdown awaits shutdown directly; no extra pump.

    assert runtime.phase == LifecyclePhase.SHUTDOWN


# ---------------------------------------------------------------------------
# 19. Bootstrap fails with GitError when GitTools.__init__ raises
# ---------------------------------------------------------------------------


async def test_bootstrap_raises_git_error_on_git_init_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GitTools failure during bootstrap surfaces as GitError (§A.9 exit 3)."""
    mqtt = FakeMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)

    def fake_git_init(self: Any, root: Path, region_name: str) -> None:
        raise GitError(f"git init failed for {region_name}")

    monkeypatch.setattr(
        "region_template.runtime.GitTools.__init__",
        fake_git_init,
    )

    with pytest.raises(GitError):
        await runtime.bootstrap()


# ---------------------------------------------------------------------------
# 20. Bootstrap fails with ConnectionError when MQTT __aenter__ raises
# ---------------------------------------------------------------------------


async def test_bootstrap_raises_connection_error_on_mqtt_failure(
    tmp_path: Path,
) -> None:
    """MQTT connect failure during bootstrap surfaces as ConnectionError
    (§A.9 exit 4)."""

    class BrokenMqttClient(FakeMqttClient):
        async def __aenter__(self) -> FakeMqttClient:
            raise HiveConnectionError("broker unreachable")

    mqtt = BrokenMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)

    with pytest.raises(HiveConnectionError):
        await runtime.bootstrap()


# ---------------------------------------------------------------------------
# 21. Sleep-grant timeout leaves the region in WAKE with a metacog error
# ---------------------------------------------------------------------------


async def test_sleep_grant_timeout_stays_wake(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``hive/system/sleep/granted`` within the timeout → stay WAKE + metacog.

    Regression: if a grant never arrives the runtime must not escalate to
    SLEEP or SHUTDOWN. Spec §A.4.4 step 2.
    """
    # Shorten the grant timeout so the test completes quickly.
    monkeypatch.setattr(
        "region_template.runtime._SLEEP_GRANT_TIMEOUT_S", 0.05
    )

    mqtt = FakeMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    await runtime.bootstrap()

    try:
        # Don't publish sleep/granted; force_sleep will time out waiting.
        await runtime.force_sleep("test_trigger")

        # Phase stayed WAKE (didn't escalate or hang).
        assert runtime.phase == LifecyclePhase.WAKE
        # Metacog error published with kind=sleep_grant_timeout.
        metacog = [
            e.payload.data
            for topic, e, _, _ in mqtt.published
            if topic == METACOGNITION_ERROR_DETECTED
        ]
        assert any(
            m.get("kind") == "sleep_grant_timeout" for m in metacog
        ), f"no sleep_grant_timeout metacog seen: {metacog}"
    finally:
        await runtime.shutdown("test_done")


# ---------------------------------------------------------------------------
# 22. Cortisol spike during SLEEP calls SleepCoordinator.abort()
# ---------------------------------------------------------------------------


async def test_cortisol_abort_during_sleep(tmp_path: Path) -> None:
    """Unit-level: ``_on_cortisol_during_sleep`` above threshold calls abort.

    Staging the full pipeline (enter sleep + race an LLM call + inject
    cortisol) is fragile on Windows; per the fix plan we exercise the
    callback directly with phase=SLEEP so the abort branch is covered.
    """
    mqtt = FakeMqttClient(region_name="test_region")
    runtime = await _build_runtime(tmp_path, fake_mqtt=mqtt)
    await runtime.bootstrap()

    abort_calls: list[str] = []

    async def fake_abort(reason: str) -> None:
        abort_calls.append(reason)

    # Install a fake abort on the coordinator (created during bootstrap).
    assert runtime.sleep is not None
    runtime.sleep.abort = fake_abort  # type: ignore[assignment]

    # Flip phase to SLEEP so the callback's guard lets through.
    runtime.phase = LifecyclePhase.SLEEP

    threshold = runtime.config.lifecycle.sleep_abort_cortisol_threshold
    above = min(1.0, threshold + 0.1)
    below = max(0.0, threshold - 0.1)

    # Below-threshold: must NOT abort.
    low_env = Envelope.new(
        source_region="amygdala",
        topic=MODULATOR_CORTISOL,
        content_type="application/json",
        data={"level": below},
    )
    await runtime._on_cortisol_during_sleep(low_env)
    assert abort_calls == []

    # Above-threshold: MUST abort.
    high_env = Envelope.new(
        source_region="amygdala",
        topic=MODULATOR_CORTISOL,
        content_type="application/json",
        data={"level": above},
    )
    await runtime._on_cortisol_during_sleep(high_env)
    assert len(abort_calls) == 1
    assert "cortisol" in abort_calls[0]

    # Cleanup: put phase back so shutdown path is clean.
    runtime.phase = LifecyclePhase.WAKE
    await runtime.shutdown("test_done")


# ---------------------------------------------------------------------------
# 23. _pre_restart_verify — real subprocess success path
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_pre_restart_verify_real_subprocess_success(
    tmp_path: Path,
) -> None:
    """Exercise the real subprocess dry-import against a real config on disk.

    Complements ``test_pre_restart_verify_failure_reverts_and_stays_wake``
    (which monkeypatches the verify method wholesale). This test runs
    ``sys.executable -c "import runtime; RegionRuntime(config_path)"`` in
    a subprocess so the actual §D.5.5 path gets coverage. Marked ``slow``
    — subprocess spin-up takes roughly a second.
    """
    # Write a valid minimal config.yaml that load_config accepts.
    region_name = "verify_region"
    region_root = tmp_path / "regions" / region_name
    region_root.mkdir(parents=True)
    (region_root / "handlers").mkdir()
    (region_root / "memory").mkdir()
    (region_root / "prompt.md").write_text("seed\n", encoding="utf-8")

    config_yaml = region_root / "config.yaml"
    config_yaml.write_text(
        "schema_version: 1\n"
        f"name: {region_name}\n"
        "role: a verify-path test region used only by unit tests\n"
        "llm:\n"
        "  provider: anthropic\n"
        "  model: claude-3-5-sonnet-20241022\n"
        "capabilities:\n"
        "  self_modify: false\n"
        "  tool_use: none\n"
        "  vision: false\n"
        "  audio: false\n",
        encoding="utf-8",
    )

    # Build the runtime via __init__ so config_path points at the real file.
    runtime = RegionRuntime(config_yaml)

    # No mock — this actually shells out to sys.executable.
    ok = await runtime._pre_restart_verify()
    assert ok is True, "real subprocess dry-import must succeed on a valid config"
