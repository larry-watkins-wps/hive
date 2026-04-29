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
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiomqtt
import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from observatory.adjacency import Adjacency
from observatory.api import build_router
from observatory.config import Settings
from observatory.mqtt_subscriber import MqttSubscriber, load_subscription_map
from observatory.region_reader import RegionReader
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer
from observatory.sensory.publisher import SensoryPublisher
from observatory.sensory.routes import build_sensory_router
from observatory.types import RingRecord
from observatory.ws import ConnectionHub, build_ws_router

log = structlog.get_logger(__name__)

_SHUTDOWN_TIMEOUT_S = 2.0
# Reconnect backoff — matches region_template/mqtt_client.py's §B.10 shape
# (1s, 2s, 4s, ... capped at 30s). The observatory never gives up: unlike
# a region, a dead MQTT feed is recoverable without data loss (ring buffer
# simply has a gap), so we prefer "eventually catch up" over "crash the
# container and have the orchestrator restart us".
_RECONNECT_BACKOFF_INITIAL_S = 1.0
_RECONNECT_BACKOFF_CAP_S = 30.0

# Watchdog: force a reconnect if the subscriber's `messages_received_total`
# counter stops incrementing. aiomqtt 2.5.1's async iterator can silently
# wait forever when paho's internal `loop_read` degrades without firing
# `on_disconnect` — the client looks connected, no MqttError is raised,
# and the reconnect loop in `_mqtt_run_with_reconnect` has no trigger to
# act on. Hive's normal traffic (heartbeats alone, one per region per
# second) is ~14 msg/s, so a 20 s gap with zero messages is unambiguously
# a stall, not a quiet broker. The watchdog cancels the subscriber task;
# the outer reconnect loop then builds a fresh aiomqtt client.
_WATCHDOG_STALL_THRESHOLD_S = 20.0
_WATCHDOG_POLL_INTERVAL_S = 5.0


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


def _backoff_delay(attempt: int, *, initial: float, cap: float) -> float:
    """Exponential backoff with a ceiling. Pure function, independently tested.

    ``attempt=0 → initial``, ``attempt=1 → 2*initial``, doubling until ``cap``.
    """
    return min(cap, initial * (2 ** attempt))


async def _run_subscriber_with_watchdog(
    *,
    client: aiomqtt.Client,
    subscriber: Any,
    stop_event: asyncio.Event,
) -> None:
    """Run ``subscriber.run(client, stop_event)`` with a stall-watchdog.

    aiomqtt's async iterator (``client.messages``) waits forever on the
    internal queue when paho's ``loop_read`` degrades silently — no
    ``on_disconnect`` fires, no ``MqttError`` is raised, and the outer
    reconnect loop has nothing to react to. The watchdog polls
    ``subscriber.messages_received_total`` every
    ``_WATCHDOG_POLL_INTERVAL_S`` and cancels the subscriber if the
    counter hasn't moved in ``_WATCHDOG_STALL_THRESHOLD_S``. A cancel
    bubbles up as ``CancelledError``, which this function converts to a
    normal return so ``_mqtt_run_with_reconnect`` can loop and rebuild
    the client.

    The watchdog only arms once at least one message has been seen on
    this connection — that avoids a false-positive reconnect storm on a
    genuinely quiet broker right after boot.
    """
    sub_task = asyncio.create_task(subscriber.run(client, stop_event))
    try:
        last_total = subscriber.messages_received_total
        last_change_ts = asyncio.get_running_loop().time()
        while not sub_task.done():
            # Use wait() rather than wait_for(shield(...)) so we don't
            # accumulate a shield wrapper per iteration. FIRST_COMPLETED
            # returns immediately when sub_task finishes on its own.
            await asyncio.wait(
                {sub_task}, timeout=_WATCHDOG_POLL_INTERVAL_S,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if sub_task.done():
                return  # subscriber finished on its own (stop_event)
            now = asyncio.get_running_loop().time()
            cur_total = subscriber.messages_received_total
            if cur_total != last_total:
                last_total = cur_total
                last_change_ts = now
                continue
            if cur_total == 0:
                last_change_ts = now
                continue
            if now - last_change_ts >= _WATCHDOG_STALL_THRESHOLD_S:
                log.warning(
                    "observatory.mqtt_stall_detected",
                    messages_received_total=cur_total,
                    stall_seconds=round(now - last_change_ts, 1),
                    action="force_reconnect",
                )
                sub_task.cancel()
                break
    finally:
        if not sub_task.done():
            sub_task.cancel()
        # Swallow CancelledError from the subscriber — it's the watchdog's
        # doing, not a programmer bug. Any other exception propagates to
        # the reconnect loop's MqttError handler (or up, for non-MQTT bugs).
        with contextlib.suppress(asyncio.CancelledError):
            await sub_task


async def _mqtt_run_with_reconnect(
    *,
    client_factory: Callable[[], aiomqtt.Client],
    subscriber: Any,
    stop_event: asyncio.Event,
    backoff_initial_s: float = _RECONNECT_BACKOFF_INITIAL_S,
    backoff_cap_s: float = _RECONNECT_BACKOFF_CAP_S,
) -> None:
    """Run the subscriber against the broker, reconnecting on broker failure.

    On :class:`aiomqtt.MqttError` (initial connect, subscribe, or mid-stream
    iteration) the loop logs a warning, sleeps with exponential backoff, and
    reopens with a fresh client. The backoff counter resets after a
    successful connect, so a one-off disconnect doesn't penalize the next
    one. Non-MqttError exceptions propagate so programmer bugs are loud.

    Exits when ``stop_event`` fires — either mid-session (the subscriber's
    own stop check breaks its loop) or mid-backoff (this function wakes
    early from its sleep).
    """
    attempt = 0
    while not stop_event.is_set():
        try:
            client = client_factory()
            async with client:
                await client.subscribe("hive/#")
                if attempt > 0:
                    log.info("observatory.mqtt_reconnected", attempts=attempt)
                else:
                    log.info("observatory.mqtt_connected")
                attempt = 0
                await _run_subscriber_with_watchdog(
                    client=client, subscriber=subscriber, stop_event=stop_event
                )
            # Clean exit from subscriber.run — either stop_event fired (shutdown)
            # or the watchdog forced a reconnect due to a silent stall. Loop
            # back and reopen unless shutdown was requested.
            if stop_event.is_set():
                return
        except aiomqtt.MqttError as err:
            if stop_event.is_set():
                return
            delay = _backoff_delay(
                attempt, initial=backoff_initial_s, cap=backoff_cap_s
            )
            log.warning(
                "observatory.mqtt_disconnected",
                attempt=attempt,
                delay_s=delay,
                err=str(err),
            )
            attempt += 1
            # Sleep with early-wake on stop_event. ``asyncio.wait_for`` returns
            # when the event fires, raises ``TimeoutError`` when the delay
            # expires — either branch cleanly resolves to "should I retry?".
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
                return
            except TimeoutError:
                continue


def build_app(settings: Settings) -> FastAPI:  # noqa: PLR0915 — composition factory
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
    # v2 Task 4 — sandboxed per-region filesystem reader. Built eagerly so
    # that an invalid `regions_root` fails fast at service startup rather
    # than on the first v2 REST request. The reader is attached to
    # `app.state` below (alongside the registry) so tests can swap it.
    reader = RegionReader(settings.regions_root)

    # Monkey-patch subscriber.dispatch so every newly ingested envelope also
    # fans out to WebSocket clients via the hub. `MqttSubscriber.run()`
    # calls `self.dispatch(message)`, and because we assign the wrapper as
    # an instance attribute, normal attribute lookup finds it before the
    # class method (plan-authoritative — see observatory/prompts/task-07).
    original_dispatch = subscriber.dispatch

    async def dispatch_and_fanout(msg: object) -> None:
        # Trigger broadcast on the subscriber's success counter, not on
        # ring length. Once the deque fills to `ring_buffer_size` (default
        # 10 000, ≈20 s at 500 msg/s), `len(ring)` stops growing because
        # `deque.maxlen` caps it — making `post_len > pre_len` permanently
        # false and silently killing all envelope broadcasts. The counter
        # increments once per successful dispatch regardless of ring
        # fullness, and `ring.last()` is O(1) vs. `snapshot()[-1]`'s O(N).
        pre_count = subscriber.messages_received_total
        await original_dispatch(msg)
        if subscriber.messages_received_total > pre_count:
            rec = ring.last()
            if rec is not None:
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

        # Fresh client per (re)connect. aiomqtt.Client instances aren't
        # re-enterable after __aexit__, so the reconnect loop must build a
        # new one each attempt.
        def client_factory() -> aiomqtt.Client:
            return aiomqtt.Client(
                hostname=host, port=port, identifier=f"observatory-{host}-{port}"
            )

        await hub.start()
        task: asyncio.Task | None = None

        task = asyncio.create_task(
            _mqtt_run_with_reconnect(
                client_factory=client_factory,
                subscriber=subscriber,
                stop_event=stop_event,
            )
        )

        def _on_mqtt_task_done(t: asyncio.Task) -> None:
            """Surface unrecoverable failures loudly.

            The reconnect loop swallows ``aiomqtt.MqttError`` and retries, so
            we only see exceptions here for truly unexpected failures
            (programmer bugs, non-MQTT crashes). Cancellation during shutdown
            is normal and ignored.
            """
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                log.error("observatory.mqtt_task_crashed", exc_info=exc)

        task.add_done_callback(_on_mqtt_task_done)

        sensory_publisher = SensoryPublisher(settings)
        await sensory_publisher.connect()
        _app.state.sensory_publisher = sensory_publisher
        _app.state.settings = settings

        try:
            yield
        finally:
            # Signal the subscriber loop, stop the hub's delta task, then
            # await the MQTT task's cancellation with a bounded timeout so
            # a stuck broker-disconnect doesn't hang shutdown. CancelledError
            # and TimeoutError are both swallowed — the task is being torn
            # down and neither outcome is actionable here.
            await sensory_publisher.disconnect()
            stop_event.set()
            await hub.stop()
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                    await asyncio.wait_for(task, timeout=_SHUTDOWN_TIMEOUT_S)
            log.info("observatory.shutdown_complete")

    app = FastAPI(lifespan=lifespan, title="Hive Observatory", version="0.1.0")

    # Spec §6.2 requires error bodies of shape {"error", "message"} (not
    # wrapped under {"detail": ...}) and `Cache-Control: no-store` on ALL
    # responses — including errors. FastAPI's default HTTPException handler
    # emits neither. This custom handler:
    #   1. Unwraps dict `detail` (v2 handlers raise HTTPException with
    #      {"error", "message"} as `detail`) to the top-level body.
    #   2. Leaves legacy/string `detail` alone via the standard wrapper
    #      (no v1 code currently takes this path, but preserving it is
    #      defensive against future additions).
    #   3. Attaches Cache-Control: no-store to every error response.
    @app.exception_handler(StarletteHTTPException)
    async def _observatory_http_exc_handler(
        _request: Request, exc: StarletteHTTPException,
    ) -> JSONResponse:
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            body: dict = exc.detail
        else:
            body = {"detail": exc.detail}
        return JSONResponse(
            body,
            status_code=exc.status_code,
            headers={"Cache-Control": "no-store"},
        )

    # Attach singletons to `app.state` so the v2 REST handlers (and tests
    # that want to swap them) have a stable access point. v1's routes still
    # use the closure-captured `registry`; v2's use `request.app.state.*`.
    app.state.registry = registry
    app.state.reader = reader
    # Routers MUST be registered before the `/` static mount — FastAPI
    # resolves routes in registration order and a `/` mount registered
    # first would shadow `/api/*` and `/ws`.
    app.include_router(build_router(region_registry=registry))
    app.include_router(build_sensory_router())
    app.include_router(build_ws_router(hub))

    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app
