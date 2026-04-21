"""FastAPI app factory for the observatory.

Wires together the ring buffer, retained cache, region registry, adjacency
tracker, MQTT subscriber, and WebSocket ConnectionHub into a single FastAPI
application. The app's `lifespan` hook connects to the broker, subscribes
`hive/#`, starts the ConnectionHub's delta loop, and drains cleanly on
shutdown.
"""
from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

import aiomqtt
import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from observatory.adjacency import Adjacency
from observatory.api import build_router
from observatory.config import Settings
from observatory.mqtt_subscriber import MqttSubscriber, load_subscription_map
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer
from observatory.types import RingRecord
from observatory.ws import ConnectionHub, build_ws_router

log = structlog.get_logger(__name__)

_SHUTDOWN_TIMEOUT_S = 2.0


def _parse_mqtt_url(url: str) -> tuple[str, int]:
    """Split an MQTT URL into (host, port).

    Handles ``mqtt://host:port``, ``mqtt://host`` (→ default 1883), and
    ``mqtts://host:port`` (parsed but TLS is not wired in v1; see
    ``build_app`` below). Malformed URLs (no scheme) will raise
    ``IndexError``; the caller is responsible for validation.
    """
    rest = url.split("://", 1)[1]
    host, _, port_s = rest.partition(":")
    return host, int(port_s or "1883")


def build_app(settings: Settings) -> FastAPI:
    """Construct the observatory FastAPI app.

    The factory is synchronous and does not touch the network — it merely
    wires instances and returns an app whose `lifespan` will connect to
    the broker once an ASGI runtime starts it. This keeps the smoke test
    (`python -c "... build_app(Settings())"`) side-effect-free.
    """
    ring = RingBuffer(capacity=settings.ring_buffer_size)
    cache = RetainedCache()
    registry = RegionRegistry.seed_from(settings.hive_repo_root)
    adjacency = Adjacency(window_seconds=5.0)
    sub_map = load_subscription_map(settings.hive_repo_root)
    subscriber = MqttSubscriber(ring, cache, registry, adjacency, sub_map)
    hub = ConnectionHub(ring, cache, registry, adjacency, max_ws_rate=settings.max_ws_rate)

    # Monkey-patch subscriber.dispatch so every newly ingested envelope also
    # fans out to WebSocket clients via the hub. `MqttSubscriber.run()`
    # calls `self.dispatch(message)`, and because we assign the wrapper as
    # an instance attribute, normal attribute lookup finds it before the
    # class method (plan-authoritative — see observatory/prompts/task-07).
    original_dispatch = subscriber.dispatch

    async def dispatch_and_fanout(msg: object) -> None:
        pre_len = len(ring)
        await original_dispatch(msg)
        post_len = len(ring)
        if post_len > pre_len:
            rec: RingRecord = ring.snapshot()[-1]
            await hub.broadcast_envelope(rec)

    subscriber.dispatch = dispatch_and_fanout  # type: ignore[method-assign]

    stop_event = asyncio.Event()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):  # noqa: ARG001
        host, port = _parse_mqtt_url(settings.mqtt_url)
        if settings.mqtt_url.startswith("mqtts://"):
            # v1 does not wire TLS — document the gap so deploy doesn't silently
            # downgrade. TLS is a v1.1 follow-up (see decisions.md).
            log.warning(
                "observatory.mqtts_scheme_no_tls",
                host=host,
                port=port,
                note="mqtts:// URL given but TLS is not configured in v1",
            )
        client = aiomqtt.Client(
            hostname=host, port=port, identifier=f"observatory-{host}-{port}"
        )
        await hub.start()
        task: asyncio.Task | None = None

        async def _run() -> None:
            async with client:
                await client.subscribe("hive/#")
                await subscriber.run(client, stop_event)

        task = asyncio.create_task(_run())
        try:
            yield
        finally:
            # Signal the subscriber loop, stop the hub's delta task, then
            # await the MQTT task's cancellation with a bounded timeout so
            # a stuck broker-disconnect doesn't hang shutdown. CancelledError
            # and TimeoutError are both swallowed — the task is being torn
            # down and neither outcome is actionable here.
            stop_event.set()
            await hub.stop()
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                    await asyncio.wait_for(task, timeout=_SHUTDOWN_TIMEOUT_S)
            log.info("observatory.shutdown_complete")

    app = FastAPI(lifespan=lifespan, title="Hive Observatory", version="0.1.0")
    # Routers MUST be registered before the `/` static mount — FastAPI
    # resolves routes in registration order and a `/` mount registered
    # first would shadow `/api/*` and `/ws`.
    app.include_router(build_router(region_registry=registry))
    app.include_router(build_ws_router(hub))

    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app
