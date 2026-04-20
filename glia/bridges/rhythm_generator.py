"""Rhythm generator — spec §E.7.

Publishes three rhythm topics as independent asyncio tasks:

    hive/rhythm/gamma  ~40 Hz
    hive/rhythm/beta   ~20 Hz
    hive/rhythm/theta   ~6 Hz

Jitter of ±10% is acceptable per spec (neural rhythms jitter; no
tight-loop scheduler required). Each tick publishes a JSON envelope
with ``beat`` (monotonically increasing int), ``hz`` (nominal), and
``ts`` (wall-clock float seconds).
"""
from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)

RHYTHMS: dict[str, float] = {
    "hive/rhythm/gamma": 40.0,
    "hive/rhythm/beta": 20.0,
    "hive/rhythm/theta": 6.0,
}
JITTER_PCT = 0.1  # ±10%

PublishFn = Callable[..., Awaitable[None]]


class RhythmGenerator:
    """Emits rhythm envelopes on three topics at ~40/20/6 Hz."""

    name = "rhythm_generator"

    def __init__(self, publish: PublishFn) -> None:
        self._publish = publish
        self._tasks: list[asyncio.Task[Any]] = []
        self._stopping = False

    async def start(self) -> None:
        """Spawn one asyncio task per rhythm topic. Idempotent-safe."""
        if self._tasks:
            # Already running — don't double-spawn.
            return
        self._stopping = False
        self._tasks = [
            asyncio.create_task(
                self._emit(topic, hz),
                name=f"rhythm-{topic.rsplit('/', 1)[1]}",
            )
            for topic, hz in RHYTHMS.items()
        ]

    async def stop(self) -> None:
        """Cancel and await all rhythm tasks."""
        self._stopping = True
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def _emit(self, topic: str, hz: float) -> None:
        period = 1.0 / hz
        beat = 0
        try:
            while not self._stopping:
                envelope = Envelope.new(
                    source_region="glia",
                    topic=topic,
                    content_type="application/json",
                    data={"beat": beat, "hz": hz, "ts": time.time()},
                )
                try:
                    await self._publish(envelope, qos=0, retain=False)
                except Exception:  # noqa: BLE001 — keep ticking even if publish fails
                    log.warning("rhythm_publish_failed", topic=topic, beat=beat)
                beat += 1
                jittered = period * (1.0 + random.uniform(-JITTER_PCT, JITTER_PCT))
                await asyncio.sleep(jittered)
        except asyncio.CancelledError:
            # Normal path on stop().
            raise
