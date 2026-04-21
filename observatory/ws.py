"""WebSocket fan-out: snapshot-on-connect + live envelope stream + periodic deltas."""
from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from observatory import __version__
from observatory.adjacency import Adjacency
from observatory.decimator import Decimator
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer
from observatory.types import RingRecord

log = structlog.get_logger(__name__)

_DELTA_INTERVAL_S = 2.0
_QUEUE_HIGH_WATER = 1000
_RECENT_SNAPSHOT_LIMIT = 500


@dataclass(eq=False)
class _Client:
    """Per-connection fan-out state.

    ``eq=False`` so instances keep default identity-based ``__hash__``; we
    store them in a ``set`` on the hub.
    """
    ws: WebSocket
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    decimator: Decimator | None = None
    # Envelopes dropped since the last `decimated` emit — reported and reset
    # by ``_delta_loop`` so the UI can surface backpressure.
    dropped_since_last_delta: int = 0


def _ring_record_to_payload(rec: RingRecord) -> dict[str, Any]:
    return {
        "observed_at": rec.observed_at,
        "topic": rec.topic,
        "envelope": rec.envelope,
        "source_region": rec.source_region,
        "destinations": list(rec.destinations),
    }


class ConnectionHub:
    """Per-connection fan-out manager.

    One ``_Client`` per WS connection, each with its own queue + decimator.
    ``serve(ws)`` is the entry point wired by ``build_ws_router``. A single
    background ``_delta_task`` emits ``region_delta`` + ``adjacency`` messages
    to every connected client every ``_DELTA_INTERVAL_S`` seconds, plus a
    per-client ``decimated`` summary whenever envelopes were dropped since
    the previous tick; start it via ``start()`` and cancel it via ``stop()``
    from the app's lifespan hooks (Task 7).
    """

    def __init__(
        self,
        ring: RingBuffer,
        cache: RetainedCache,
        registry: RegionRegistry,
        adjacency: Adjacency,
        max_ws_rate: int,
    ) -> None:
        self.ring = ring
        self.cache = cache
        self.registry = registry
        self.adjacency = adjacency
        self._max_ws_rate = max_ws_rate
        self._clients: set[_Client] = set()
        self._delta_task: asyncio.Task | None = None

    def snapshot_message(self) -> dict[str, Any]:
        recent_records = self.ring.snapshot()[-_RECENT_SNAPSHOT_LIMIT:]
        return {
            "type": "snapshot",
            "payload": {
                "regions": self.registry.to_json(),
                "retained": self.cache.snapshot(),
                "recent": [_ring_record_to_payload(r) for r in recent_records],
                "server_version": __version__,
            },
        }

    async def broadcast_envelope(self, rec: RingRecord) -> None:
        payload = _ring_record_to_payload(rec)
        msg = {"type": "envelope", "payload": payload}
        now = time.monotonic()
        for c in list(self._clients):
            if c.decimator and not c.decimator.should_keep(payload, now=now):
                c.dropped_since_last_delta += 1
                continue
            if c.queue.qsize() > _QUEUE_HIGH_WATER:
                # Slow client — drop to protect the hub from head-of-line blocking.
                c.dropped_since_last_delta += 1
                continue
            await c.queue.put(msg)

    async def _delta_loop(self) -> None:
        """Emit `adjacency`, `region_delta`, and (per-client) `decimated` every tick.

        Wrapped in `try/except Exception` so a bug in any collaborator doesn't
        silently kill the whole delta stream. A slow client's full queue no
        longer stalls delta delivery to other clients — we use ``put_nowait``
        and drop on ``QueueFull``.
        """
        while True:
            try:
                await asyncio.sleep(_DELTA_INTERVAL_S)
                pairs = self.adjacency.snapshot(now=time.monotonic())
                adjacency_msg = {
                    "type": "adjacency",
                    "payload": {"pairs": [[s, d, round(r, 3)] for s, d, r in pairs]},
                }
                region_msg = {
                    "type": "region_delta",
                    "payload": {"regions": self.registry.to_json()},
                }
                for c in list(self._clients):
                    _enqueue_nonblocking(c, adjacency_msg)
                    _enqueue_nonblocking(c, region_msg)
                    if c.dropped_since_last_delta > 0:
                        decimated_msg = {
                            "type": "decimated",
                            "payload": {"dropped": c.dropped_since_last_delta},
                        }
                        _enqueue_nonblocking(c, decimated_msg)
                        c.dropped_since_last_delta = 0
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — keep the delta loop alive on errors
                log.exception("observatory.delta_loop_error")

    async def start(self) -> None:
        if self._delta_task is None:
            self._delta_task = asyncio.create_task(self._delta_loop())

    async def stop(self) -> None:
        if self._delta_task is not None:
            self._delta_task.cancel()
            self._delta_task = None

    async def serve(self, ws: WebSocket) -> None:
        await ws.accept()
        client = _Client(ws=ws, decimator=Decimator(max_rate=self._max_ws_rate))
        self._clients.add(client)
        try:
            await ws.send_json(self.snapshot_message())
            while True:
                msg = await client.queue.get()
                await ws.send_json(msg)
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            log.exception("observatory.ws_error")
        finally:
            self._clients.discard(client)


def _enqueue_nonblocking(client: _Client, msg: dict[str, Any]) -> None:
    """Put `msg` on a client's queue without blocking.

    Used by the delta loop — one frozen tab must not stall delivery to
    every other client. If the queue is already over high-water we silently
    drop the delta message (the client will get the next tick's delta; its
    envelope-drop counter already surfaces the backpressure via `decimated`).
    """
    if client.queue.qsize() > _QUEUE_HIGH_WATER:
        return
    with contextlib.suppress(asyncio.QueueFull):
        client.queue.put_nowait(msg)


def build_ws_router(hub: ConnectionHub) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await hub.serve(ws)

    return router
