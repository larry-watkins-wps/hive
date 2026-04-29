# Observatory v4 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Fresh implementer subagent per task; two-stage review between tasks per `observatory/CLAUDE.md`.

**Goal:** Ship the v4 "chat with Hive" milestone — a floating-overlay chat surface inside the existing observatory frontend, backed by a narrowly-scoped `observatory/sensory/` module that publishes operator-typed text to a single new topic `hive/external/perception` and reads Hive's responses from the existing `hive/motor/speech/complete` topic. v4 is observatory-only; cognitive subscription and broca payload enrichment land via cosignable code-change proposal artifacts (not v4's PR).

**Architecture:** Backend gains a `sensory/` subpackage (4 files) — the *only* part of observatory permitted to publish, allowlist-gated — plus three new fields on `config.Settings`. One new REST route: `POST /sensory/text/in`. Frontend gains a `chat/` subtree (8 files) — floating overlay with drag/resize, transcript that filters the existing envelope ring for two topics, optimistic local turn rendering with envelope-id-based dedupe. No new MQTT subscriptions; no new WS commands; no new ring buffer; no edits under `regions/`.

**Tech Stack:** same as v1/v2/v3. React 18, TypeScript 5, Vite 5, Tailwind 3, zustand 4 (with `subscribeWithSelector` middleware, established v3); FastAPI + `aiomqtt` 2.5+; pytest + pytest-asyncio; testcontainers `eclipse-mosquitto:2`.

**Spec:** [observatory/docs/specs/2026-04-29-observatory-v4-chat-design.md](../specs/2026-04-29-observatory-v4-chat-design.md) — authoritative. Plan conflicts with spec → spec wins; log the discrepancy in `observatory/memory/decisions.md`.

**Tracking convention** (per `observatory/CLAUDE.md`):
- Per-task implementer prompts: `observatory/prompts/v4-task-NN-<slug>.md`
- Non-obvious decisions: `observatory/memory/decisions.md` (append-only)
- One commit per plan task with HEREDOC message ending with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- Two-stage review after each implementer (spec-compliance `general-purpose`, then code-quality `superpowers:code-reviewer`); fix-loop on anything Important+

## Drifts from spec & current state that implementers must know

1. **Backend layout is a flat package at `observatory/`.** Files live at `observatory/<file>.py` (e.g. `observatory/api.py`, `observatory/service.py`, `observatory/config.py`); imports are `from observatory.X import …`. The new sensory subpackage sits as `observatory/sensory/`, imported as `from observatory.sensory.X import …`. The spec refers to module paths with this implicit understanding.
2. **`Settings` is a `@dataclass(frozen=True)`** with a `from_env()` classmethod that reads `os.environ` directly — *not* Pydantic-Settings. v4's three new fields are flat string/int fields on the same dataclass with flat `OBSERVATORY_*` env vars. See spec §4.5.
3. **`Envelope.new(...)` factory** in `src/shared/message_envelope.py:64-85` generates `id` (UUID v4) and `timestamp` (ISO-8601 ms-precision UTC). Use the factory; do not synthesize wrappers by hand. The factory's `attention_hint` defaults to `0.5` — leave it at default for v4.
4. **`Envelope.to_json()` returns `bytes`** (`json.dumps(asdict(self)).encode("utf-8")`). aiomqtt's `client.publish(topic, payload, qos=...)` accepts `bytes` directly — no extra encoding step.
5. **`api.py` builds an `APIRouter` with `prefix="/api"`** in `build_router(...)`. v4's POST endpoint sits at `/sensory/text/in` *without* the `/api` prefix — it lives on its own router (or is added inside `build_router` outside the `/api` prefix block). The spec's "namespaced under `/sensory/*`" specifies this. See Task 3 for the exact wiring.
6. **`PublishFailedError` wraps `aiomqtt.MqttError`.** aiomqtt's exception hierarchy is `MqttError` (base) + `MqttCodeError` (CONNACK errors) — both should be caught.
7. **Frontend store uses `subscribeWithSelector` middleware** (v3 Task 4 established this). The chat slice setters follow the same shape — mutate via `set(state => ({ ... }))`, not direct mutation.
8. **Existing `useDockPersistence`** (`observatory/web-src/src/dock/useDockPersistence.ts`) is the canonical localStorage debounce pattern for v4's `useChatPersistence`. Reuse the shape: hydrate on first mount, debounce 200ms on changes, key by `'observatory.chat.*'`.
9. **`Envelope` (frontend type)** in `store.ts:22-28` is `{ observed_at, topic, envelope, source_region, destinations }`. The full Hive envelope (with `id`, `timestamp`, `payload.data`, etc.) is nested under `e.envelope`. Frontend code reading user/hive turn data accesses `e.envelope.payload.data.text` etc., with type narrowing.
10. **`ws.ts` 10 Hz batcher** (`pushEnvelopes`) means a single user POST → broker → WS round-trip can take up to ~100ms before the firehose echo lands. The optimistic local turn rendering in Task 8 must remain visible during that window.
11. **Frontend tests use Vitest with `jsdom` environment** (set by per-test config or top-of-file pragma). Existing `*.test.tsx` files are the reference for Vitest patterns — `describe`/`it` style, `@testing-library/react` for rendering, `userEvent` from `@testing-library/user-event`.
12. **Component tests require Docker Desktop** for testcontainers `eclipse-mosquitto:2`. CI on GitHub Actions runs them via the standard runner; local skips are gated by `pytest -m component`.
13. **Conftest sets `WindowsSelectorEventLoopPolicy`** (`observatory/tests/component/conftest.py`) — needed for aiomqtt's `add_reader`/`add_writer` on Windows. Don't override the event loop in v4 tests.
14. **Ruff config lives at workspace root `pyproject.toml`** (per top-level `CLAUDE.md`). Do NOT add `[tool.ruff]` to `observatory/pyproject.toml`.

---

## File Structure (locked in up front)

### Backend (Python)

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/sensory/__init__.py` | Empty package marker. | 1 |
| `observatory/sensory/allowlist.py` | `ALLOWED_PUBLISH_TOPICS: FrozenSet[str]` — v4 = `{"hive/external/perception"}`. | 1 |
| `observatory/sensory/errors.py` | `ForbiddenTopicError`, `PublishFailedError`. | 1 |
| `observatory/sensory/publisher.py` | `SensoryPublisher` — aiomqtt publish client with allowlist enforcement and FastAPI startup/shutdown lifecycle. | 2 |
| `observatory/sensory/routes.py` | FastAPI `APIRouter` with `POST /sensory/text/in`. | 3 |
| `observatory/config.py` (modify) | Add three flat fields to `Settings` dataclass + `from_env()`. | 1 |
| `observatory/service.py` (modify) | Construct `SensoryPublisher` in `lifespan`; mount sensory router. | 3 |

### Backend tests

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/tests/unit/sensory/__init__.py` | Empty. | 1 |
| `observatory/tests/unit/sensory/test_allowlist.py` | Pinned-set test. | 1 |
| `observatory/tests/unit/sensory/test_errors.py` | Exception classes have expected attrs. | 1 |
| `observatory/tests/unit/test_config.py` (modify) | Add tests for chat fields + env overrides. | 1 |
| `observatory/tests/unit/sensory/test_publisher.py` | Allowlist enforcement, JSON serialization, MqttError wrapping. | 2 |
| `observatory/tests/unit/sensory/test_routes.py` | Validation, envelope construction, publisher invocation, response shape. | 3 |
| `observatory/tests/component/test_end_to_end.py` (modify) | New test: POST → broker confirms publish on `hive/external/perception`. | 4 |

### Code-change proposal artifacts

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/docs/proposals/2026-04-29-association-cortex-perception-subscription.yaml` | Inert proposal: add `hive/external/perception` to `regions/association_cortex/subscriptions.yaml`. | 5 |
| `observatory/docs/proposals/2026-04-29-broca-speech-complete-text-payload.yaml` | Inert proposal: enrich broca's `speech/complete` payload with a `text` field. | 5 |

### Frontend (TypeScript)

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/src/store.ts` (modify) | Chat slice: `chatVisible`, `chatPosition`, `chatSize`, `pendingChatTurns` map; setters. | 6 |
| `observatory/web-src/src/chat/useChatPersistence.ts` | localStorage debounce for `chatPosition` + `chatSize`; viewport clamp on hydrate. | 6 |
| `observatory/web-src/src/chat/api.ts` | `postChatText(text: string): Promise<{id, timestamp}>` — POST `/sensory/text/in`. | 7 |
| `observatory/web-src/src/chat/Transcript.tsx` | Filtered firehose view: `external/perception` + `motor/speech/complete` + optimistic pending turns. | 8 |
| `observatory/web-src/src/chat/TranscriptTurn.tsx` | One row: speaker label + body + mono timestamp; user / hive / placeholder / error variants. | 8 |
| `observatory/web-src/src/chat/ChatInput.tsx` | Auto-grow textarea + Enter submit + optimistic turn lifecycle. | 9 |
| `observatory/web-src/src/chat/ChatOverlay.tsx` | Floating frame: drag, resize, visibility, mounts Transcript + ChatInput. | 10 |
| `observatory/web-src/src/chat/useChatKeys.ts` | Window-level `c` toggle + Esc dismiss. | 11 |
| `observatory/web-src/src/App.tsx` (modify) | Mount `<ChatOverlay/>`; install `useChatKeys`. | 12 |

### Frontend tests

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/src/chat/useChatPersistence.test.ts` | Hydrate/debounce/clamp. | 6 |
| `observatory/web-src/src/chat/api.test.ts` | Happy/4xx/5xx → `RestError`. | 7 |
| `observatory/web-src/src/chat/Transcript.test.tsx` | Filter, render variants, dedupe with pending. | 8 |
| `observatory/web-src/src/chat/ChatInput.test.tsx` | Submit, Shift+Enter, optimistic lifecycle. | 9 |
| `observatory/web-src/src/chat/ChatOverlay.test.tsx` | Visibility, drag, resize, viewport clamp. | 10 |
| `observatory/web-src/src/chat/useChatKeys.test.tsx` | Toggle + Esc + input-focus guard. | 11 |

---

## Task 1: Sensory module skeleton + Settings extension

**Files:**
- Create: `observatory/sensory/__init__.py`
- Create: `observatory/sensory/allowlist.py`
- Create: `observatory/sensory/errors.py`
- Modify: `observatory/config.py`
- Create: `observatory/tests/unit/sensory/__init__.py`
- Create: `observatory/tests/unit/sensory/test_allowlist.py`
- Create: `observatory/tests/unit/sensory/test_errors.py`
- Modify: `observatory/tests/unit/test_config.py`

**Spec sections:** §4.1, §4.2, §4.5, §11 (Principle IV — allowlist as boundary)

- [ ] **Step 1: Write the allowlist test**

```python
# observatory/tests/unit/sensory/test_allowlist.py
"""Allowlist is the spec §4.2 boundary: exactly one topic for v4."""
from observatory.sensory.allowlist import ALLOWED_PUBLISH_TOPICS


def test_v4_allowlist_is_exactly_one_topic():
    """Spec §4.2: 'v4 = `hive/external/perception` only.'"""
    assert ALLOWED_PUBLISH_TOPICS == frozenset({"hive/external/perception"})


def test_allowlist_is_immutable():
    """Frozenset prevents accidental in-flight mutation by routes/tests."""
    assert isinstance(ALLOWED_PUBLISH_TOPICS, frozenset)
```

- [ ] **Step 2: Write the errors test**

```python
# observatory/tests/unit/sensory/test_errors.py
"""ForbiddenTopicError + PublishFailedError shape per spec §4.3-4.4."""
import aiomqtt
import pytest

from observatory.sensory.errors import ForbiddenTopicError, PublishFailedError


def test_forbidden_topic_error_carries_topic():
    err = ForbiddenTopicError("hive/cognitive/pfc/oops")
    assert err.topic == "hive/cognitive/pfc/oops"
    assert "hive/cognitive/pfc/oops" in str(err)


def test_publish_failed_wraps_mqtt_error():
    """Spec §4.3: 'On aiomqtt.MqttError, raises PublishFailedError wrapping the original.'"""
    underlying = aiomqtt.MqttError("connection refused")
    err = PublishFailedError(underlying)
    assert err.cause is underlying
    assert "connection refused" in str(err)
```

- [ ] **Step 3: Run the unit tests; expect ImportError**

```bash
cd C:/repos/hive
python -m pytest observatory/tests/unit/sensory/ -q
```
Expected: `ModuleNotFoundError: No module named 'observatory.sensory'`.

- [ ] **Step 4: Implement the package skeleton**

```python
# observatory/sensory/__init__.py
"""Observatory sensory bridge — narrowly-scoped MQTT publisher.

This subpackage is the *only* part of observatory permitted to publish to
MQTT. Spec: observatory/docs/specs/2026-04-29-observatory-v4-chat-design.md.
"""
```

```python
# observatory/sensory/allowlist.py
"""Topic allowlist — the boundary that keeps observatory's write surface narrow.

v4: only `hive/external/perception` (translator output for chat-typed input).
Future PRs add topics by editing this set + updating the v4 spec §4.2.
"""
from typing import FrozenSet

ALLOWED_PUBLISH_TOPICS: FrozenSet[str] = frozenset({
    "hive/external/perception",
})
```

```python
# observatory/sensory/errors.py
"""Exceptions raised by the sensory bridge."""
from __future__ import annotations


class ForbiddenTopicError(Exception):
    """Raised when a publish call targets a topic outside the allowlist.

    This is a programming error — routes always build allowlist-permitted
    topics. If raised at runtime, the route returns HTTP 500.
    """

    def __init__(self, topic: str) -> None:
        self.topic = topic
        super().__init__(f"topic {topic!r} is not in the v4 publish allowlist")


class PublishFailedError(Exception):
    """Raised when the underlying aiomqtt publish call fails.

    Wraps the original `aiomqtt.MqttError` so route handlers can return
    HTTP 502 with the underlying message in the body.
    """

    def __init__(self, cause: Exception) -> None:
        self.cause = cause
        super().__init__(str(cause))
```

- [ ] **Step 5: Add the test package marker**

```python
# observatory/tests/unit/sensory/__init__.py
```
(Empty file.)

- [ ] **Step 6: Run the unit tests; expect PASS**

```bash
python -m pytest observatory/tests/unit/sensory/ -q
```
Expected: `2 passed` (test_allowlist) `+ 2 passed` (test_errors).

- [ ] **Step 7: Add Settings fields**

Modify `observatory/config.py`. Inside the `Settings` dataclass, *after* the existing `ring_buffer_size` field:

```python
    chat_default_speaker: str = "Larry"
    chat_publish_qos: int = 1
    chat_text_max_length: int = 4000
```

Inside `from_env()`, *after* the existing `ring_buffer_size=` line:

```python
            chat_default_speaker=os.environ.get(
                "OBSERVATORY_CHAT_DEFAULT_SPEAKER", cls.chat_default_speaker
            ),
            chat_publish_qos=_int_env(
                "OBSERVATORY_CHAT_PUBLISH_QOS", cls.chat_publish_qos
            ),
            chat_text_max_length=_int_env(
                "OBSERVATORY_CHAT_TEXT_MAX_LENGTH", cls.chat_text_max_length
            ),
```

- [ ] **Step 8: Add config tests**

Append to `observatory/tests/unit/test_config.py`:

```python
def test_chat_defaults():
    """Spec §4.5 + §8 default table."""
    s = Settings()
    assert s.chat_default_speaker == "Larry"
    assert s.chat_publish_qos == 1
    assert s.chat_text_max_length == 4000


def test_chat_default_speaker_env_override(monkeypatch):
    monkeypatch.setenv("OBSERVATORY_CHAT_DEFAULT_SPEAKER", "Operator")
    s = Settings.from_env()
    assert s.chat_default_speaker == "Operator"


def test_chat_publish_qos_env_override(monkeypatch):
    monkeypatch.setenv("OBSERVATORY_CHAT_PUBLISH_QOS", "0")
    s = Settings.from_env()
    assert s.chat_publish_qos == 0


def test_chat_text_max_length_env_override(monkeypatch):
    monkeypatch.setenv("OBSERVATORY_CHAT_TEXT_MAX_LENGTH", "2000")
    s = Settings.from_env()
    assert s.chat_text_max_length == 2000


def test_chat_publish_qos_invalid_raises_config_error(monkeypatch):
    monkeypatch.setenv("OBSERVATORY_CHAT_PUBLISH_QOS", "not-a-number")
    with pytest.raises(ConfigError):
        Settings.from_env()
```

(Top-of-file imports may need `pytest` and `from observatory.config import ConfigError` — check the existing test file and add only what's missing.)

- [ ] **Step 9: Run config + sensory tests**

```bash
python -m pytest observatory/tests/unit/test_config.py observatory/tests/unit/sensory/ -q
python -m ruff check observatory/sensory/ observatory/tests/unit/sensory/ observatory/config.py observatory/tests/unit/test_config.py
```
Expected: all PASS, ruff clean.

- [ ] **Step 10: Commit**

```bash
git add observatory/sensory/ observatory/tests/unit/sensory/ observatory/config.py observatory/tests/unit/test_config.py
git commit -m "$(cat <<'EOF'
observatory(v4): sensory module skeleton + Settings chat fields

Adds observatory/sensory/ subpackage (allowlist + errors) and three flat
chat_* fields to Settings (default_speaker, publish_qos, text_max_length)
with OBSERVATORY_CHAT_* env overrides. No behaviour change yet — just the
boundary primitives Task 2's SensoryPublisher and Task 3's POST route
will plug into. Spec §4.1, §4.2, §4.5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: SensoryPublisher

**Files:**
- Create: `observatory/sensory/publisher.py`
- Create: `observatory/tests/unit/sensory/test_publisher.py`

**Spec sections:** §4.3, §3.2 (envelope wrapper)

**Architecture note:** `SensoryPublisher` owns a long-lived `aiomqtt.Client` connection that the FastAPI lifespan brings up at startup and tears down at shutdown. The mqtt subscriber (`mqtt_subscriber.py`) is a *separate* client — read and write surfaces are independent (spec §11 read/write isolation).

- [ ] **Step 1: Write the publisher tests**

```python
# observatory/tests/unit/sensory/test_publisher.py
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
        data={"text": "hi", "speaker": "Larry", "channel": "observatory.chat",
              "source_modality": "text"},
    )


def _mock_client_factory(client: MagicMock):
    """Replace aiomqtt.Client constructor with one that hands back the mock."""
    return lambda *a, **kw: client


@pytest.mark.asyncio
async def test_publish_allowlisted_topic_serialises_and_calls_client(
    monkeypatch, settings, envelope
):
    client = MagicMock()
    client.publish = AsyncMock()
    monkeypatch.setattr(
        "observatory.sensory.publisher.aiomqtt.Client", _mock_client_factory(client)
    )

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
async def test_publish_forbidden_topic_raises(monkeypatch, settings):
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
async def test_publish_wraps_mqtt_error(monkeypatch, settings, envelope):
    client = MagicMock()
    client.publish = AsyncMock(side_effect=aiomqtt.MqttError("broker unreachable"))
    pub = SensoryPublisher(settings)
    pub._client = client

    with pytest.raises(PublishFailedError) as exc_info:
        await pub.publish(envelope)
    assert isinstance(exc_info.value.cause, aiomqtt.MqttError)
    assert "broker unreachable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_publish_without_connect_raises_runtime_error(settings, envelope):
    pub = SensoryPublisher(settings)
    # never set _client
    with pytest.raises(RuntimeError, match="connect"):
        await pub.publish(envelope)
```

- [ ] **Step 2: Run tests; expect ImportError on `SensoryPublisher`**

```bash
python -m pytest observatory/tests/unit/sensory/test_publisher.py -q
```
Expected: `ImportError: cannot import name 'SensoryPublisher'`.

- [ ] **Step 3: Implement the publisher**

```python
# observatory/sensory/publisher.py
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

import structlog
import aiomqtt

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
            raise RuntimeError("SensoryPublisher.publish called before connect()")
        try:
            await self._client.publish(envelope.topic, envelope.to_json(), qos=qos)
        except aiomqtt.MqttError as e:
            raise PublishFailedError(e) from e
```

- [ ] **Step 4: Run publisher tests; expect PASS**

```bash
python -m pytest observatory/tests/unit/sensory/test_publisher.py -q
python -m ruff check observatory/sensory/publisher.py observatory/tests/unit/sensory/test_publisher.py
```
Expected: 4 passed, ruff clean.

- [ ] **Step 5: Commit**

```bash
git add observatory/sensory/publisher.py observatory/tests/unit/sensory/test_publisher.py
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

---

## Task 3: POST /sensory/text/in route + service.py wiring

**Files:**
- Create: `observatory/sensory/routes.py`
- Modify: `observatory/service.py`
- Create: `observatory/tests/unit/sensory/test_routes.py`

**Spec sections:** §4.4, §3.2 (envelope shape)

- [ ] **Step 1: Write route tests**

```python
# observatory/tests/unit/sensory/test_routes.py
"""POST /sensory/text/in — validation, envelope construction, response shape.

Routes the publisher dependency to a stub so we can assert what envelope
the route built without a real broker. Component-level round-trip is
covered in Task 4.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from observatory.config import Settings
from observatory.sensory.errors import PublishFailedError
from observatory.sensory.routes import build_sensory_router, get_publisher, get_settings
from shared.message_envelope import Envelope


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def stub_publisher() -> MagicMock:
    pub = MagicMock()
    pub.publish = AsyncMock()
    return pub


@pytest.fixture
def app(settings: Settings, stub_publisher: MagicMock) -> FastAPI:
    a = FastAPI()
    a.include_router(build_sensory_router())
    a.dependency_overrides[get_publisher] = lambda: stub_publisher
    a.dependency_overrides[get_settings] = lambda: settings
    return a


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_happy_path_publishes_envelope_and_returns_id_timestamp(
    client: TestClient, stub_publisher: MagicMock, settings: Settings
):
    """Spec §4.4: 202 + {id, timestamp} body; envelope per §3.2."""
    resp = client.post("/sensory/text/in", json={"text": "hi"})
    assert resp.status_code == 202
    body = resp.json()
    assert "id" in body and len(body["id"]) >= 32  # uuid v4 string
    assert body["timestamp"].endswith("Z")

    stub_publisher.publish.assert_awaited_once()
    envelope: Envelope = stub_publisher.publish.call_args.args[0]
    assert envelope.topic == "hive/external/perception"
    assert envelope.source_region == "observatory.sensory"
    assert envelope.id == body["id"]
    assert envelope.timestamp == body["timestamp"]
    data = envelope.payload.data
    assert data["text"] == "hi"
    assert data["speaker"] == settings.chat_default_speaker  # default applied
    assert data["channel"] == "observatory.chat"
    assert data["source_modality"] == "text"
    assert stub_publisher.publish.call_args.kwargs["qos"] == settings.chat_publish_qos


def test_speaker_override_passes_through(client: TestClient, stub_publisher: MagicMock):
    resp = client.post("/sensory/text/in", json={"text": "hi", "speaker": "Operator"})
    assert resp.status_code == 202
    envelope: Envelope = stub_publisher.publish.call_args.args[0]
    assert envelope.payload.data["speaker"] == "Operator"


def test_text_trimmed_server_side(client: TestClient, stub_publisher: MagicMock):
    resp = client.post("/sensory/text/in", json={"text": "  hello  "})
    assert resp.status_code == 202
    envelope: Envelope = stub_publisher.publish.call_args.args[0]
    assert envelope.payload.data["text"] == "hello"


def test_empty_after_trim_rejected_with_422(client: TestClient, stub_publisher: MagicMock):
    resp = client.post("/sensory/text/in", json={"text": "   "})
    assert resp.status_code == 422
    stub_publisher.publish.assert_not_awaited()


def test_oversize_text_rejected_with_422(client: TestClient, stub_publisher: MagicMock, settings: Settings):
    too_long = "x" * (settings.chat_text_max_length + 1)
    resp = client.post("/sensory/text/in", json={"text": too_long})
    assert resp.status_code == 422
    stub_publisher.publish.assert_not_awaited()


def test_publish_failed_returns_502(client: TestClient, stub_publisher: MagicMock):
    import aiomqtt
    stub_publisher.publish.side_effect = PublishFailedError(aiomqtt.MqttError("broker down"))
    resp = client.post("/sensory/text/in", json={"text": "hi"})
    assert resp.status_code == 502
    body = resp.json()
    assert body["error"] == "publish_failed"
    assert "broker down" in body["message"]


def test_response_has_no_store_cache_control(client: TestClient):
    resp = client.post("/sensory/text/in", json={"text": "hi"})
    assert resp.headers.get("Cache-Control") == "no-store"
```

- [ ] **Step 2: Run; expect ImportError**

```bash
python -m pytest observatory/tests/unit/sensory/test_routes.py -q
```
Expected: ImportError on `build_sensory_router`.

- [ ] **Step 3: Implement the routes module**

```python
# observatory/sensory/routes.py
"""POST /sensory/text/in — translator output endpoint.

The single v4 endpoint. Future audio/visual endpoints sit beside this
under the `/sensory/*` prefix. The publisher dependency is provided
via FastAPI's dependency-injection so component tests + unit tests
can swap the real publisher for a stub.

Spec §4.4.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from observatory.config import Settings
from observatory.sensory.errors import ForbiddenTopicError, PublishFailedError
from observatory.sensory.publisher import SensoryPublisher
from shared.message_envelope import Envelope


# Dependency providers — overridden in tests via `app.dependency_overrides`.
def get_publisher(request: Request) -> SensoryPublisher:
    return request.app.state.sensory_publisher


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


class TextInRequest(BaseModel):
    text: str = Field(min_length=1)
    speaker: str | None = None

    @field_validator("text")
    @classmethod
    def _trim_and_check(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("text is empty after trim")
        return trimmed


class TextInResponse(BaseModel):
    id: str
    timestamp: str


def build_sensory_router() -> APIRouter:
    router = APIRouter()

    @router.post("/sensory/text/in", status_code=202, response_model=TextInResponse)
    async def text_in(
        body: TextInRequest,
        publisher: SensoryPublisher = Depends(get_publisher),
        settings: Settings = Depends(get_settings),
    ) -> Response:
        # Late max-length check so we can use the runtime Settings value
        # rather than baking it into Pydantic at import time.
        if len(body.text) > settings.chat_text_max_length:
            raise HTTPException(
                status_code=422,
                detail=[{
                    "loc": ["body", "text"],
                    "msg": f"text exceeds chat_text_max_length={settings.chat_text_max_length}",
                    "type": "value_error",
                }],
            )

        speaker = body.speaker if body.speaker is not None else settings.chat_default_speaker
        envelope = Envelope.new(
            source_region="observatory.sensory",
            topic="hive/external/perception",
            content_type="application/json",
            data={
                "text": body.text,
                "speaker": speaker,
                "channel": "observatory.chat",
                "source_modality": "text",
            },
        )
        try:
            await publisher.publish(envelope, qos=settings.chat_publish_qos)
        except ForbiddenTopicError as e:  # programming error
            raise HTTPException(status_code=500, detail={
                "error": "forbidden_topic", "message": str(e),
            }) from e
        except PublishFailedError as e:
            raise HTTPException(status_code=502, detail={
                "error": "publish_failed", "message": str(e),
            }) from e

        return JSONResponse(
            status_code=202,
            content={"id": envelope.id, "timestamp": envelope.timestamp},
            headers={"Cache-Control": "no-store"},
        )

    return router
```

Pydantic's `HTTPException` with a list-shape detail mirrors FastAPI's own validation-error body; the existing v2/v3 `/api/regions/*` routes use the flat `{error, message}` shape, so we match that for the publish-failed case while preserving FastAPI standard for input validation.

- [ ] **Step 4: Run route tests; expect FAIL until app wiring is in place**

```bash
python -m pytest observatory/tests/unit/sensory/test_routes.py -q
```

The test fixture builds its own `FastAPI()` app and overrides dependencies — *route tests should pass at this point* without service.py changes. If tests still fail, debug `dependency_overrides` plumbing.

Expected: 7 passed.

- [ ] **Step 5: Wire SensoryPublisher + router into service.py**

In `observatory/service.py`, locate the `lifespan` context manager and the `build_app` factory.

(a) Top-of-file imports — add:

```python
from observatory.sensory.publisher import SensoryPublisher
from observatory.sensory.routes import build_sensory_router
```

(b) Inside `lifespan(...)`, *after* the existing MQTT subscriber setup but *before* the `yield`, add:

```python
    sensory_publisher = SensoryPublisher(settings)
    await sensory_publisher.connect()
    app.state.sensory_publisher = sensory_publisher
    app.state.settings = settings
```

(c) After the `yield`, *before* the existing teardown, add:

```python
    await sensory_publisher.disconnect()
```

(d) Inside `build_app(...)`, *after* the existing `app.include_router(build_router(region_registry))` line, add:

```python
    app.include_router(build_sensory_router())
```

- [ ] **Step 6: Run full unit test suite**

```bash
python -m pytest observatory/tests/unit/ -q
python -m ruff check observatory/sensory/ observatory/service.py observatory/tests/unit/sensory/
```
Expected: all PASS, ruff clean.

- [ ] **Step 7: Commit**

```bash
git add observatory/sensory/routes.py observatory/service.py observatory/tests/unit/sensory/test_routes.py
git commit -m "$(cat <<'EOF'
observatory(v4): POST /sensory/text/in route + service wiring

Adds the single v4 REST endpoint. Validates body via Pydantic, trims
text, enforces text_max_length against runtime Settings, builds an
Envelope via Envelope.new(...), calls the SensoryPublisher dependency,
returns 202 with {id, timestamp}. ForbiddenTopicError -> 500;
PublishFailedError -> 502 with flat {error, message} body. Cache-Control
no-store, matching v2 REST convention.

service.py constructs a SensoryPublisher in the lifespan, connects it
at startup, attaches to app.state for the route's dependency, and
disconnects on shutdown. Spec §4.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Component test — POST → real broker round-trip

**Files:**
- Modify: `observatory/tests/component/test_end_to_end.py`

**Spec sections:** §9.2

- [ ] **Step 1: Append the component test**

**Adapt to existing test patterns.** The existing test file uses `starlette.testclient.TestClient` (sync, runs lifespan as context manager), the `MosquittoContainer` testcontainer with a custom `_MOSQUITTO_CONF`, and shared module-scoped fixtures. The new test reuses those fixtures; it differs only in needing an aiomqtt side-channel listener to capture the publish.

Pattern: start the listener in a background thread *before* the POST, share results via a `queue.Queue`. This avoids needing `asgi_lifespan` (not in deps) and matches the file's existing sync style.

Append to `observatory/tests/component/test_end_to_end.py`:

```python
def test_post_sensory_text_in_publishes_to_broker(broker_url, tmp_path):
    """Spec §9.2: POST → real broker confirms publish on hive/external/perception
    with the spec §3.2 envelope shape, round-trip < 500ms."""
    import asyncio
    import queue
    import threading
    import time

    # Build the app pointing at the testcontainer broker. Empty regions dir
    # is fine — the route doesn't touch the registry.
    regions_root = tmp_path / "regions"
    regions_root.mkdir()
    settings = dataclasses.replace(
        Settings(),
        mqtt_url=broker_url,
        regions_root=regions_root,
    )
    app = build_app(settings)

    # Capture the broker echo via a separate aiomqtt subscriber running in
    # its own thread + event loop. Using `qos=1` matches the route default
    # so the broker delivers reliably even if there's a minor race.
    captured: queue.Queue[dict] = queue.Queue()
    ready = threading.Event()
    host, _, port_s = broker_url.split("://", 1)[1].partition(":")
    port = int(port_s)

    def _capture_loop() -> None:
        async def _go():
            async with aiomqtt.Client(host, port) as c:
                await c.subscribe("hive/external/perception", qos=1)
                ready.set()
                async for msg in c.messages:
                    captured.put(json.loads(msg.payload.decode()))
                    return
        asyncio.run(_go())

    cap_thread = threading.Thread(target=_capture_loop, daemon=True)
    cap_thread.start()
    assert ready.wait(timeout=5.0), "capture subscriber never reported ready"

    # Drive the route via the sync TestClient (runs lifespan automatically).
    with TestClient(app) as client:
        t0 = time.monotonic()
        resp = client.post("/sensory/text/in", json={"text": "hi from test"})
        assert resp.status_code == 202
        body = resp.json()
        assert "id" in body and "timestamp" in body

    env = captured.get(timeout=2.0)
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5, f"round-trip too slow: {elapsed:.2f}s"

    assert env["topic"] == "hive/external/perception"
    assert env["source_region"] == "observatory.sensory"
    assert env["envelope_version"] == 1
    assert env["id"] == body["id"]
    assert env["timestamp"] == body["timestamp"]
    data = env["payload"]["data"]
    assert data["text"] == "hi from test"
    assert data["speaker"] == "Larry"
    assert data["channel"] == "observatory.chat"
    assert data["source_modality"] == "text"
```

The `broker_url` fixture is the existing module-scoped fixture in this file (returns `mqtt://host:port`). If the existing fixture name is `mosquitto_container` or similar, adapt accordingly — the implementer should grep the file for the existing pattern. (`asyncio`, `aiomqtt`, `json`, `dataclasses`, `Settings`, `build_app`, `TestClient` are already imported at the top of the file — no new top-level imports needed beyond `queue`, `threading`, `time`.)

- [ ] **Step 2: Run the component test**

```bash
python -m pytest observatory/tests/component/test_end_to_end.py::test_post_sensory_text_in_publishes_to_broker -m component -v
```
Expected: PASS, round-trip < 500ms.

- [ ] **Step 3: Run the full component suite**

```bash
python -m pytest observatory/tests/component/ -m component -v
```
Expected: 4 passed (3 existing v1/v2/v3 + 1 new v4).

- [ ] **Step 4: Commit**

```bash
git add observatory/tests/component/test_end_to_end.py
git commit -m "$(cat <<'EOF'
observatory(v4): component test — POST → real broker round-trip

Verifies POST /sensory/text/in publishes a fully-formed Hive Envelope
on hive/external/perception with the §3.2 shape. Uses the existing
testcontainers eclipse-mosquitto:2 fixture and asserts round-trip
latency < 500ms. Spec §9.2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Code-change proposal artifacts

**Files:**
- Create: `observatory/docs/proposals/2026-04-29-association-cortex-perception-subscription.yaml`
- Create: `observatory/docs/proposals/2026-04-29-broca-speech-complete-text-payload.yaml`

**Spec sections:** §5.1, §5.2

- [ ] **Step 1: Create the proposals directory + first artifact**

```yaml
# observatory/docs/proposals/2026-04-29-association-cortex-perception-subscription.yaml
proposal_id: assoc-cortex-perception-2026-04-29
target: regions/association_cortex/subscriptions.yaml
kind: subscription_addition
diff:
  add:
    - topic: hive/external/perception
      qos: 1
      description: "External perception — thought-form text arriving from outside the organism (chat, future STT, future captioning)."
rationale: |
  Observatory v4 introduces a chat surface that publishes typed user input
  to hive/external/perception (see observatory/docs/specs/2026-04-29-observatory-v4-chat-design.md).
  Association_cortex is the natural first reader because its prompt already
  declares multi-modal integration as its role. Without this subscription
  no region listens to chat input, and the conversation is one-way.
cosign_required: true
```

- [ ] **Step 2: Create the second artifact**

```yaml
# observatory/docs/proposals/2026-04-29-broca-speech-complete-text-payload.yaml
proposal_id: broca-complete-text-payload-2026-04-29
target: regions/broca_area/prompt.md  # plus any handler that emits `complete`
kind: payload_enrichment
diff:
  field: text
  on_topic: hive/motor/speech/complete
  type: string
  required: true
  semantics: "verbatim text of the utterance broca articulated"
rationale: |
  Observatory v4's chat reads hive/motor/speech/complete to render Hive's
  responses in the transcript. With audio bytes alone the chat can show
  only an "🔊 hive spoke" placeholder. Adding text to the complete payload
  is biologically natural — a speaker knows what they just said — and
  costs broca nothing because it already holds the intent text it just
  synthesised.
cosign_required: true
```

- [ ] **Step 3: Commit**

```bash
git add observatory/docs/proposals/
git commit -m "$(cat <<'EOF'
observatory(v4): code-change proposal artifacts (assoc_cortex sub + broca payload)

Inert YAML payloads under observatory/docs/proposals/. v4 itself does
not modify any region (Principle III). When cosigned via Hive's
hive/system/codechange/proposed channel:

  - association_cortex gains a hive/external/perception subscription, so
    chat messages reach cognition.
  - broca's speech/complete payload gains a `text` field, so the chat
    transcript can render Hive's responses with words rather than just
    an audio-only placeholder.

Until cosigned, v4 chat is one-way (operator can speak, Hive listens
silently — the legitimate bootstrap state). Spec §5.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Frontend store extension + chat persistence

**Files:**
- Modify: `observatory/web-src/src/store.ts`
- Create: `observatory/web-src/src/chat/useChatPersistence.ts`
- Create: `observatory/web-src/src/chat/useChatPersistence.test.ts`

**Spec sections:** §6.2, §6.5

- [ ] **Step 1: Extend the store State type**

In `observatory/web-src/src/store.ts`, add to the `State` type (after the `pendingEnvelopeKey` entry and its setter):

```ts
  // Chat slice — see spec §6.2, §6.5
  chatVisible: boolean;
  chatPosition: { x: number; y: number };  // viewport px (top-left of overlay)
  chatSize: { w: number; h: number };
  /** Optimistic user turns awaiting firehose echo. Keyed by:
   *  - temporary client id while the POST is in flight (no envelope id yet)
   *  - envelope id once POST returns
   * Dropped when an envelope with the same id arrives in the firehose ring. */
  pendingChatTurns: Record<string, PendingChatTurn>;

  setChatVisible: (v: boolean) => void;
  setChatPosition: (p: { x: number; y: number }) => void;
  setChatSize: (s: { w: number; h: number }) => void;
  addPendingChatTurn: (turn: PendingChatTurn) => void;
  resolvePendingChatTurn: (clientId: string, envelopeId: string, timestamp: string) => void;
  failPendingChatTurn: (clientId: string, reason: string) => void;
  dropPendingChatTurn: (id: string) => void;
```

Above the `State` type, add the supporting type:

```ts
export type PendingChatTurn = {
  /** Stable id for React keys and lookup. Initially a client uuid; replaced
   * by the envelope id once POST returns. */
  id: string;
  text: string;
  speaker: string;
  /** ISO timestamp string. Initially the local time at submit; replaced
   * with the server-assigned envelope timestamp on POST success. */
  timestamp: string;
  /** Lifecycle state for rendering. */
  status: 'sending' | 'sent' | 'failed';
  /** Failure reason when status === 'failed'. */
  errorReason?: string;
};
```

- [ ] **Step 2: Add the initial state values + setters**

Inside the `create<State>()(...)` factory, after the existing initial values (e.g. `pendingEnvelopeKey: null`), add:

```ts
  chatVisible: false,
  chatPosition: { x: 0, y: 16 },     // x is recomputed lazily on first open
  chatSize: { w: 320, h: 260 },
  pendingChatTurns: {},
```

After the existing setters (e.g. `setPendingEnvelopeKey`), add:

```ts
  setChatVisible: (v) => set({ chatVisible: v }),
  setChatPosition: (p) => set({ chatPosition: p }),
  setChatSize: (s) => set({ chatSize: s }),
  addPendingChatTurn: (turn) => set((s) => ({
    pendingChatTurns: { ...s.pendingChatTurns, [turn.id]: turn },
  })),
  resolvePendingChatTurn: (clientId, envelopeId, timestamp) => set((s) => {
    const existing = s.pendingChatTurns[clientId];
    if (!existing) return {};
    const { [clientId]: _, ...rest } = s.pendingChatTurns;
    return {
      pendingChatTurns: {
        ...rest,
        [envelopeId]: { ...existing, id: envelopeId, timestamp, status: 'sent' },
      },
    };
  }),
  failPendingChatTurn: (clientId, reason) => set((s) => {
    const existing = s.pendingChatTurns[clientId];
    if (!existing) return {};
    return {
      pendingChatTurns: {
        ...s.pendingChatTurns,
        [clientId]: { ...existing, status: 'failed', errorReason: reason },
      },
    };
  }),
  dropPendingChatTurn: (id) => set((s) => {
    const { [id]: _, ...rest } = s.pendingChatTurns;
    return { pendingChatTurns: rest };
  }),
```

- [ ] **Step 3: Write the persistence hook test**

```ts
// observatory/web-src/src/chat/useChatPersistence.test.ts
import { renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useStore } from '../store';
import { useChatPersistence } from './useChatPersistence';

describe('useChatPersistence', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('hydrates chatPosition + chatSize from localStorage on first mount', () => {
    localStorage.setItem('observatory.chat.position', JSON.stringify({ x: 50, y: 80 }));
    localStorage.setItem('observatory.chat.size', JSON.stringify({ w: 400, h: 300 }));

    renderHook(() => useChatPersistence(useStore));

    expect(useStore.getState().chatPosition).toEqual({ x: 50, y: 80 });
    expect(useStore.getState().chatSize).toEqual({ w: 400, h: 300 });
  });

  it('clamps hydrated position back inside the viewport', () => {
    Object.defineProperty(window, 'innerWidth', { value: 800, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 600, configurable: true });
    localStorage.setItem('observatory.chat.position', JSON.stringify({ x: 5000, y: 5000 }));
    localStorage.setItem('observatory.chat.size', JSON.stringify({ w: 320, h: 260 }));

    renderHook(() => useChatPersistence(useStore));

    const pos = useStore.getState().chatPosition;
    expect(pos.x).toBeLessThanOrEqual(800 - 320 - 16);
    expect(pos.y).toBeLessThanOrEqual(600 - 260 - 16);
  });

  it('debounces writes (200ms) on chatPosition changes', () => {
    renderHook(() => useChatPersistence(useStore));
    useStore.getState().setChatPosition({ x: 100, y: 200 });
    expect(localStorage.getItem('observatory.chat.position')).toBeNull();
    vi.advanceTimersByTime(199);
    expect(localStorage.getItem('observatory.chat.position')).toBeNull();
    vi.advanceTimersByTime(2);
    expect(JSON.parse(localStorage.getItem('observatory.chat.position')!))
      .toEqual({ x: 100, y: 200 });
  });

  it('debounces writes on chatSize changes', () => {
    renderHook(() => useChatPersistence(useStore));
    useStore.getState().setChatSize({ w: 500, h: 350 });
    vi.advanceTimersByTime(201);
    expect(JSON.parse(localStorage.getItem('observatory.chat.size')!))
      .toEqual({ w: 500, h: 350 });
  });
});
```

- [ ] **Step 4: Implement the persistence hook**

```ts
// observatory/web-src/src/chat/useChatPersistence.ts
/**
 * localStorage persistence for the chat overlay's position + size.
 * Mirrors useDockPersistence: hydrate from localStorage on mount,
 * debounce 200ms on store changes back to localStorage. On hydrate,
 * clamp position so the overlay can't open off-screen if the viewport
 * shrunk between sessions. Spec §6.2.
 */
import { useEffect, useRef } from 'react';
import type { StoreApi } from 'zustand';

import type { State } from '../store';

const POSITION_KEY = 'observatory.chat.position';
const SIZE_KEY = 'observatory.chat.size';
const DEBOUNCE_MS = 200;
const VIEWPORT_MARGIN = 16;

function clampPosition(
  pos: { x: number; y: number },
  size: { w: number; h: number },
): { x: number; y: number } {
  const maxX = Math.max(0, window.innerWidth - size.w - VIEWPORT_MARGIN);
  const maxY = Math.max(0, window.innerHeight - size.h - VIEWPORT_MARGIN);
  return {
    x: Math.min(Math.max(VIEWPORT_MARGIN, pos.x), maxX),
    y: Math.min(Math.max(VIEWPORT_MARGIN, pos.y), maxY),
  };
}

export function useChatPersistence(store: StoreApi<State>): void {
  const hydratedRef = useRef(false);
  const posTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sizeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Hydrate once on first mount.
  useEffect(() => {
    if (hydratedRef.current) return;
    hydratedRef.current = true;

    const sizeRaw = localStorage.getItem(SIZE_KEY);
    let size = store.getState().chatSize;
    if (sizeRaw) {
      try {
        const parsed = JSON.parse(sizeRaw);
        if (typeof parsed?.w === 'number' && typeof parsed?.h === 'number') {
          size = { w: parsed.w, h: parsed.h };
          store.getState().setChatSize(size);
        }
      } catch { /* corrupt — ignore, keep default */ }
    }

    const posRaw = localStorage.getItem(POSITION_KEY);
    if (posRaw) {
      try {
        const parsed = JSON.parse(posRaw);
        if (typeof parsed?.x === 'number' && typeof parsed?.y === 'number') {
          const clamped = clampPosition({ x: parsed.x, y: parsed.y }, size);
          store.getState().setChatPosition(clamped);
        }
      } catch { /* ignore */ }
    }
  }, [store]);

  // Debounced writes for position.
  useEffect(() => {
    return store.subscribe((s, prev) => {
      if (s.chatPosition === prev.chatPosition) return;
      if (posTimer.current) clearTimeout(posTimer.current);
      posTimer.current = setTimeout(() => {
        localStorage.setItem(POSITION_KEY, JSON.stringify(s.chatPosition));
      }, DEBOUNCE_MS);
    });
  }, [store]);

  // Debounced writes for size.
  useEffect(() => {
    return store.subscribe((s, prev) => {
      if (s.chatSize === prev.chatSize) return;
      if (sizeTimer.current) clearTimeout(sizeTimer.current);
      sizeTimer.current = setTimeout(() => {
        localStorage.setItem(SIZE_KEY, JSON.stringify(s.chatSize));
      }, DEBOUNCE_MS);
    });
  }, [store]);
}
```

- [ ] **Step 5: Export the `State` type from store**

If `State` isn't already exported from `store.ts` (check with grep), change `type State = {...}` to `export type State = {...}`. Also export `PendingChatTurn` (already done in Step 1).

- [ ] **Step 6: Run frontend tests**

```bash
cd observatory/web-src
npx vitest run src/chat/useChatPersistence.test.ts
npx tsc -b
```
Expected: 4 tests pass; typecheck clean.

- [ ] **Step 7: Run the full vitest suite to catch regressions**

```bash
npx vitest run
```
Expected: previous tests + 4 new = clean run.

- [ ] **Step 8: Commit**

```bash
cd C:/repos/hive
git add observatory/web-src/src/store.ts observatory/web-src/src/chat/useChatPersistence.ts observatory/web-src/src/chat/useChatPersistence.test.ts
git commit -m "$(cat <<'EOF'
observatory(v4): store chat slice + useChatPersistence

Adds chatVisible/chatPosition/chatSize state and a pendingChatTurns
map to the zustand store, with setters for each. The pending-turns
map holds optimistic user turns keyed first by a temporary client id
during POST flight, then rekeyed to the envelope id once POST returns
(see Task 9 ChatInput for the lifecycle). Spec §6.2, §6.5.

useChatPersistence mirrors useDockPersistence: hydrate from localStorage
on mount, debounce 200ms on changes. Hydrated positions are clamped
back inside the viewport in case it shrunk between sessions.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Frontend api.ts — POST wrapper

**Files:**
- Create: `observatory/web-src/src/chat/api.ts`
- Create: `observatory/web-src/src/chat/api.test.ts`

**Spec sections:** §4.4 (response shape)

- [ ] **Step 1: Write api tests**

```ts
// observatory/web-src/src/chat/api.test.ts
import { afterEach, describe, expect, it, vi } from 'vitest';

import { postChatText } from './api';

describe('postChatText', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('POSTs to /sensory/text/in with the given text and returns id+timestamp', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(
        JSON.stringify({ id: 'abc-123', timestamp: '2026-04-29T14:32:08.417Z' }),
        { status: 202, headers: { 'content-type': 'application/json' } },
      ),
    );

    const result = await postChatText('hello');

    expect(fetchMock).toHaveBeenCalledWith(
      '/sensory/text/in',
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ text: 'hello' }),
      }),
    );
    expect(result).toEqual({ id: 'abc-123', timestamp: '2026-04-29T14:32:08.417Z' });
  });

  it('passes through speaker when provided', async () => {
    const fetchMock = vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ id: 'x', timestamp: 't' }), { status: 202 }),
    );
    await postChatText('hi', 'Operator');
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toEqual({ text: 'hi', speaker: 'Operator' });
  });

  it('throws with the parsed error body on non-2xx', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ error: 'publish_failed', message: 'broker down' }),
        { status: 502 }),
    );
    await expect(postChatText('hi')).rejects.toThrow(/publish_failed.*broker down/);
  });

  it('throws on network failure with a generic message', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new TypeError('Network error'));
    await expect(postChatText('hi')).rejects.toThrow(/network/i);
  });
});
```

- [ ] **Step 2: Run; expect ImportError**

```bash
cd observatory/web-src
npx vitest run src/chat/api.test.ts
```
Expected: missing `./api` import.

- [ ] **Step 3: Implement the api**

```ts
// observatory/web-src/src/chat/api.ts
/**
 * POST /sensory/text/in wrapper.
 * Returns the envelope id + timestamp (spec §4.4) so the caller can
 * rekey its optimistic local turn from the temporary client id to the
 * server-assigned envelope id. Spec §6.5.
 */
export type PostChatTextResponse = {
  id: string;
  timestamp: string;
};

export class ChatPostError extends Error {
  constructor(public readonly kind: string, public readonly detail: string) {
    super(`${kind}: ${detail}`);
    this.name = 'ChatPostError';
  }
}

export async function postChatText(
  text: string,
  speaker?: string,
): Promise<PostChatTextResponse> {
  const body = speaker !== undefined ? { text, speaker } : { text };
  let resp: Response;
  try {
    resp = await fetch('/sensory/text/in', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new ChatPostError('network', (e as Error).message);
  }
  if (!resp.ok) {
    let errKind = `http_${resp.status}`;
    let errMsg = resp.statusText;
    try {
      const parsed = await resp.json();
      // Match server bodies: 502 has flat {error, message}; 422 has FastAPI
      // detail array. Surface whichever shape is present.
      if (typeof parsed?.error === 'string') {
        errKind = parsed.error;
        errMsg = parsed.message ?? errMsg;
      } else if (Array.isArray(parsed?.detail) && parsed.detail.length > 0) {
        errKind = 'validation';
        errMsg = parsed.detail[0].msg ?? errMsg;
      }
    } catch { /* response wasn't JSON — keep status defaults */ }
    throw new ChatPostError(errKind, errMsg);
  }
  return (await resp.json()) as PostChatTextResponse;
}
```

- [ ] **Step 4: Run; expect PASS**

```bash
npx vitest run src/chat/api.test.ts
npx tsc -b
```
Expected: 4 passed; typecheck clean.

- [ ] **Step 5: Commit**

```bash
cd C:/repos/hive
git add observatory/web-src/src/chat/api.ts observatory/web-src/src/chat/api.test.ts
git commit -m "$(cat <<'EOF'
observatory(v4): chat/api.ts — POST /sensory/text/in wrapper

postChatText(text, speaker?) returns {id, timestamp} from the server's
202 response (spec §4.4). Errors are normalised into a ChatPostError
carrying {kind, detail} so the ChatInput component (Task 9) can render
the failure reason in its error placeholder.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Transcript + TranscriptTurn

**Files:**
- Create: `observatory/web-src/src/chat/Transcript.tsx`
- Create: `observatory/web-src/src/chat/TranscriptTurn.tsx`
- Create: `observatory/web-src/src/chat/Transcript.test.tsx`

**Spec sections:** §3.3, §6.4, §6.5 (dedupe interaction)

- [ ] **Step 1: Write Transcript tests**

```tsx
// observatory/web-src/src/chat/Transcript.test.tsx
import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import type { Envelope, PendingChatTurn } from '../store';
import { useStore } from '../store';
import { Transcript } from './Transcript';

function envOnTopic(topic: string, data: unknown, id: string, ts: string): Envelope {
  return {
    observed_at: Date.parse(ts),
    topic,
    source_region: 'observatory.sensory',
    destinations: [],
    envelope: {
      id, timestamp: ts, envelope_version: 1,
      source_region: 'observatory.sensory',
      topic,
      payload: { content_type: 'application/json', encoding: 'utf-8', data },
      attention_hint: 0.5, reply_to: null, correlation_id: null,
    },
  };
}

describe('Transcript', () => {
  beforeEach(() => {
    useStore.setState({
      envelopes: [],
      pendingChatTurns: {},
    });
  });
  afterEach(() => {
    useStore.setState({ envelopes: [], pendingChatTurns: {} });
  });

  it('filters envelopes to the two transcript topics', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/external/perception',
          { text: 'hi', speaker: 'Larry', channel: 'observatory.chat', source_modality: 'text' },
          'env-1', '2026-04-29T14:00:00.000Z'),
        envOnTopic('hive/cognitive/pfc/plan', { unrelated: true }, 'env-2', '2026-04-29T14:01:00.000Z'),
        envOnTopic('hive/motor/speech/complete',
          { text: 'hello', utterance_id: 'u-1' }, 'env-3', '2026-04-29T14:02:00.000Z'),
      ],
    });
    render(<Transcript />);
    expect(screen.getByText('hi')).toBeInTheDocument();
    expect(screen.getByText('hello')).toBeInTheDocument();
    expect(screen.queryByText(/unrelated/)).toBeNull();
  });

  it('renders user turn with the speaker label from payload data', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/external/perception',
          { text: 'are you there?', speaker: 'Larry', channel: 'observatory.chat', source_modality: 'text' },
          'env-1', '2026-04-29T14:00:00.000Z'),
      ],
    });
    render(<Transcript />);
    expect(screen.getByText('larry')).toBeInTheDocument();
    expect(screen.getByText('are you there?')).toBeInTheDocument();
  });

  it('renders hive turn with text when payload.data.text is present', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/motor/speech/complete',
          { text: 'yes', utterance_id: 'u-1' }, 'env-1', '2026-04-29T14:00:00.000Z'),
      ],
    });
    render(<Transcript />);
    expect(screen.getByText('hive')).toBeInTheDocument();
    expect(screen.getByText('yes')).toBeInTheDocument();
  });

  it('renders audio placeholder when motor/speech/complete has no text', () => {
    useStore.setState({
      envelopes: [
        envOnTopic('hive/motor/speech/complete',
          { utterance_id: 'u-1', duration_ms: 4200 }, 'env-1', '2026-04-29T14:00:00.000Z'),
      ],
    });
    render(<Transcript />);
    expect(screen.getByText(/🔊 hive spoke/)).toBeInTheDocument();
    expect(screen.getByText(/4s/)).toBeInTheDocument();
  });

  it('renders pending optimistic turn alongside ring envelopes, then dedupes', () => {
    const pending: PendingChatTurn = {
      id: 'env-1', text: 'optimistic', speaker: 'Larry',
      timestamp: '2026-04-29T14:00:00.000Z', status: 'sent',
    };
    useStore.setState({
      envelopes: [],
      pendingChatTurns: { 'env-1': pending },
    });
    const { rerender } = render(<Transcript />);
    expect(screen.getByText('optimistic')).toBeInTheDocument();

    // Now the firehose echo arrives with the same envelope id.
    useStore.setState({
      envelopes: [
        envOnTopic('hive/external/perception',
          { text: 'optimistic', speaker: 'Larry', channel: 'observatory.chat', source_modality: 'text' },
          'env-1', '2026-04-29T14:00:00.000Z'),
      ],
      pendingChatTurns: { 'env-1': pending },  // pending still in store; dedupe is render-time
    });
    rerender(<Transcript />);
    // The text appears exactly once — pending was suppressed because the id matches.
    expect(screen.getAllByText('optimistic')).toHaveLength(1);
  });

  it('renders error placeholder for failed pending turn', () => {
    useStore.setState({
      pendingChatTurns: {
        'tmp-1': {
          id: 'tmp-1', text: 'hi', speaker: 'Larry',
          timestamp: '2026-04-29T14:00:00.000Z',
          status: 'failed', errorReason: 'publish_failed: broker down',
        },
      },
    });
    render(<Transcript />);
    expect(screen.getByText(/× failed to send/)).toBeInTheDocument();
    expect(screen.getByText(/broker down/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run; expect ImportError**

```bash
cd observatory/web-src
npx vitest run src/chat/Transcript.test.tsx
```
Expected: missing `./Transcript`.

- [ ] **Step 3: Implement TranscriptTurn**

```tsx
// observatory/web-src/src/chat/TranscriptTurn.tsx
/**
 * One row in the chat transcript. Plain text — no card chrome — matching
 * the v3 inspector message style. Spec §6.4.
 */
import type { CSSProperties } from 'react';

type Variant = 'user' | 'hive' | 'audio_placeholder' | 'error';

type Props = {
  variant: Variant;
  speaker: string;
  body: string;
  timestamp: string;       // ISO; rendered HH:MM:SS in mono
  errorReason?: string;
};

const SPEAKER_COLORS: Record<Variant, string> = {
  user: 'rgba(143,197,255,.65)',
  hive: 'rgba(220,180,255,.65)',
  audio_placeholder: 'rgba(220,180,255,.65)',
  error: 'rgba(220,140,140,.7)',
};

function fmtClock(iso: string): string {
  // ISO is "YYYY-MM-DDTHH:MM:SS.sssZ" — substring HH:MM:SS.
  const t = iso.indexOf('T');
  return t >= 0 ? iso.substring(t + 1, t + 9) : iso;
}

const speakerStyle = (variant: Variant): CSSProperties => ({
  fontSize: 9, letterSpacing: '.5px', textTransform: 'uppercase',
  color: SPEAKER_COLORS[variant], marginBottom: 3,
  display: 'flex', justifyContent: 'space-between',
});
const tsStyle: CSSProperties = {
  fontFamily: 'ui-monospace, Menlo, Consolas, monospace',
  fontSize: 9, color: 'rgba(120,124,135,.6)',
};
const bodyStyle = (variant: Variant): CSSProperties => ({
  fontSize: 11, fontWeight: 200, lineHeight: 1.5,
  color: variant === 'error' ? SPEAKER_COLORS.error : 'rgba(230,232,238,.88)',
});
const rowStyle: CSSProperties = { padding: '10px 16px' };

export function TranscriptTurn({ variant, speaker, body, timestamp, errorReason }: Props) {
  return (
    <div style={rowStyle} data-testid="transcript-turn" data-variant={variant}>
      <div style={speakerStyle(variant)}>
        <span>{speaker}</span>
        <span style={tsStyle}>{fmtClock(timestamp)}</span>
      </div>
      <div style={bodyStyle(variant)}>
        {variant === 'error' && errorReason ? `× failed to send · ${errorReason}` : body}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Implement Transcript**

```tsx
// observatory/web-src/src/chat/Transcript.tsx
/**
 * Filtered firehose view: hive/external/perception + hive/motor/speech/complete,
 * unioned with pending optimistic turns from the store. Dedupe happens at
 * render time by envelope id. Spec §3.3, §6.4, §6.5.
 */
import { useMemo, useRef, useEffect, type CSSProperties } from 'react';

import { useStore, type Envelope, type PendingChatTurn } from '../store';
import { TranscriptTurn } from './TranscriptTurn';

const TRANSCRIPT_TOPICS = new Set(['hive/external/perception', 'hive/motor/speech/complete']);

type Turn = {
  key: string;
  variant: 'user' | 'hive' | 'audio_placeholder' | 'error';
  speaker: string;
  body: string;
  timestamp: string;
  errorReason?: string;
  sortMs: number;
};

function envelopeToTurn(e: Envelope): Turn | null {
  const inner = e.envelope as {
    id: string; timestamp: string;
    payload?: { data?: Record<string, unknown> };
  };
  const data = inner.payload?.data ?? {};
  if (e.topic === 'hive/external/perception') {
    return {
      key: inner.id,
      variant: 'user',
      speaker: String(data.speaker ?? 'unknown'),
      body: String(data.text ?? ''),
      timestamp: inner.timestamp,
      sortMs: Date.parse(inner.timestamp) || e.observed_at,
    };
  }
  // hive/motor/speech/complete
  const text = data.text;
  if (typeof text === 'string' && text.length > 0) {
    return {
      key: inner.id,
      variant: 'hive',
      speaker: 'hive',
      body: text,
      timestamp: inner.timestamp,
      sortMs: Date.parse(inner.timestamp) || e.observed_at,
    };
  }
  // audio placeholder — no text payload
  const ms = typeof data.duration_ms === 'number' ? data.duration_ms : null;
  const dur = ms !== null ? ` · ${Math.round(ms / 1000)}s` : '';
  return {
    key: inner.id,
    variant: 'audio_placeholder',
    speaker: 'hive',
    body: `🔊 hive spoke${dur}`,
    timestamp: inner.timestamp,
    sortMs: Date.parse(inner.timestamp) || e.observed_at,
  };
}

function pendingToTurn(p: PendingChatTurn): Turn {
  return {
    key: p.id,
    variant: p.status === 'failed' ? 'error' : 'user',
    speaker: p.speaker,
    body: p.text,
    timestamp: p.timestamp,
    errorReason: p.errorReason,
    sortMs: Date.parse(p.timestamp) || Date.now(),
  };
}

export function Transcript() {
  const envelopes = useStore((s) => s.envelopes);
  const pending = useStore((s) => s.pendingChatTurns);

  const turns = useMemo(() => {
    const fromRing: Turn[] = [];
    const seenIds = new Set<string>();
    for (const e of envelopes) {
      if (!TRANSCRIPT_TOPICS.has(e.topic)) continue;
      const turn = envelopeToTurn(e);
      if (turn) {
        fromRing.push(turn);
        seenIds.add(turn.key);
      }
    }
    const fromPending: Turn[] = [];
    for (const p of Object.values(pending)) {
      if (seenIds.has(p.id)) continue;  // ring already has it — dedupe
      fromPending.push(pendingToTurn(p));
    }
    return [...fromRing, ...fromPending].sort((a, b) => a.sortMs - b.sortMs);
  }, [envelopes, pending]);

  // Auto-scroll-to-bottom when within 40px of the end (spec §6.3).
  const bodyRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    const distanceFromEnd = el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromEnd < 40) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const containerStyle: CSSProperties = { flex: 1, overflowY: 'auto' };

  return (
    <div ref={bodyRef} style={containerStyle} data-testid="transcript">
      {turns.map((t) => (
        <TranscriptTurn
          key={t.key}
          variant={t.variant}
          speaker={t.speaker}
          body={t.body}
          timestamp={t.timestamp}
          errorReason={t.errorReason}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Run tests; expect PASS**

```bash
npx vitest run src/chat/Transcript.test.tsx
npx tsc -b
```
Expected: 6 passed; typecheck clean.

- [ ] **Step 6: Commit**

```bash
cd C:/repos/hive
git add observatory/web-src/src/chat/Transcript.tsx observatory/web-src/src/chat/TranscriptTurn.tsx observatory/web-src/src/chat/Transcript.test.tsx
git commit -m "$(cat <<'EOF'
observatory(v4): Transcript + TranscriptTurn

Filtered view of the existing envelope ring scoped to
hive/external/perception (user turns) and hive/motor/speech/complete
(hive turns / audio placeholder). Unions with optimistic pendingChatTurns
from the store, deduped at render time by envelope id. Auto-scroll to
bottom when within 40px (matches v3 firehose / messages behaviour).

TranscriptTurn renders one row in the v3 inspector style — no card
chrome, speaker tag in caps + colour-coded (user blue, hive purple,
error red), Inter 200 body, mono timestamp. Spec §6.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: ChatInput

**Files:**
- Create: `observatory/web-src/src/chat/ChatInput.tsx`
- Create: `observatory/web-src/src/chat/ChatInput.test.tsx`

**Spec sections:** §6.7, §6.5 (optimistic lifecycle)

- [ ] **Step 1: Write ChatInput tests**

```tsx
// observatory/web-src/src/chat/ChatInput.test.tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { useStore } from '../store';
import { ChatInput } from './ChatInput';
import * as api from './api';

describe('ChatInput', () => {
  beforeEach(() => {
    useStore.setState({ pendingChatTurns: {} });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    useStore.setState({ pendingChatTurns: {} });
  });

  it('disables submit when text is empty after trim', async () => {
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox');
    const u = userEvent.setup();
    await u.type(textarea, '   ');
    await u.keyboard('{Enter}');
    expect(useStore.getState().pendingChatTurns).toEqual({});
  });

  it('submit on Enter: adds optimistic pending turn and POSTs', async () => {
    const post = vi.spyOn(api, 'postChatText').mockResolvedValue({
      id: 'env-1', timestamp: '2026-04-29T14:00:00.000Z',
    });
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox');
    const u = userEvent.setup();
    await u.type(textarea, 'hello');
    await u.keyboard('{Enter}');

    // Optimistic turn appears immediately (keyed by client id, status sending).
    const pending = Object.values(useStore.getState().pendingChatTurns);
    expect(pending).toHaveLength(1);
    expect(pending[0].text).toBe('hello');
    expect(['sending', 'sent']).toContain(pending[0].status);
    expect(post).toHaveBeenCalledWith('hello', undefined);

    // Wait microtask: pending turn rekeyed to envelope id.
    await Promise.resolve();
    await Promise.resolve();
    const after = useStore.getState().pendingChatTurns;
    expect(after['env-1']).toBeTruthy();
    expect(after['env-1'].status).toBe('sent');
  });

  it('Shift+Enter inserts a newline and does not submit', async () => {
    const post = vi.spyOn(api, 'postChatText');
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    const u = userEvent.setup();
    await u.type(textarea, 'line one');
    await u.keyboard('{Shift>}{Enter}{/Shift}');
    await u.type(textarea, 'line two');
    expect(textarea.value).toBe('line one\nline two');
    expect(post).not.toHaveBeenCalled();
  });

  it('clears textarea after successful submit', async () => {
    vi.spyOn(api, 'postChatText').mockResolvedValue({
      id: 'env-1', timestamp: 't',
    });
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    const u = userEvent.setup();
    await u.type(textarea, 'hi');
    await u.keyboard('{Enter}');
    expect(textarea.value).toBe('');
  });

  it('flips pending turn to failed on POST error', async () => {
    vi.spyOn(api, 'postChatText').mockRejectedValue(
      new api.ChatPostError('publish_failed', 'broker down'),
    );
    render(<ChatInput />);
    const textarea = screen.getByRole('textbox');
    const u = userEvent.setup();
    await u.type(textarea, 'hi');
    await u.keyboard('{Enter}');
    await Promise.resolve();
    await Promise.resolve();
    const pending = Object.values(useStore.getState().pendingChatTurns);
    expect(pending).toHaveLength(1);
    expect(pending[0].status).toBe('failed');
    expect(pending[0].errorReason).toMatch(/broker down/);
  });
});
```

- [ ] **Step 2: Run; expect ImportError**

```bash
cd observatory/web-src
npx vitest run src/chat/ChatInput.test.tsx
```
Expected: missing `./ChatInput`.

- [ ] **Step 3: Implement ChatInput**

```tsx
// observatory/web-src/src/chat/ChatInput.tsx
/**
 * Chat input: auto-grow textarea + Enter-to-submit + optimistic lifecycle.
 *
 * Lifecycle (spec §6.5):
 *   1. User hits Enter. Add pending turn with status='sending', keyed by
 *      a temp client id. Clear the textarea.
 *   2. POST /sensory/text/in. On 202 success, rekey the pending turn
 *      from temp id to the server's envelope id and set status='sent'.
 *      The Transcript dedupes by id once the firehose echo arrives.
 *   3. On POST failure, flip the pending turn to status='failed' with the
 *      ChatPostError detail in errorReason. The Transcript renders it as
 *      an error placeholder. The temp id stays — the user can re-type a
 *      fresh message; the failed turn lingers until cleared.
 */
import { useRef, useState, type CSSProperties, type KeyboardEvent } from 'react';

import { useStore, type PendingChatTurn } from '../store';
import { ChatPostError, postChatText } from './api';

let _clientIdCounter = 0;
function nextClientId(): string {
  _clientIdCounter += 1;
  return `chat-client-${Date.now()}-${_clientIdCounter}`;
}

const inputContainerStyle: CSSProperties = {
  borderTop: '1px solid rgba(80,84,96,.25)',
  padding: '10px 14px',
  display: 'flex', flexDirection: 'column', gap: 4,
};
const textareaStyle: CSSProperties = {
  width: '100%', resize: 'none',
  background: 'transparent', border: 'none', outline: 'none',
  color: 'rgba(230,232,238,.9)',
  fontFamily: 'Inter, ui-sans-serif, sans-serif',
  fontWeight: 200, fontSize: 11, lineHeight: 1.5,
};
const hintStyle: CSSProperties = {
  fontFamily: 'ui-monospace, Consolas, monospace',
  fontSize: 9, color: 'rgba(120,124,135,.55)',
  letterSpacing: '.3px',
};

const MAX_ROWS = 6;
const ROW_PX = 16;  // line-height 1.5 × 11px ≈ 16

export function ChatInput() {
  const [text, setText] = useState('');
  const ref = useRef<HTMLTextAreaElement>(null);
  const addPending = useStore((s) => s.addPendingChatTurn);
  const resolvePending = useStore((s) => s.resolvePendingChatTurn);
  const failPending = useStore((s) => s.failPendingChatTurn);

  function autoGrow(el: HTMLTextAreaElement) {
    el.style.height = 'auto';
    const next = Math.min(el.scrollHeight, ROW_PX * (MAX_ROWS + 1));
    el.style.height = `${next}px`;
  }

  async function submit() {
    const trimmed = text.trim();
    if (!trimmed) return;
    const clientId = nextClientId();
    const optimistic: PendingChatTurn = {
      id: clientId,
      text: trimmed,
      speaker: 'Larry',  // server's default; we display the same locally
      timestamp: new Date().toISOString(),
      status: 'sending',
    };
    addPending(optimistic);
    setText('');
    if (ref.current) {
      ref.current.style.height = 'auto';
    }

    try {
      const { id, timestamp } = await postChatText(trimmed);
      resolvePending(clientId, id, timestamp);
    } catch (e) {
      const reason = e instanceof ChatPostError ? `${e.kind}: ${e.detail}` : String(e);
      failPending(clientId, reason);
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  return (
    <div style={inputContainerStyle}>
      <textarea
        ref={ref}
        rows={2}
        placeholder="say something to hive…"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          autoGrow(e.currentTarget);
        }}
        onKeyDown={onKeyDown}
        style={textareaStyle}
      />
      <div style={hintStyle}>enter to send · esc to dismiss · c to toggle</div>
    </div>
  );
}
```

- [ ] **Step 4: Run; expect PASS**

```bash
npx vitest run src/chat/ChatInput.test.tsx
npx tsc -b
```
Expected: 5 passed; typecheck clean.

- [ ] **Step 5: Commit**

```bash
cd C:/repos/hive
git add observatory/web-src/src/chat/ChatInput.tsx observatory/web-src/src/chat/ChatInput.test.tsx
git commit -m "$(cat <<'EOF'
observatory(v4): ChatInput — auto-grow textarea + optimistic lifecycle

Enter submits, Shift+Enter newlines. On submit:
  - adds an optimistic pending turn keyed by a temp client id
  - clears the textarea
  - POSTs /sensory/text/in
  - on 202: rekeys pending turn from temp id -> envelope id, status=sent
    (Transcript dedupes by id once the firehose echoes the envelope back)
  - on failure: flips pending turn to status=failed with the ChatPostError
    detail; Transcript renders the error placeholder

Visual style matches the v3 dock input: borderless transparent textarea,
Inter 200 11px, mono hint line below. Spec §6.5, §6.7.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: ChatOverlay (frame + drag + resize)

**Files:**
- Create: `observatory/web-src/src/chat/ChatOverlay.tsx`
- Create: `observatory/web-src/src/chat/ChatOverlay.test.tsx`

**Spec sections:** §6.3

- [ ] **Step 1: Write ChatOverlay tests**

```tsx
// observatory/web-src/src/chat/ChatOverlay.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useStore } from '../store';
import { ChatOverlay } from './ChatOverlay';

describe('ChatOverlay', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'innerWidth', { value: 1200, configurable: true });
    Object.defineProperty(window, 'innerHeight', { value: 800, configurable: true });
    useStore.setState({
      chatVisible: false,
      chatPosition: { x: 0, y: 16 },
      chatSize: { w: 320, h: 260 },
      pendingChatTurns: {},
      envelopes: [],
    });
  });
  afterEach(() => {
    useStore.setState({ chatVisible: false });
  });

  it('renders nothing when chatVisible is false', () => {
    render(<ChatOverlay />);
    expect(screen.queryByTestId('chat-overlay')).toBeNull();
  });

  it('renders the overlay when chatVisible is true', () => {
    useStore.setState({ chatVisible: true });
    render(<ChatOverlay />);
    expect(screen.getByTestId('chat-overlay')).toBeInTheDocument();
    expect(screen.getByText('chat with hive')).toBeInTheDocument();
  });

  it('lazy-computes default position to top-right on first open', () => {
    // chatPosition.x starts at 0; opening should snap to viewport.w - size.w - 16.
    useStore.setState({ chatPosition: { x: 0, y: 16 } });
    useStore.setState({ chatVisible: true });
    render(<ChatOverlay />);
    const pos = useStore.getState().chatPosition;
    expect(pos.x).toBe(1200 - 320 - 16);  // 864
  });

  it('preserves user-set position on subsequent opens', () => {
    useStore.setState({ chatPosition: { x: 100, y: 100 }, chatVisible: true });
    render(<ChatOverlay />);
    const pos = useStore.getState().chatPosition;
    expect(pos).toEqual({ x: 100, y: 100 });
  });

  it('drag from header updates chatPosition', () => {
    useStore.setState({ chatVisible: true, chatPosition: { x: 100, y: 100 } });
    render(<ChatOverlay />);
    const header = screen.getByTestId('chat-header');
    fireEvent.pointerDown(header, { clientX: 200, clientY: 150 });
    fireEvent.pointerMove(window, { clientX: 250, clientY: 180 });
    fireEvent.pointerUp(window);
    const pos = useStore.getState().chatPosition;
    expect(pos.x).toBe(150);  // 100 + (250 - 200)
    expect(pos.y).toBe(130);  // 100 + (180 - 150)
  });

  it('drag clamps position to keep overlay inside the viewport', () => {
    useStore.setState({ chatVisible: true, chatPosition: { x: 100, y: 100 } });
    render(<ChatOverlay />);
    const header = screen.getByTestId('chat-header');
    fireEvent.pointerDown(header, { clientX: 200, clientY: 150 });
    fireEvent.pointerMove(window, { clientX: 999_999, clientY: 999_999 });
    fireEvent.pointerUp(window);
    const pos = useStore.getState().chatPosition;
    expect(pos.x).toBeLessThanOrEqual(1200 - 320 - 16);
    expect(pos.y).toBeLessThanOrEqual(800 - 260 - 16);
  });

  it('resize from corner handle updates chatSize and clamps to range', () => {
    useStore.setState({ chatVisible: true, chatSize: { w: 320, h: 260 } });
    render(<ChatOverlay />);
    const handle = screen.getByTestId('chat-resize-handle');
    fireEvent.pointerDown(handle, { clientX: 0, clientY: 0 });
    fireEvent.pointerMove(window, { clientX: 100, clientY: 50 });
    fireEvent.pointerUp(window);
    const size = useStore.getState().chatSize;
    expect(size.w).toBe(420);  // 320 + 100
    expect(size.h).toBe(310);  // 260 + 50
  });

  it('resize clamps below minimum', () => {
    useStore.setState({ chatVisible: true, chatSize: { w: 320, h: 260 } });
    render(<ChatOverlay />);
    const handle = screen.getByTestId('chat-resize-handle');
    fireEvent.pointerDown(handle, { clientX: 0, clientY: 0 });
    fireEvent.pointerMove(window, { clientX: -10000, clientY: -10000 });
    fireEvent.pointerUp(window);
    const size = useStore.getState().chatSize;
    expect(size.w).toBe(240);   // min
    expect(size.h).toBe(180);   // min
  });
});
```

- [ ] **Step 2: Run; expect ImportError**

```bash
cd observatory/web-src
npx vitest run src/chat/ChatOverlay.test.tsx
```
Expected: missing `./ChatOverlay`.

- [ ] **Step 3: Implement ChatOverlay**

```tsx
// observatory/web-src/src/chat/ChatOverlay.tsx
/**
 * Floating chat overlay. Spec §6.3.
 *
 * On first open with default chatPosition (x === 0), snap to top-right
 * (viewport.w - size.w - 16, 16). Subsequent opens preserve whatever
 * position the user dragged it to (also persisted via useChatPersistence).
 *
 * Drag: pointerdown on the header captures (startClientX/Y, startPosX/Y)
 * in refs; pointermove on window updates chatPosition with the delta,
 * clamped to viewport. pointerup releases.
 *
 * Resize: same pattern from the bottom-right corner handle. Width clamped
 * [240, 720]; height clamped [180, 720].
 */
import { useEffect, useRef, type CSSProperties, type PointerEvent as RPE } from 'react';

import { useStore } from '../store';
import { Transcript } from './Transcript';
import { ChatInput } from './ChatInput';

const VIEWPORT_MARGIN = 16;
const W_MIN = 240, W_MAX = 720;
const H_MIN = 180, H_MAX = 720;

const frameStyle: CSSProperties = {
  position: 'fixed',
  background: 'rgba(14,15,19,.72)',
  backdropFilter: 'blur(14px)',
  border: '1px solid rgba(80,84,96,.45)',
  borderRadius: 4,
  display: 'flex', flexDirection: 'column',
  fontFamily: 'Inter, ui-sans-serif, sans-serif',
  zIndex: 50,
  transition: 'opacity .18s ease',
};
const headerStyle: CSSProperties = {
  fontSize: 9, letterSpacing: '.5px', textTransform: 'uppercase',
  color: 'rgba(180,184,192,.6)',
  padding: '10px 14px',
  borderBottom: '1px solid rgba(80,84,96,.25)',
  cursor: 'grab', userSelect: 'none',
};
const resizeHandleStyle: CSSProperties = {
  position: 'absolute', bottom: 0, right: 0,
  width: 12, height: 12, cursor: 'nwse-resize',
};

function clampPos(
  pos: { x: number; y: number }, size: { w: number; h: number },
): { x: number; y: number } {
  const maxX = Math.max(0, window.innerWidth - size.w - VIEWPORT_MARGIN);
  const maxY = Math.max(0, window.innerHeight - size.h - VIEWPORT_MARGIN);
  return {
    x: Math.min(Math.max(VIEWPORT_MARGIN, pos.x), maxX),
    y: Math.min(Math.max(VIEWPORT_MARGIN, pos.y), maxY),
  };
}
function clampSize(s: { w: number; h: number }): { w: number; h: number } {
  return {
    w: Math.min(Math.max(W_MIN, s.w), W_MAX),
    h: Math.min(Math.max(H_MIN, s.h), H_MAX),
  };
}

export function ChatOverlay() {
  const visible = useStore((s) => s.chatVisible);
  const pos = useStore((s) => s.chatPosition);
  const size = useStore((s) => s.chatSize);
  const setPos = useStore((s) => s.setChatPosition);
  const setSize = useStore((s) => s.setChatSize);

  // Lazy default-position computation on first open.
  // chatPosition.x starts at 0 (placeholder); we snap to top-right when
  // the user opens the overlay and the position hasn't been set.
  useEffect(() => {
    if (!visible) return;
    if (pos.x === 0 && pos.y === 16) {
      setPos({
        x: window.innerWidth - size.w - VIEWPORT_MARGIN,
        y: VIEWPORT_MARGIN,
      });
    }
  }, [visible, pos.x, pos.y, size.w, setPos]);

  // Drag refs
  const dragStart = useRef<{ cx: number; cy: number; px: number; py: number } | null>(null);
  const resizeStart = useRef<{ cx: number; cy: number; w: number; h: number } | null>(null);

  useEffect(() => {
    function onMove(e: PointerEvent) {
      if (dragStart.current) {
        const { cx, cy, px, py } = dragStart.current;
        setPos(clampPos({ x: px + (e.clientX - cx), y: py + (e.clientY - cy) }, size));
      } else if (resizeStart.current) {
        const { cx, cy, w, h } = resizeStart.current;
        setSize(clampSize({ w: w + (e.clientX - cx), h: h + (e.clientY - cy) }));
      }
    }
    function onUp() {
      dragStart.current = null;
      resizeStart.current = null;
    }
    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
    };
  }, [setPos, setSize, size.w, size.h]);

  if (!visible) return null;

  function onHeaderDown(e: RPE) {
    dragStart.current = { cx: e.clientX, cy: e.clientY, px: pos.x, py: pos.y };
  }
  function onResizeDown(e: RPE) {
    e.stopPropagation();
    resizeStart.current = { cx: e.clientX, cy: e.clientY, w: size.w, h: size.h };
  }

  return (
    <div
      data-testid="chat-overlay"
      style={{ ...frameStyle, left: pos.x, top: pos.y, width: size.w, height: size.h }}
    >
      <div data-testid="chat-header" style={headerStyle} onPointerDown={onHeaderDown}>
        chat with hive
      </div>
      <Transcript />
      <ChatInput />
      <div data-testid="chat-resize-handle" style={resizeHandleStyle} onPointerDown={onResizeDown} />
    </div>
  );
}
```

- [ ] **Step 4: Run; expect PASS**

```bash
npx vitest run src/chat/ChatOverlay.test.tsx
npx tsc -b
```
Expected: 8 passed; typecheck clean.

- [ ] **Step 5: Commit**

```bash
cd C:/repos/hive
git add observatory/web-src/src/chat/ChatOverlay.tsx observatory/web-src/src/chat/ChatOverlay.test.tsx
git commit -m "$(cat <<'EOF'
observatory(v4): ChatOverlay — floating frame with drag + resize

Translucent draggable HUD panel. Mounts Transcript + ChatInput. Header
is the drag region; bottom-right corner is the resize handle. Position
clamps inside viewport with 16px margin; size clamps to [240,720] x
[180,720]. On first open with default position the overlay snaps to
top-right; subsequent opens preserve user-set position.

Visual style matches the spec §6.3 / Larry's thin/soft/hover-reveal
aesthetic: rgba(14,15,19,.72) bg with backdrop-blur(14px), 1px soft
border, 4px radius, no shadow, .18s opacity fade, Inter 200 throughout.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: useChatKeys hotkey

**Files:**
- Create: `observatory/web-src/src/chat/useChatKeys.ts`
- Create: `observatory/web-src/src/chat/useChatKeys.test.tsx`

**Spec sections:** §6.6

- [ ] **Step 1: Write the hotkey tests**

```tsx
// observatory/web-src/src/chat/useChatKeys.test.tsx
import { render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { useStore } from '../store';
import { useChatKeys } from './useChatKeys';

function Harness() {
  useChatKeys();
  return null;
}

describe('useChatKeys', () => {
  beforeEach(() => {
    useStore.setState({ chatVisible: false });
  });
  afterEach(() => {
    useStore.setState({ chatVisible: false });
  });

  function fireKey(key: string, target: EventTarget = document.body) {
    const e = new KeyboardEvent('keydown', { key, bubbles: true });
    target.dispatchEvent(e);
  }

  it('c toggles chatVisible', () => {
    render(<Harness />);
    expect(useStore.getState().chatVisible).toBe(false);
    fireKey('c');
    expect(useStore.getState().chatVisible).toBe(true);
    fireKey('c');
    expect(useStore.getState().chatVisible).toBe(false);
  });

  it('c is ignored when an input has focus', () => {
    render(<Harness />);
    const input = document.createElement('input');
    document.body.appendChild(input);
    input.focus();
    fireKey('c', input);
    expect(useStore.getState().chatVisible).toBe(false);
    document.body.removeChild(input);
  });

  it('c is ignored when a textarea has focus', () => {
    render(<Harness />);
    const ta = document.createElement('textarea');
    document.body.appendChild(ta);
    ta.focus();
    fireKey('c', ta);
    expect(useStore.getState().chatVisible).toBe(false);
    document.body.removeChild(ta);
  });

  it('Esc closes the overlay when chatVisible is true and target is inside the overlay', () => {
    useStore.setState({ chatVisible: true });
    render(<Harness />);
    const overlay = document.createElement('div');
    overlay.setAttribute('data-testid', 'chat-overlay');
    document.body.appendChild(overlay);
    fireKey('Escape', overlay);
    expect(useStore.getState().chatVisible).toBe(false);
    document.body.removeChild(overlay);
  });

  it('Esc is ignored when chatVisible is false', () => {
    render(<Harness />);
    fireKey('Escape');
    expect(useStore.getState().chatVisible).toBe(false);
  });

  it('Esc is ignored when target is outside the overlay', () => {
    useStore.setState({ chatVisible: true });
    render(<Harness />);
    fireKey('Escape', document.body);
    expect(useStore.getState().chatVisible).toBe(true);
  });
});
```

- [ ] **Step 2: Implement the hook**

```ts
// observatory/web-src/src/chat/useChatKeys.ts
/**
 * Window-level keydown for the chat overlay.
 *  - `c` (no modifiers, no input/textarea/contenteditable focus): toggle
 *    chatVisible.
 *  - `Escape` (chatVisible === true, target inside the overlay): close.
 *
 * Spec §6.6.
 */
import { useEffect } from 'react';

import { useStore } from '../store';

function targetIsTextSink(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  const tag = t.tagName.toLowerCase();
  return tag === 'input' || tag === 'textarea' || t.isContentEditable;
}

function targetInOverlay(t: EventTarget | null): boolean {
  if (!(t instanceof HTMLElement)) return false;
  return !!t.closest('[data-testid="chat-overlay"]');
}

export function useChatKeys(): void {
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      // Esc dismiss
      if (e.key === 'Escape') {
        const { chatVisible, setChatVisible } = useStore.getState();
        if (chatVisible && targetInOverlay(e.target)) {
          e.preventDefault();
          setChatVisible(false);
        }
        return;
      }
      // c toggle
      if (e.key === 'c' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        if (targetIsTextSink(e.target)) return;
        const { chatVisible, setChatVisible } = useStore.getState();
        e.preventDefault();
        setChatVisible(!chatVisible);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
```

- [ ] **Step 3: Run; expect PASS**

```bash
cd observatory/web-src
npx vitest run src/chat/useChatKeys.test.tsx
npx tsc -b
```
Expected: 6 passed; typecheck clean.

- [ ] **Step 4: Commit**

```bash
cd C:/repos/hive
git add observatory/web-src/src/chat/useChatKeys.ts observatory/web-src/src/chat/useChatKeys.test.tsx
git commit -m "$(cat <<'EOF'
observatory(v4): useChatKeys — c toggles overlay, Esc dismisses

Single window-level keydown listener:
  - `c` (no modifiers, no input/textarea/contenteditable focus) toggles
    chatVisible. Same input-focus guard as useDockKeys.
  - `Escape` (chatVisible true + target inside overlay) closes the
    overlay. Doesn't propagate to the inspector dismiss handler because
    the inspector listens with its own targeting check.

Spec §6.6.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: App.tsx mount + production build

**Files:**
- Modify: `observatory/web-src/src/App.tsx`

**Spec sections:** §6.1 ("Mounted in App.tsx as a sibling to <Inspector /> and <Dock />")

- [ ] **Step 1: Modify App.tsx**

Open `observatory/web-src/src/App.tsx`. The file currently looks like:

```tsx
export function App() {
  useEffect(() => connect(useStore), []);
  useInspectorKeys();
  useDockKeys();
  return (
    <div className="relative w-full h-full">
      <Scene />
      <Hud />
      <Inspector />
      <Dock />
    </div>
  );
}
```

Apply two changes:

(a) Add imports near the top:

```tsx
import { ChatOverlay } from './chat/ChatOverlay';
import { useChatKeys } from './chat/useChatKeys';
import { useChatPersistence } from './chat/useChatPersistence';
```

(b) Inside `App()` install the chat hooks and mount the overlay:

```tsx
export function App() {
  useEffect(() => connect(useStore), []);
  useInspectorKeys();
  useDockKeys();
  useChatKeys();
  useChatPersistence(useStore);
  return (
    <div className="relative w-full h-full">
      <Scene />
      <Hud />
      <Inspector />
      <Dock />
      <ChatOverlay />
    </div>
  );
}
```

- [ ] **Step 2: Run the full vitest suite**

```bash
cd observatory/web-src
npx vitest run
```
Expected: previous tests + 6 chat tests = clean.

- [ ] **Step 3: Run typecheck and production build**

```bash
npx tsc -b
npm run build
```
Expected: typecheck clean; `observatory/web/index.html` + `assets/index-*.{css,js}` emitted; chunk-size warning (pre-existing) is fine.

- [ ] **Step 4: Commit**

```bash
cd C:/repos/hive
git add observatory/web-src/src/App.tsx
git commit -m "$(cat <<'EOF'
observatory(v4): mount ChatOverlay + chat hooks in App.tsx

ChatOverlay sits as a sibling to Scene/Hud/Inspector/Dock.
useChatKeys + useChatPersistence install at the App root same as
the existing inspector/dock hooks. Spec §6.1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Verification + HANDOFF closure

**Files:**
- Modify: `observatory/HANDOFF.md`

**This task has no code changes** — it runs the full automated suite, captures the snapshot for the HANDOFF, and closes out v4.

- [ ] **Step 1: Run the full backend unit suite**

```bash
cd C:/repos/hive
python -m pytest observatory/tests/unit/ -q
```
Expected: previous count (101 unit + N component existing) + new sensory tests ≈ 113+ unit passing.

- [ ] **Step 2: Run the full backend component suite**

```bash
python -m pytest observatory/tests/component/ -m component -v
```
Expected: 4 passed (3 v1/v2/v3 + 1 v4 round-trip).

- [ ] **Step 3: Run ruff over all v4 paths**

```bash
python -m ruff check observatory/sensory/ observatory/tests/unit/sensory/ observatory/config.py observatory/service.py observatory/tests/component/test_end_to_end.py
```
Expected: clean.

- [ ] **Step 4: Run the full frontend vitest suite**

```bash
cd observatory/web-src
npx vitest run
```
Expected: previous 168 + 33 new chat tests ≈ 201 passing.

- [ ] **Step 5: Typecheck + production build**

```bash
npx tsc -b
npm run build
```
Expected: clean; bundle emitted.

- [ ] **Step 6: Smoke-test the full app against a local broker**

Manual: with the Hive broker running at `127.0.0.1:1883`, start the observatory:

```bash
cd C:/repos/hive
python -m uvicorn observatory.service:app --reload  # or whatever the existing dev command is
```

Open http://localhost:8765, hit `c`, type a message, press Enter. Verify:
- Optimistic turn appears immediately.
- The same turn re-renders without flicker once the firehose echo arrives (dedupe by id).
- No server console errors.
- Pressing `c` again hides the overlay; pressing `c` again shows it with the same position.
- Drag the header → position persists across page reload.
- Drag the resize handle → size persists across page reload.

Document any issues in `observatory/memory/decisions.md` (do *not* fix in this task — file follow-ups for v4.1).

- [ ] **Step 7: Update HANDOFF.md**

Edit `observatory/HANDOFF.md`:

(a) Update the top-line:

```markdown
*Last updated: 2026-04-29 (session N — v4 SHIPPED)*

**Canonical resume prompt:** `continue observatory v5` (v5 not yet scoped)
```

(b) In the State snapshot table, append after the v3 row:

```markdown
| v4 brainstorm | ✅ Complete | 2026-04-29 — visual-companion mockup (placement: floating overlay) |
| v4 spec written | ✅ Complete | `observatory/docs/specs/2026-04-29-observatory-v4-chat-design.md` · commit `<spec_commit>` |
| v4 plan written | ✅ Complete | `observatory/docs/plans/2026-04-29-observatory-v4-plan.md` (13 tasks) · commit `<plan_commit>` |
| v4 Task 1 — sensory skeleton + Settings chat fields | ✅ Complete | `<task1_commit>` |
| v4 Task 2 — SensoryPublisher | ✅ Complete | `<task2_commit>` |
| v4 Task 3 — POST /sensory/text/in route + service.py wiring | ✅ Complete | `<task3_commit>` |
| v4 Task 4 — component test (POST → real broker round-trip) | ✅ Complete | `<task4_commit>` |
| v4 Task 5 — code-change proposal artifacts | ✅ Complete | `<task5_commit>` |
| v4 Task 6 — store chat slice + useChatPersistence | ✅ Complete | `<task6_commit>` |
| v4 Task 7 — chat/api.ts | ✅ Complete | `<task7_commit>` |
| v4 Task 8 — Transcript + TranscriptTurn | ✅ Complete | `<task8_commit>` |
| v4 Task 9 — ChatInput | ✅ Complete | `<task9_commit>` |
| v4 Task 10 — ChatOverlay (drag/resize) | ✅ Complete | `<task10_commit>` |
| v4 Task 11 — useChatKeys hotkey | ✅ Complete | `<task11_commit>` |
| v4 Task 12 — App.tsx mount | ✅ Complete | `<task12_commit>` |
| v4 Task 13 — verification + HANDOFF closure | ✅ Complete | this commit |
| **v4 — SHIPPED** | ✅ | |
```

(c) Add a "Suite + lint snapshot (end of session N — v4 ship)" section with the actual numbers from steps 1-5.

(d) Add v4 post-ship checklist — Larry may want to address in v5 or earlier:
- **Cosign `assoc-cortex-perception-2026-04-29.yaml`** to actually wire `hive/external/perception` into association_cortex's subscriptions. Until then, the chat is one-way.
- **Cosign `broca-complete-text-payload-2026-04-29.yaml`** when broca evolves speech-output handlers, so the chat transcript renders Hive's responses with text rather than just the audio-only placeholder.
- **STT for hive audio responses** — pick server-side (in `observatory/sensory/`) vs. browser-side (Web Speech API) once we see whether the audio-only placeholder is acceptable in practice.

(e) Add visual-E2E punch list (deferred to Larry's human-loop review):
- Hotkey: `c` toggles, `Esc` inside overlay dismisses, both ignored in input fields.
- Overlay: drag from header repositions; bottom-right handle resizes; both clamp to viewport / size range; both persist across reloads via localStorage.
- Transcript: user turns blue/caps, hive turns purple, audio placeholder for missing text payload, error placeholder on POST failure.
- Optimistic dedupe: turn appears instantly, doesn't double-render when firehose echo arrives ~tens of ms later.
- Pure-B: no spinner, no delivery receipt — silence is silence when broca produces no `complete`.

(f) Update "Authoritative references" to v4.

- [ ] **Step 8: Final verification commit**

```bash
git add observatory/HANDOFF.md
git commit -m "$(cat <<'EOF'
observatory: v4 ship — chat with Hive (sensory bridge + floating overlay)

13 tasks landed across session N: backend sensory module (4 files +
allowlist + Settings extension), one new MQTT topic
(hive/external/perception), POST /sensory/text/in route, frontend
chat/ subtree (8 files), App.tsx mount, two cosignable code-change
proposal artifacts under observatory/docs/proposals/.

Suite snapshot:
  - python -m pytest observatory/tests/unit/ -q → <N> passed
  - python -m pytest observatory/tests/component/ -m component -v → 4 passed
  - npx vitest run → <N> passed across <M> test files
  - python -m ruff check / npx tsc -b → clean

v4 chat is one-way until the assoc_cortex subscription proposal is
cosigned; Hive responses render as audio-only placeholders until the
broca text-payload proposal is cosigned. Both proposals live under
observatory/docs/proposals/ and follow Hive's existing
hive/system/codechange/proposed channel.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Checklist (run before handing off)

**Spec coverage:**
- §3.1 single new topic — Tasks 1, 4 (allowlist + component test).
- §3.2 envelope shape — Tasks 2, 3, 4 (publisher uses Envelope.new; route fills inner data; component asserts wire shape).
- §3.3 transcript reads two topics — Task 8 (Transcript filter).
- §3.4 nothing else added — proposal artifacts in Task 5 are inert.
- §4.1 module layout — Tasks 1, 2, 3.
- §4.2 allowlist — Task 1 + enforcement in Task 2.
- §4.3 publisher — Task 2.
- §4.4 routes + endpoint behaviour — Task 3 + Task 4 component verify.
- §4.5 Settings — Task 1.
- §5.1, §5.2 proposal artifacts — Task 5.
- §6.1 frontend module layout — Tasks 6-12 (one file per row).
- §6.2 store extension + persistence — Task 6.
- §6.3 ChatOverlay drag/resize/clamp — Task 10.
- §6.4 Transcript filter + variant rendering — Task 8.
- §6.5 dedupe by envelope id + optimistic lifecycle — Tasks 6, 7, 8, 9.
- §6.6 hotkey — Task 11.
- §6.7 ChatInput — Task 9.
- §7 pure-B (no spinner / receipt / indicator) — implicit; no spinner code is written anywhere; verify in Task 13 smoke.
- §8 Configuration — Task 1.
- §9 Tests — split across all tasks (each adds its own; component test in Task 4).
- §10 Out of scope — nothing built.
- §11 Constitutional — no edits under regions/; Task 13 verifies.

**Type consistency:**
- `PostChatTextResponse` used by Task 7 + 9 ✓
- `PendingChatTurn` defined in Task 6, consumed in 8 + 9 ✓
- `Envelope` factory signature consistent across Tasks 2, 3, 4 ✓
- `chat_default_speaker` / `chat_publish_qos` / `chat_text_max_length` named consistently across Tasks 1, 2, 3 ✓
- `addPendingChatTurn` / `resolvePendingChatTurn` / `failPendingChatTurn` / `dropPendingChatTurn` setter names consistent in Tasks 6 + 9 ✓

**No placeholders:**
- All test cases include real assertion code.
- All implementations include real bodies, not "implement here."
- All commit messages are HEREDOC with the required co-author footer.
- All commands are runnable as written (paths absolute or relative-to-cwd documented).

---

**End of plan.**
