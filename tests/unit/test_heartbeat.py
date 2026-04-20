"""Tests for region_template.heartbeat — spec §A.5."""
from __future__ import annotations

import asyncio
import contextlib
import re

import pytest

from region_template.heartbeat import Heartbeat, HeartbeatState
from region_template.types import LifecyclePhase
from shared.message_envelope import Envelope

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

# The 11 fields required by spec §A.5, in order.
_A5_FIELDS = (
    "region",
    "status",
    "phase",
    "ts",
    "uptime_s",
    "handler_count",
    "queue_depth_messages",
    "llm_tokens_used_lifetime",
    "stm_bytes",
    "last_error_ts",
    "build_sha",
)

# Fixture values used across multiple tests so magic-number lint stays happy.
_HANDLER_COUNT = 3
_QUEUE_DEPTH = 0
_LLM_TOKENS = 142301
_STM_BYTES = 1823

# Cadence test tolerances.
_CADENCE_MIN_TICKS = 2
_CADENCE_MAX_TICKS = 6         # generous upper bound for CI jitter
_IDEMPOTENT_MAX_TICKS = 6      # two concurrent tasks would easily exceed this
_STATE_PROVIDER_MIN_CALLS = 3


class _RecordingPublisher:
    """Minimal async callable that records every envelope it receives."""

    def __init__(self) -> None:
        self.published: list[Envelope] = []
        self._event = asyncio.Event()

    async def __call__(self, envelope: Envelope) -> None:
        self.published.append(envelope)
        self._event.set()

    async def wait_for(self, n: int, timeout: float = 2.0) -> None:
        """Wait until at least ``n`` envelopes have been recorded."""
        deadline = asyncio.get_event_loop().time() + timeout
        while len(self.published) < n:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                raise AssertionError(
                    f"Only received {len(self.published)} of {n} envelopes"
                )
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._event.wait(), timeout=remaining)
            self._event.clear()


def _default_state() -> HeartbeatState:
    return HeartbeatState(
        status="wake",
        phase=LifecyclePhase.WAKE,
        handler_count=_HANDLER_COUNT,
        queue_depth_messages=_QUEUE_DEPTH,
        llm_tokens_used_lifetime=_LLM_TOKENS,
        stm_bytes=_STM_BYTES,
        last_error_ts=None,
    )


def _make_heartbeat(
    publisher: _RecordingPublisher,
    *,
    region: str = "x",
    interval_s: float = 0.05,
    state: HeartbeatState | None = None,
    build_sha: str = "abcdef1",
) -> Heartbeat:
    return Heartbeat(
        region=region,
        interval_s=interval_s,
        publish=publisher,
        state_provider=lambda: state if state is not None else _default_state(),
        build_sha=build_sha,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCadence:
    async def test_emits_multiple_ticks_at_configured_cadence(self) -> None:
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub, interval_s=0.05)
        await hb.start()
        await asyncio.sleep(0.15)
        await hb.stop()
        # First tick is immediate; expect 2-4 within ~150ms at 50ms cadence.
        count = len(pub.published)
        assert _CADENCE_MIN_TICKS <= count <= _CADENCE_MAX_TICKS, (
            f"Expected {_CADENCE_MIN_TICKS}-{_CADENCE_MAX_TICKS} envelopes; "
            f"got {count}"
        )


class TestEnvelopeShape:
    async def test_envelope_routing_fields(self) -> None:
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub, region="x")
        await hb.start()
        await pub.wait_for(1)
        await hb.stop()

        env = pub.published[0]
        assert env.source_region == "x"
        assert env.topic == "hive/system/heartbeat/x"
        assert env.payload.content_type == "application/json"

    async def test_payload_has_all_eleven_a5_fields(self) -> None:
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub)
        await hb.start()
        await pub.wait_for(1)
        await hb.stop()

        data = pub.published[0].payload.data
        assert isinstance(data, dict)
        assert set(data.keys()) == set(_A5_FIELDS), (
            f"Expected fields {_A5_FIELDS}, got {sorted(data.keys())}"
        )

    async def test_payload_field_types(self) -> None:
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub, region="x", build_sha="abcdef1")
        await hb.start()
        await pub.wait_for(1)
        await hb.stop()

        data = pub.published[0].payload.data
        assert data["region"] == "x"
        assert data["status"] == "wake"
        assert data["phase"] == "wake"          # StrEnum string form
        assert isinstance(data["ts"], str)
        assert isinstance(data["uptime_s"], int)
        assert data["handler_count"] == _HANDLER_COUNT
        assert data["queue_depth_messages"] == _QUEUE_DEPTH
        assert data["llm_tokens_used_lifetime"] == _LLM_TOKENS
        assert data["stm_bytes"] == _STM_BYTES
        assert data["last_error_ts"] is None
        assert data["build_sha"] == "abcdef1"

    async def test_ts_format_iso8601_utc_milliseconds(self) -> None:
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub)
        await hb.start()
        await pub.wait_for(1)
        await hb.stop()

        ts = pub.published[0].payload.data["ts"]
        assert _TS_RE.match(ts), f"ts {ts!r} not ISO-8601-UTC with ms precision + Z"

    async def test_last_error_ts_preserves_string_value(self) -> None:
        pub = _RecordingPublisher()
        state = HeartbeatState(
            status="wake",
            phase=LifecyclePhase.WAKE,
            handler_count=0,
            queue_depth_messages=0,
            llm_tokens_used_lifetime=0,
            stm_bytes=0,
            last_error_ts="2026-04-19T09:00:00.000Z",
        )
        hb = _make_heartbeat(pub, state=state)
        await hb.start()
        await pub.wait_for(1)
        await hb.stop()
        assert pub.published[0].payload.data["last_error_ts"] == "2026-04-19T09:00:00.000Z"


class TestStateProvider:
    async def test_state_provider_called_per_tick(self) -> None:
        pub = _RecordingPublisher()
        counter = {"n": 0}

        def provider() -> HeartbeatState:
            counter["n"] += 1
            return _default_state()

        hb = Heartbeat(
            region="x",
            interval_s=0.05,
            publish=pub,
            state_provider=provider,
            build_sha="abcdef1",
        )
        await hb.start()
        await pub.wait_for(_STATE_PROVIDER_MIN_CALLS)
        await hb.stop()
        assert counter["n"] >= _STATE_PROVIDER_MIN_CALLS


class TestIdempotency:
    async def test_start_twice_does_not_spawn_second_task(self) -> None:
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub, interval_s=0.05)
        await hb.start()
        await hb.start()   # second start must be a no-op
        await asyncio.sleep(0.12)
        await hb.stop()

        # At 50ms cadence over ~120ms we should see roughly 2-4 ticks,
        # never the ~4-8 that two concurrent tasks would produce.
        count = len(pub.published)
        assert count <= _IDEMPOTENT_MAX_TICKS, (
            f"start() appears non-idempotent; double-emission suspected "
            f"(count={count})"
        )

    async def test_stop_is_idempotent_on_running_instance(self) -> None:
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub)
        await hb.start()
        await pub.wait_for(1)
        await hb.stop()
        await hb.stop()   # must not raise

    async def test_stop_is_safe_on_never_started_instance(self) -> None:
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub)
        await hb.stop()   # never started — must not raise


class TestSetInterval:
    async def test_set_interval_speeds_up_cadence(self) -> None:
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub, interval_s=0.2)
        await hb.start()
        # Wait for the first immediate emission.
        await pub.wait_for(1)
        baseline = len(pub.published)

        hb.set_interval(0.05)
        await asyncio.sleep(0.15)
        await hb.stop()

        # With the 200ms interval kept, we'd see the first tick + possibly
        # one more (~200ms). After dropping to 50ms we should see several.
        final = len(pub.published)
        assert final - baseline >= 1, (
            f"Expected more ticks after set_interval; baseline={baseline}, "
            f"final={final}"
        )


class TestUptime:
    async def test_uptime_s_is_int_and_monotonic(self) -> None:
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub, interval_s=0.05)
        await hb.start()
        await pub.wait_for(2)
        await hb.stop()

        up0 = pub.published[0].payload.data["uptime_s"]
        up1 = pub.published[1].payload.data["uptime_s"]
        assert isinstance(up0, int)
        assert isinstance(up1, int)
        assert up1 >= up0


class TestFieldOrder:
    async def test_payload_field_order_matches_spec_a5(self) -> None:
        """Spec §A.5 lists the 11 fields in a specific order.

        dict insertion order preserves this; JSON serialization
        reflects it for debuggability.
        """
        pub = _RecordingPublisher()
        hb = _make_heartbeat(pub)
        await hb.start()
        await pub.wait_for(1)
        await hb.stop()

        data = pub.published[0].payload.data
        assert tuple(data.keys()) == _A5_FIELDS


# ---------------------------------------------------------------------------
# Dataclass sanity
# ---------------------------------------------------------------------------


class TestHeartbeatStateDataclass:
    def test_heartbeat_state_is_frozen(self) -> None:
        state = _default_state()
        with pytest.raises((AttributeError, Exception)):
            # frozen dataclasses raise FrozenInstanceError on assignment
            state.status = "sleep"  # type: ignore[misc]
