"""End-to-end: publish to a real broker, observe it via the WebSocket.

Boots ``eclipse-mosquitto:2`` via testcontainers, brings up the observatory
FastAPI app (real lifespan, real aiomqtt subscriber), connects a WebSocket
client, publishes one envelope from a separate aiomqtt client, and asserts
the envelope arrives on the WS stream.

We publish with ``retain=True`` to eliminate a subscribe/publish race: the
observatory's subscriber connects + subscribes asynchronously inside the
lifespan's background task. An unretained publish that arrives before
subscribe completes would be dropped by the broker. Retained messages are
delivered to any client that subscribes to the matching topic immediately
on subscription, which makes the test deterministic. See
``observatory/memory/decisions.md`` for the rationale.

Note on the mosquitto config: the default config shipped by
``testcontainers[mqtt]`` includes both ``protocol mqtt`` (which creates a
default listener on port 1883) AND an explicit ``listener 1883``, which
collides on ``eclipse-mosquitto:2`` — the broker terminates with "Address
in use" and the wait-for-logs predicate ("mosquitto version X running")
never matches. We therefore hand the container a minimal, correct config
via ``MosquittoContainer.start(configfile=...)``.

The ``broker_url`` fixture is module-scoped so v1's WS flow and v2's REST
flow share a single container. Starting mosquitto is the expensive part of
a component run; we pay it once per test module.
"""
from __future__ import annotations

import dataclasses
import json
import socket
from collections.abc import Iterator
from pathlib import Path

import aiomqtt
import pytest
from starlette.testclient import TestClient
from testcontainers.mqtt import MosquittoContainer

from observatory.config import Settings
from observatory.service import build_app

pytestmark = pytest.mark.component


_MOSQUITTO_CONF = """\
listener 1883
allow_anonymous true
persistence false
log_dest stdout
log_type error
log_type warning
log_type notice
log_type information
"""


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _seed_regions(root: Path) -> None:
    """Lay down a minimal ``testregion`` under ``root`` for v2 endpoint tests.

    Mirrors the unit-suite fixture shape (``observatory/tests/unit/conftest.py``)
    but trimmed to the fields the plan's assertions reference: ``llm_model`` +
    ``api_key`` in config.yaml (secret redaction) and a single on_wake.py
    handler (tree listing).
    """
    region = root / "testregion"
    (region / "memory").mkdir(parents=True)
    (region / "handlers").mkdir()
    (region / "prompt.md").write_text("hello\n", encoding="utf-8")
    (region / "memory" / "stm.json").write_text(
        json.dumps({"n": 1}), encoding="utf-8"
    )
    (region / "subscriptions.yaml").write_text(
        "topics: [hive/modulator/+]\n", encoding="utf-8"
    )
    (region / "config.yaml").write_text(
        "llm_model: fake\napi_key: shh\n", encoding="utf-8",
    )
    (region / "handlers" / "on_wake.py").write_text(
        "def handle():\n    pass\n", encoding="utf-8"
    )


@pytest.fixture(scope="module")
def broker_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Stand up mosquitto once per test module; yield ``mqtt://host:port``.

    Module scope keeps the container alive across both the v1 WS test and
    the v2 REST test — mosquitto startup is the dominant cost of this file.
    """
    conf_dir = tmp_path_factory.mktemp("mosquitto_conf")
    conf_path = conf_dir / "mosquitto.conf"
    conf_path.write_text(_MOSQUITTO_CONF, encoding="utf-8")

    broker = MosquittoContainer(image="eclipse-mosquitto:2")
    broker.start(configfile=str(conf_path))
    try:
        host = broker.get_container_host_ip()
        port = int(broker.get_exposed_port(1883))
        yield f"mqtt://{host}:{port}"
    finally:
        broker.stop()


@pytest.mark.asyncio
async def test_publish_reaches_websocket(tmp_path, broker_url) -> None:
    # Parse back the URL so the aiomqtt publisher below can target the same
    # broker without duplicating the fixture's work.
    assert broker_url.startswith("mqtt://")
    host_port = broker_url[len("mqtt://"):]
    broker_host, _, port_s = host_port.partition(":")
    broker_port = int(port_s)

    settings = Settings(
        bind_host="127.0.0.1",
        bind_port=_free_port(),
        mqtt_url=broker_url,
        ring_buffer_size=100,  # noqa: PLR2004 — component-test magic
        max_ws_rate=200,  # noqa: PLR2004 — component-test magic
        hive_repo_root=tmp_path,
    )

    app = build_app(settings)
    client = TestClient(app)

    # starlette 1.0's TestClient only supports sync `with`, not
    # `async with` — but `with client:` still drives the real
    # lifespan via its internal anyio portal (startup on __enter__,
    # shutdown on __exit__), so the subscriber task is connected
    # and running for the duration of the block.
    with client, client.websocket_connect("/ws") as ws:
        snap = ws.receive_json()
        assert snap["type"] == "snapshot"

        envelope = {
            "id": "abc",
            "timestamp": "2026-04-20T00:00:00.000Z",
            "source_region": "thalamus",
            "topic": "hive/cognitive/prefrontal/plan",
            "payload": {"x": 1},
        }
        async with aiomqtt.Client(
            hostname=broker_host, port=broker_port
        ) as pub:
            # retain=True so a late subscriber still sees the
            # message on subscribe — eliminates the race.
            await pub.publish(
                "hive/cognitive/prefrontal/plan",
                payload=json.dumps(envelope).encode(),
                retain=True,
            )

        # Drain up to N messages from the WS until we see our
        # envelope. The delta loop also emits `region_delta` /
        # `adjacency` frames on a 1 Hz cadence, so we have to
        # skip past those. `receive_json()` blocks — retain=True
        # guarantees the envelope eventually lands.
        received = None
        drained: list[dict] = []
        for _ in range(50):  # noqa: PLR2004 — drain budget
            msg = ws.receive_json()
            drained.append(
                {
                    "type": msg.get("type"),
                    "topic": msg.get("payload", {}).get("topic"),
                }
            )
            if msg["type"] == "envelope" and msg["payload"]["topic"] == (
                "hive/cognitive/prefrontal/plan"
            ):
                received = msg
                break
        assert received is not None, (
            f"envelope never arrived on the WS stream; drained "
            f"{len(drained)} messages: {drained}"
        )
        assert received["payload"]["source_region"] == "thalamus"


def test_v2_endpoints_over_real_service(tmp_path, broker_url) -> None:
    """v2 REST surface (/config redaction, /handlers tree) over a real broker.

    Reuses the module-scoped ``broker_url`` fixture so this does not spin up
    a second mosquitto. The app connects to the real broker through its
    lifespan (we still need ``with TestClient(app) as client`` to drive
    startup), but the actual assertions target the filesystem-backed REST
    endpoints seeded via ``_seed_regions``.
    """
    regions_root = tmp_path / "regions"
    _seed_regions(regions_root)

    # hive_repo_root points at an empty dir so the registry seeds empty
    # (no glia/regions_registry.yaml to bleed in); we then populate
    # ``testregion`` directly via apply_heartbeat to pass the
    # ``_ensure_region`` short-circuit on each v2 route.
    empty_root = tmp_path / "empty_hive_root"
    empty_root.mkdir()

    settings = dataclasses.replace(
        Settings(),
        bind_host="127.0.0.1",
        bind_port=_free_port(),
        mqtt_url=broker_url,
        regions_root=regions_root,
        hive_repo_root=empty_root,
        ring_buffer_size=100,  # noqa: PLR2004 — component-test magic
        max_ws_rate=200,  # noqa: PLR2004 — component-test magic
    )
    app = build_app(settings)

    with TestClient(app) as client:
        # Same seeding pattern the unit tests use (see
        # observatory/tests/unit/test_api_regions_v2.py::client).
        app.state.registry.apply_heartbeat("testregion", {"phase": "wake"})

        r = client.get("/api/regions/testregion/config")
        assert r.status_code == 200  # noqa: PLR2004
        body = r.json()
        assert body["api_key"] == "***"
        assert body["llm_model"] == "fake"
        assert r.headers["cache-control"] == "no-store"

        r = client.get("/api/regions/testregion/handlers")
        assert r.status_code == 200  # noqa: PLR2004
        assert len(r.json()) == 1
        assert r.headers["cache-control"] == "no-store"
