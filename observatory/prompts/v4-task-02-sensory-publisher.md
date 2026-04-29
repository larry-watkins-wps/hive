# v4 Task 2 — SensoryPublisher

You are implementing Task 2 of the observatory v4 plan. Read this prompt in full before touching any file. The spec is authoritative when prose conflicts.

## Your role

Implement Task 2 only. Drive to a green test suite + clean ruff + a single commit, then stop.

## Working directory

`C:/repos/hive`. Use `C:/repos/hive/.venv/Scripts/python.exe` for python invocations (system python lacks pytest).

Use forward slashes and Unix shell syntax. Never `cd` (paths are absolute).

## Predecessor state

Task 1 already landed (commit `370db6f`):
- `observatory/sensory/__init__.py` exists.
- `observatory/sensory/allowlist.py` exports `ALLOWED_PUBLISH_TOPICS: frozenset[str] = frozenset({"hive/external/perception"})`.
- `observatory/sensory/errors.py` exports `ForbiddenTopicError(topic)` (with `.topic` attr) and `PublishFailedError(cause)` (with `.cause` attr; `str(err) == str(cause)`).
- `observatory/config.py::Settings` has `chat_default_speaker`, `chat_publish_qos`, `chat_text_max_length` fields plus `mqtt_url: str = "mqtt://127.0.0.1:1883"` (existing).

## Architecture note

`SensoryPublisher` owns a long-lived `aiomqtt.Client` connection. The FastAPI lifespan in Task 3 will bring it up at startup and tear it down at shutdown. The MQTT *subscriber* (`observatory/mqtt_subscriber.py`) uses a *separate* aiomqtt client — read and write surfaces stay independent (spec §11).

## Spec excerpts (authoritative)

### §4.3 Publisher

```python
class SensoryPublisher:
    def __init__(self, settings: Settings) -> None: ...
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def publish(self, envelope: Envelope, *, qos: int = 1) -> None: ...
```

- Reuses `aiomqtt` at the same pinned version as `region_template/mqtt_client.py`.
- Connects on FastAPI `startup` event; disconnects on `shutdown`.
- `publish()` validates `envelope.topic ∈ ALLOWED_PUBLISH_TOPICS`, serialises via `envelope.to_json()` (UTF-8 JSON bytes), publishes with `qos=1` default. The envelope itself carries `source_region`, `id`, `timestamp` — the publisher does not synthesise those.
- On `aiomqtt.MqttError`, raises `PublishFailedError` wrapping the original.

### §3.2 Envelope (relevant for tests)

`Envelope.new(source_region=..., topic=..., content_type="application/json", data={...})` — factory in `src/shared/message_envelope.py`. Generates `id` (UUID v4) and `timestamp` (ISO-8601 ms-precision UTC). `Envelope.to_json()` returns UTF-8 bytes via `json.dumps(asdict(self)).encode("utf-8")`.

## Existing-contract surface

`shared.message_envelope.Envelope` is importable as `from shared.message_envelope import Envelope` (workspace conftest adds repo root to sys.path; `src/shared/` is on PYTHONPATH=src in CI). Test files in `observatory/tests/unit/` already use this import path successfully.

`aiomqtt 2.5+` is in `observatory/pyproject.toml`. The `aiomqtt.MqttError` exception hierarchy is the base; `aiomqtt.MqttCodeError` is a subclass for CONNACK errors. Catching `MqttError` catches both.

`structlog.get_logger(__name__)` is the existing observatory logger pattern (see `observatory/service.py:36`).

## Step-by-step

### Step 1 — Write the publisher tests (TDD red phase)

Create `observatory/tests/unit/sensory/test_publisher.py`:

```python
"""SensoryPublisher behaviour: allowlist + serialisation + error wrapping.

aiomqtt.Client is mocked — these are pure-unit tests. Real-broker
round-trip is exercised in the component test (Task 4).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiomqtt
import pytest

from observatory.config import Settings
from observatory.sensory.errors import ForbiddenTopicError, PublishFailedError
from observatory.sensory.publisher import SensoryPublisher
from shared.message_envelope import Envelope


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def envelope() -> Envelope:
    return Envelope.new(
        source_region="observatory.sensory",
        topic="hive/external/perception",
        content_type="application/json",
        data={
            "text": "hi",
            "speaker": "Larry",
            "channel": "observatory.chat",
            "source_modality": "text",
        },
    )


@pytest.mark.asyncio
async def test_publish_allowlisted_topic_serialises_and_calls_client(
    settings: Settings, envelope: Envelope,
) -> None:
    client = MagicMock()
    client.publish = AsyncMock()
    pub = SensoryPublisher(settings)
    pub._client = client  # bypass connect for unit test

    await pub.publish(envelope, qos=1)

    client.publish.assert_awaited_once()
    call_topic, call_payload = client.publish.call_args.args
    assert call_topic == "hive/external/perception"
    # to_json returns bytes — the publisher passes them straight through.
    assert isinstance(call_payload, bytes)
    assert b'"topic": "hive/external/perception"' in call_payload
    assert client.publish.call_args.kwargs["qos"] == 1


@pytest.mark.asyncio
async def test_publish_forbidden_topic_raises(settings: Settings) -> None:
    pub = SensoryPublisher(settings)
    pub._client = MagicMock()  # not used — we should raise before publish

    bad = Envelope.new(
        source_region="observatory.sensory",
        topic="hive/cognitive/pfc/oops",
        content_type="application/json",
        data={"x": 1},
    )
    with pytest.raises(ForbiddenTopicError) as exc_info:
        await pub.publish(bad)
    assert exc_info.value.topic == "hive/cognitive/pfc/oops"


@pytest.mark.asyncio
async def test_publish_wraps_mqtt_error(
    settings: Settings, envelope: Envelope,
) -> None:
    client = MagicMock()
    client.publish = AsyncMock(side_effect=aiomqtt.MqttError("broker unreachable"))
    pub = SensoryPublisher(settings)
    pub._client = client

    with pytest.raises(PublishFailedError) as exc_info:
        await pub.publish(envelope)
    assert isinstance(exc_info.value.cause, aiomqtt.MqttError)
    assert "broker unreachable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_publish_without_connect_raises_runtime_error(
    settings: Settings, envelope: Envelope,
) -> None:
    pub = SensoryPublisher(settings)
    # never set _client
    with pytest.raises(RuntimeError, match="connect"):
        await pub.publish(envelope)
```

### Step 2 — Run tests; expect ImportError

```
C:/repos/hive/.venv/Scripts/python.exe -m pytest observatory/tests/unit/sensory/test_publisher.py -q
```

Expected: `ImportError` on `SensoryPublisher`.

### Step 3 — Implement the publisher

Create `observatory/sensory/publisher.py`:

```python
"""SensoryPublisher — long-lived aiomqtt client with allowlist enforcement.

Lifecycle:
  - constructed once per FastAPI app (in `service.py::lifespan`)
  - `connect()` opens an aiomqtt.Client connection; called in `lifespan`
  - `publish(envelope, qos=...)` validates allowlist + sends bytes
  - `disconnect()` closes the connection cleanly on app shutdown

The aiomqtt connection is established eagerly at startup so the first
chat publish doesn't pay a connection-handshake latency. A failed
startup connect is fatal — the app refuses to come up if the broker
is unreachable, so the operator sees the failure immediately rather
than at first chat send.

Spec §4.3.
"""
from __future__ import annotations

import aiomqtt
import structlog

from observatory.config import Settings
from observatory.sensory.allowlist import ALLOWED_PUBLISH_TOPICS
from observatory.sensory.errors import ForbiddenTopicError, PublishFailedError
from shared.message_envelope import Envelope

log = structlog.get_logger(__name__)


def _parse_mqtt_url(url: str) -> tuple[str, int]:
    """Same parser as observatory.service — kept local to avoid a back-import."""
    rest = url.split("://", 1)[1]
    host, _, port_s = rest.partition(":")
    return host, int(port_s or "1883")


class SensoryPublisher:
    """The single MQTT writer in observatory. Allowlist-gated.

    All publishes go through `publish()`, which validates the envelope's
    topic against `ALLOWED_PUBLISH_TOPICS` *before* serialising. A wrong
    topic is a programming error — the route always builds an allowlisted
    topic — so we raise `ForbiddenTopicError` (route maps to HTTP 500)
    rather than silently dropping.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: aiomqtt.Client | None = None
        self._host, self._port = _parse_mqtt_url(settings.mqtt_url)

    async def connect(self) -> None:
        """Open the aiomqtt connection. Idempotent: a second call is a no-op."""
        if self._client is not None:
            return
        client = aiomqtt.Client(hostname=self._host, port=self._port)
        await client.__aenter__()
        self._client = client
        log.info("sensory_publisher.connected", host=self._host, port=self._port)

    async def disconnect(self) -> None:
        """Close the aiomqtt connection. Idempotent."""
        if self._client is None:
            return
        try:
            await self._client.__aexit__(None, None, None)
        except Exception as e:  # pragma: no cover — best-effort drain
            log.warning("sensory_publisher.disconnect_error", error=str(e))
        finally:
            self._client = None

    async def publish(self, envelope: Envelope, *, qos: int = 1) -> None:
        """Publish an Envelope to MQTT. Raises if topic not allowlisted or send fails."""
        if envelope.topic not in ALLOWED_PUBLISH_TOPICS:
            raise ForbiddenTopicError(envelope.topic)
        if self._client is None:
            raise RuntimeError(
                "SensoryPublisher.publish called before connect()"
            )
        try:
            await self._client.publish(envelope.topic, envelope.to_json(), qos=qos)
        except aiomqtt.MqttError as e:
            raise PublishFailedError(e) from e
```

Imports must be alphabetical (ruff `I001`): `aiomqtt` before `structlog`. The plan's verbatim has them reversed; correct that.

### Step 4 — Run publisher tests; expect PASS

```
C:/repos/hive/.venv/Scripts/python.exe -m pytest observatory/tests/unit/sensory/test_publisher.py -q
C:/repos/hive/.venv/Scripts/python.exe -m ruff check observatory/sensory/publisher.py observatory/tests/unit/sensory/test_publisher.py
```

Expected: 4 passed, ruff clean.

### Step 5 — Commit

Stage exactly the two new files and nothing else:

```
git add observatory/sensory/publisher.py observatory/tests/unit/sensory/test_publisher.py
```

Then commit:

```
git commit -m "$(cat <<'EOF'
observatory(v4): SensoryPublisher (aiomqtt + allowlist + lifecycle)

The single MQTT writer for observatory. connect/disconnect lifecycle is
called from FastAPI's lifespan (wired in Task 3). publish() validates
the envelope's topic against ALLOWED_PUBLISH_TOPICS, serialises via
Envelope.to_json(), and wraps aiomqtt.MqttError in PublishFailedError
for the route to translate to HTTP 502. Spec §4.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

If a pre-commit hook fails: investigate, fix, re-stage, create a NEW commit. Never `--amend` after hook failure. Never `--no-verify`.

### Step 6 — Report

Report status as:
- `DONE` — tests pass, ruff clean, commit landed. Include the SHA.
- `DONE_WITH_CONCERNS` — same plus a brief note on flagged items.
- `BLOCKED` — explain.

## Cumulative gotchas

- **Imports alphabetical** (ruff I001). `aiomqtt` then `structlog`. Plan has these reversed; correct.
- **PEP 585 typing** — already covered by `from __future__ import annotations`.
- **`Exception as e` in `disconnect`** — broad-except + `pragma: no cover` is intentional; do not narrow (we don't know all aiomqtt teardown failure modes).
- **Pre-existing failures** in `observatory/tests/unit/test_mqtt_reconnect.py` (3 failures) are documented in `observatory/memory/decisions.md` (2026-04-29 entry); ignore them — not Task 2 scope.
- **Use `C:/repos/hive/.venv/Scripts/python.exe`** for python invocations.
- **Do not stage** files unrelated to Task 2.

## Definition of done for Task 2

- [ ] `observatory/sensory/publisher.py` exists with `SensoryPublisher`, `_parse_mqtt_url`, public `connect`/`disconnect`/`publish` methods.
- [ ] `observatory/tests/unit/sensory/test_publisher.py` exists with 4 tests, all passing.
- [ ] `python -m pytest observatory/tests/unit/sensory/ -q` is fully green (Task 1 + Task 2 = 8 tests).
- [ ] `ruff check observatory/sensory/publisher.py observatory/tests/unit/sensory/test_publisher.py` is clean.
- [ ] Single commit landed with the exact message above.

Begin.
