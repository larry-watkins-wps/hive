"""Unit tests for ``glia/bridges/*`` — plan task 5.11.

Covers:
  * RhythmGenerator — three topics tick at ~40/20/6 Hz, stop is safe.
  * InputTextBridge — TCP loopback publishes envelopes; bind failure
    publishes an ``unavailable`` metric.
  * MicBridge / CameraBridge — disabled-by-default and missing-import
    paths publish ``unavailable``.
  * SpeakerBridge — handle_message drops when unavailable.
  * MotorBridge — handle_message logs action data.

Tests run without ``sounddevice``/``cv2``/``pyserial`` installed —
that confirms the graceful-degrade paths.
"""
from __future__ import annotations

import asyncio
import contextlib
import sys
from unittest.mock import AsyncMock

import pytest
import structlog.testing

from glia.bridges import (
    CameraBridge,
    InputTextBridge,
    MicBridge,
    MotorBridge,
    RhythmGenerator,
    SpeakerBridge,
)
from shared.message_envelope import Envelope

GAMMA_HZ = 40.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _topics(mock_publish: AsyncMock) -> list[str]:
    """Collect topic strings from a mock's call history."""
    out: list[str] = []
    for call in mock_publish.await_args_list:
        if not call.args:
            continue
        env = call.args[0]
        if isinstance(env, Envelope):
            out.append(env.topic)
    return out


def _last_data_for(mock_publish: AsyncMock, topic: str) -> dict | None:
    for call in reversed(mock_publish.await_args_list):
        if not call.args:
            continue
        env = call.args[0]
        if isinstance(env, Envelope) and env.topic == topic:
            return env.payload.data  # type: ignore[return-value]
    return None


# ---------------------------------------------------------------------------
# RhythmGenerator
# ---------------------------------------------------------------------------

class TestRhythmGenerator:
    async def test_three_topics_published(self) -> None:
        publish = AsyncMock()
        gen = RhythmGenerator(publish)
        await gen.start()
        # 250ms ≥ 10× gamma period (25ms); beta (50ms) ticks ≥ 5×; theta
        # (167ms) ticks ≥ 1×, so all three bands are guaranteed to fire.
        await asyncio.sleep(0.25)
        await gen.stop()

        topics = set(_topics(publish))
        assert "hive/rhythm/gamma" in topics
        assert "hive/rhythm/beta" in topics
        assert "hive/rhythm/theta" in topics

    async def test_envelope_shape(self) -> None:
        publish = AsyncMock()
        gen = RhythmGenerator(publish)
        await gen.start()
        await asyncio.sleep(0.1)
        await gen.stop()

        # Grab any gamma publish and check envelope fields.
        gamma_data = _last_data_for(publish, "hive/rhythm/gamma")
        assert gamma_data is not None
        assert gamma_data["hz"] == GAMMA_HZ
        assert isinstance(gamma_data["beat"], int)
        assert gamma_data["beat"] >= 0
        assert isinstance(gamma_data["ts"], float)

    async def test_stop_cancels_tasks(self) -> None:
        publish = AsyncMock()
        gen = RhythmGenerator(publish)
        await gen.start()
        await asyncio.sleep(0.05)
        await gen.stop()
        # After stop, tasks list is empty and all underlying tasks done.
        assert gen._tasks == []  # noqa: SLF001

    async def test_stop_without_start_is_safe(self) -> None:
        publish = AsyncMock()
        gen = RhythmGenerator(publish)
        await gen.stop()  # must not raise

    async def test_start_is_idempotent(self) -> None:
        publish = AsyncMock()
        gen = RhythmGenerator(publish)
        await gen.start()
        first_tasks = list(gen._tasks)  # noqa: SLF001
        await gen.start()  # second call must not double-spawn
        assert gen._tasks == first_tasks  # noqa: SLF001
        await gen.stop()


# ---------------------------------------------------------------------------
# InputTextBridge
# ---------------------------------------------------------------------------

class TestInputTextBridge:
    async def test_line_publishes_envelope(self) -> None:
        publish = AsyncMock()
        bridge = InputTextBridge(publish, host="127.0.0.1", port=0)
        await bridge.start()
        try:
            assert bridge.server is not None
            port = bridge.server.sockets[0].getsockname()[1]

            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(b"hello hive\n")
            await writer.drain()
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

            # Give the server a moment to process the line.
            for _ in range(20):
                if "hive/sensory/input/text" in _topics(publish):
                    break
                await asyncio.sleep(0.02)

            topics = _topics(publish)
            assert "hive/sensory/input/text" in topics
            data = _last_data_for(publish, "hive/sensory/input/text")
            assert data == {"text": "hello hive"}
            _ = reader  # silence unused
        finally:
            await bridge.stop()

    async def test_bind_failure_publishes_unavailable(self) -> None:
        publish = AsyncMock()
        # Occupy a port first, then try to bind a second bridge to the
        # same port so start() hits OSError.
        hog = await asyncio.start_server(
            lambda r, w: None, host="127.0.0.1", port=0
        )
        port = hog.sockets[0].getsockname()[1]
        try:
            bridge = InputTextBridge(publish, host="127.0.0.1", port=port)
            await bridge.start()

            topics = _topics(publish)
            assert "hive/system/metrics/hardware/input_text" in topics
            data = _last_data_for(
                publish, "hive/system/metrics/hardware/input_text"
            )
            assert data is not None
            assert data["status"] == "unavailable"
            assert "bind_failed" in data["reason"]
            assert bridge.server is None

            await bridge.stop()  # safe with no server
        finally:
            hog.close()
            await hog.wait_closed()

    async def test_stop_closes_server(self) -> None:
        publish = AsyncMock()
        bridge = InputTextBridge(publish, host="127.0.0.1", port=0)
        await bridge.start()
        assert bridge.server is not None
        assert bridge.server.is_serving()
        await bridge.stop()
        assert bridge.server is None


# ---------------------------------------------------------------------------
# MicBridge
# ---------------------------------------------------------------------------

class TestMicBridge:
    async def test_disabled_publishes_unavailable(self) -> None:
        publish = AsyncMock()
        bridge = MicBridge(publish, enabled=False)
        await bridge.start()

        data = _last_data_for(publish, "hive/system/metrics/hardware/mic")
        assert data == {"status": "unavailable", "reason": "disabled_by_config"}
        assert bridge.available is False
        await bridge.stop()

    async def test_import_error_publishes_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Block sounddevice from importing even if it were installed.
        monkeypatch.setitem(sys.modules, "sounddevice", None)
        publish = AsyncMock()
        bridge = MicBridge(publish, enabled=True)
        await bridge.start()

        data = _last_data_for(publish, "hive/system/metrics/hardware/mic")
        assert data is not None
        assert data["status"] == "unavailable"
        assert data["reason"] == "sounddevice_not_installed"
        assert bridge.available is False
        await bridge.stop()

    async def test_disabled_path_emits_warning(self) -> None:
        """Spec §E.8: a disabled/unavailable bridge must emit a structlog WARNING."""
        publish = AsyncMock()
        bridge = MicBridge(publish, enabled=False)
        with structlog.testing.capture_logs() as cap:
            await bridge.start()
        assert any(
            e.get("event") == "mic_bridge_unavailable" and e.get("log_level") == "warning"
            for e in cap
        ), f"Expected 'mic_bridge_unavailable' warning; got: {cap}"


# ---------------------------------------------------------------------------
# CameraBridge
# ---------------------------------------------------------------------------

class TestCameraBridge:
    async def test_disabled_publishes_unavailable(self) -> None:
        publish = AsyncMock()
        bridge = CameraBridge(publish, enabled=False)
        await bridge.start()

        data = _last_data_for(publish, "hive/system/metrics/hardware/camera")
        assert data == {"status": "unavailable", "reason": "disabled_by_config"}
        assert bridge.available is False
        await bridge.stop()

    async def test_import_error_publishes_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "cv2", None)
        publish = AsyncMock()
        bridge = CameraBridge(publish, enabled=True)
        await bridge.start()

        data = _last_data_for(publish, "hive/system/metrics/hardware/camera")
        assert data is not None
        assert data["status"] == "unavailable"
        assert data["reason"] == "cv2_not_installed"
        assert bridge.available is False
        await bridge.stop()


# ---------------------------------------------------------------------------
# SpeakerBridge
# ---------------------------------------------------------------------------

class TestSpeakerBridge:
    async def test_disabled_publishes_unavailable(self) -> None:
        publish = AsyncMock()
        bridge = SpeakerBridge(publish, enabled=False)
        await bridge.start()

        data = _last_data_for(publish, "hive/system/metrics/hardware/speaker")
        assert data == {"status": "unavailable", "reason": "disabled_by_config"}
        assert bridge.available is False

    async def test_handle_message_when_unavailable_drops(self) -> None:
        publish = AsyncMock()
        bridge = SpeakerBridge(publish, enabled=False)
        await bridge.start()

        # handle_message on an unavailable bridge must not raise.
        env = Envelope.new(
            source_region="glia",
            topic="hive/hardware/speaker",
            content_type="application/json",
            data={"wav": "stub"},
        )
        await bridge.handle_message(env)  # no exception = pass
        await bridge.stop()


# ---------------------------------------------------------------------------
# MotorBridge
# ---------------------------------------------------------------------------

class TestMotorBridge:
    async def test_disabled_publishes_unavailable(self) -> None:
        publish = AsyncMock()
        bridge = MotorBridge(publish, enabled=False)
        await bridge.start()

        data = _last_data_for(publish, "hive/system/metrics/hardware/motor")
        assert data == {"status": "unavailable", "reason": "disabled_by_config"}

    async def test_handle_message_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        publish = AsyncMock()
        bridge = MotorBridge(publish, enabled=True)
        await bridge.start()

        env = Envelope.new(
            source_region="glia",
            topic="hive/hardware/motor",
            content_type="application/hive+motor-intent",
            data={"action": "turn_left", "magnitude": 0.5},
        )
        with structlog.testing.capture_logs() as cap:
            await bridge.handle_message(env)
        await bridge.stop()

        # Verify the motor_action log event fired.
        assert any(e.get("event") == "motor_action" for e in cap)
