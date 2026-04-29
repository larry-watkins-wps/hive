# v4 Task 3 — POST /sensory/text/in route + service.py wiring

You are implementing Task 3 of the observatory v4 plan. Read this prompt in full before touching any file. The spec is authoritative when prose conflicts.

## Your role

Implement Task 3 only. Drive to a green test suite + clean ruff + a single commit, then stop.

## Working directory

`C:/repos/hive`. Use `C:/repos/hive/.venv/Scripts/python.exe` for python invocations. **Set `PYTHONPATH=./src` for any pytest invocation that touches `shared.message_envelope`** (the workspace conftest puts `C:/repos/hive` on sys.path but the `shared` package lives at `src/shared/`).

Forward slashes; Unix shell syntax; no `cd`.

## Predecessor state

- Task 1 (commit `370db6f`): sensory module skeleton + Settings.chat_*.
- Task 2 (commit `473dd30`): `observatory/sensory/publisher.py::SensoryPublisher` with `connect/disconnect/publish` + `_parse_mqtt_url`.

Existing service.py at `observatory/service.py` already has:
- `lifespan(_app: FastAPI)` async context manager (around lines 256-317).
- A custom `@app.exception_handler(StarletteHTTPException)` that unwraps dict `detail` containing `"error"` to the top-level body, and adds `Cache-Control: no-store` to all error responses. (See lines 331-343.)
- `app.state.registry = registry` and `app.state.reader = reader` set in `build_app(...)` (lines 348-349).

The existing v1/v2 router (`observatory/api.py::build_router`) is mounted with `prefix="/api"`. v4's POST endpoint sits at `/sensory/text/in` *without* the `/api` prefix — it lives on its own router (per spec §4.1: "namespaced under `/sensory/*`").

## Spec excerpts (authoritative)

### §4.4 Routes

```python
class TextInRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    speaker: str | None = None  # falls through to settings default

class TextInResponse(BaseModel):
    id: str         # envelope id (UUID v4)
    timestamp: str  # ISO-8601 UTC
```

Endpoint behaviour:
- Accepts `{text, speaker?}`. Trims `text` (server-side); rejects empty post-trim with 422.
- Constructs the envelope via `Envelope.new(source_region="observatory.sensory", topic="hive/external/perception", content_type="application/json", data={...})`.
- Inner `data` fills: `speaker` defaults to `settings.chat_default_speaker`, `channel="observatory.chat"`, `source_modality="text"`.
- Calls `publisher.publish(envelope, qos=settings.chat_publish_qos)`.
- On success: `202 Accepted`, body `{id, timestamp}`.
- On `ForbiddenTopicError`: 500 (programming error).
- On `PublishFailedError`: 502 with body `{error: "publish_failed", message: "<aiomqtt error>"}`.
- On Pydantic validation failure: 422 with FastAPI's standard validation body.
- `Cache-Control: no-store` (mirrors v2's REST-route convention).

### §3.2 Envelope

`Envelope.new(...)` factory generates `id` (UUID v4) and `timestamp` (ISO-8601 ms-precision UTC). The factory's `attention_hint` defaults to `0.5` — leave it at default.

### §11 Read/write surface independence

Routes import publisher; routes do NOT import `RegionReader`. Read/write surfaces stay independent.

## Critical drift correction (plan vs. reality)

The plan's verbatim route uses `raise HTTPException(status_code=502, detail={"error": "publish_failed", "message": str(e)})`. The flat `{"error": ..., "message": ...}` body is produced by the custom `_observatory_http_exc_handler` in `service.py` — but **the route's unit tests build a bare `FastAPI()` without that handler**, so FastAPI's default body shape is `{"detail": {"error": ..., "message": ...}}` and `body["error"]` would `KeyError`.

**Two options:**
1. Use `JSONResponse(status_code=502, content={"error": ..., "message": ...}, headers={"Cache-Control": "no-store"})` directly in the route (the cleanest fix — body shape doesn't depend on the wider app's exception handler).
2. Have the test fixture register the same exception handler.

**Choose option 1.** Return `JSONResponse` directly from the route for both 500 and 502 error paths. This makes the route's contract stand alone — its body shape is guaranteed regardless of which app it's mounted on. Apply the same pattern to the success path (which the plan already does correctly).

You'll still need `Cache-Control: no-store` on the 422 validation-failure path. FastAPI's default validator response *does not* attach that header. Address that by registering a `RequestValidationError` handler on the test app fixture **AND** documenting that production runs through service.py's existing `_observatory_http_exc_handler` for `StarletteHTTPException` (which does add no-store, but only for HTTPException subclasses — `RequestValidationError` is its own type). For Task 3 you do not have to fix the 422-no-store gap globally; the existing test set does not assert on the 422 path's headers. Note this as a follow-up in your DONE_WITH_CONCERNS report if applicable.

The Cache-Control `no-store` test in the plan only asserts on the 202 path:

```python
def test_response_has_no_store_cache_control(client: TestClient):
    resp = client.post("/sensory/text/in", json={"text": "hi"})
    assert resp.headers.get("Cache-Control") == "no-store"
```

…which is satisfied by the success-path `JSONResponse(headers={"Cache-Control": "no-store"})`.

## Files to create / modify

1. **New:** `observatory/sensory/routes.py`
2. **New:** `observatory/tests/unit/sensory/test_routes.py`
3. **Modify:** `observatory/service.py` (3 locations: imports, lifespan, build_app)

## Step-by-step

### Step 1 — Write route tests (TDD red phase)

Create `observatory/tests/unit/sensory/test_routes.py`. Notes:
- Drop the unused `import json` from the plan's verbatim (ruff F401).
- Use forward annotations on test fixtures.
- Place inline `import aiomqtt` at module top-of-file rather than inside a single test (ruff PLC0415 / E402 hygiene).

```python
"""POST /sensory/text/in — validation, envelope construction, response shape."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import aiomqtt
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
    client: TestClient, stub_publisher: MagicMock, settings: Settings,
) -> None:
    """Spec §4.4: 202 + {id, timestamp} body; envelope per §3.2."""
    resp = client.post("/sensory/text/in", json={"text": "hi"})
    assert resp.status_code == 202  # noqa: PLR2004 — spec literal
    body = resp.json()
    assert "id" in body and len(body["id"]) >= 32  # noqa: PLR2004 — uuid hex string  # noqa: PLR2004
    assert body["timestamp"].endswith("Z")

    stub_publisher.publish.assert_awaited_once()
    envelope: Envelope = stub_publisher.publish.call_args.args[0]
    assert envelope.topic == "hive/external/perception"
    assert envelope.source_region == "observatory.sensory"
    assert envelope.id == body["id"]
    assert envelope.timestamp == body["timestamp"]
    data = envelope.payload.data
    assert data["text"] == "hi"
    assert data["speaker"] == settings.chat_default_speaker
    assert data["channel"] == "observatory.chat"
    assert data["source_modality"] == "text"
    assert stub_publisher.publish.call_args.kwargs["qos"] == settings.chat_publish_qos


def test_speaker_override_passes_through(
    client: TestClient, stub_publisher: MagicMock,
) -> None:
    resp = client.post("/sensory/text/in", json={"text": "hi", "speaker": "Operator"})
    assert resp.status_code == 202  # noqa: PLR2004
    envelope: Envelope = stub_publisher.publish.call_args.args[0]
    assert envelope.payload.data["speaker"] == "Operator"


def test_text_trimmed_server_side(
    client: TestClient, stub_publisher: MagicMock,
) -> None:
    resp = client.post("/sensory/text/in", json={"text": "  hello  "})
    assert resp.status_code == 202  # noqa: PLR2004
    envelope: Envelope = stub_publisher.publish.call_args.args[0]
    assert envelope.payload.data["text"] == "hello"


def test_empty_after_trim_rejected_with_422(
    client: TestClient, stub_publisher: MagicMock,
) -> None:
    resp = client.post("/sensory/text/in", json={"text": "   "})
    assert resp.status_code == 422  # noqa: PLR2004
    stub_publisher.publish.assert_not_awaited()


def test_oversize_text_rejected_with_422(
    client: TestClient, stub_publisher: MagicMock, settings: Settings,
) -> None:
    too_long = "x" * (settings.chat_text_max_length + 1)
    resp = client.post("/sensory/text/in", json={"text": too_long})
    assert resp.status_code == 422  # noqa: PLR2004
    stub_publisher.publish.assert_not_awaited()


def test_publish_failed_returns_502(
    client: TestClient, stub_publisher: MagicMock,
) -> None:
    stub_publisher.publish.side_effect = PublishFailedError(
        aiomqtt.MqttError("broker down")
    )
    resp = client.post("/sensory/text/in", json={"text": "hi"})
    assert resp.status_code == 502  # noqa: PLR2004
    body = resp.json()
    assert body["error"] == "publish_failed"
    assert "broker down" in body["message"]


def test_response_has_no_store_cache_control(client: TestClient) -> None:
    resp = client.post("/sensory/text/in", json={"text": "hi"})
    assert resp.headers.get("Cache-Control") == "no-store"
```

(Re-format the duplicated `# noqa: PLR2004` comment in `test_happy_path` — the editor should put a single `# noqa: PLR2004` at the end of the line; keep it tidy.)

### Step 2 — Run tests; expect ImportError

```
PYTHONPATH=./src C:/repos/hive/.venv/Scripts/python.exe -m pytest observatory/tests/unit/sensory/test_routes.py -q
```

### Step 3 — Implement the routes module

Create `observatory/sensory/routes.py`:

```python
"""POST /sensory/text/in — translator output endpoint.

The single v4 endpoint. Future audio/visual endpoints sit beside this
under the `/sensory/*` prefix. The publisher dependency is provided
via FastAPI's dependency-injection so component tests + unit tests
can swap the real publisher for a stub.

Spec §4.4.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from observatory.config import Settings
from observatory.sensory.errors import ForbiddenTopicError, PublishFailedError
from observatory.sensory.publisher import SensoryPublisher
from shared.message_envelope import Envelope

_NO_STORE = {"Cache-Control": "no-store"}


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
    ) -> JSONResponse:
        # Late max-length check uses runtime Settings, not an import-time literal.
        if len(body.text) > settings.chat_text_max_length:
            raise HTTPException(
                status_code=422,
                detail=[
                    {
                        "loc": ["body", "text"],
                        "msg": (
                            f"text exceeds chat_text_max_length="
                            f"{settings.chat_text_max_length}"
                        ),
                        "type": "value_error",
                    }
                ],
            )

        speaker = (
            body.speaker if body.speaker is not None else settings.chat_default_speaker
        )
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
        except ForbiddenTopicError as e:
            # Programming error: route always builds an allowlisted topic.
            return JSONResponse(
                status_code=500,
                content={"error": "forbidden_topic", "message": str(e)},
                headers=_NO_STORE,
            )
        except PublishFailedError as e:
            return JSONResponse(
                status_code=502,
                content={"error": "publish_failed", "message": str(e)},
                headers=_NO_STORE,
            )

        return JSONResponse(
            status_code=202,
            content={"id": envelope.id, "timestamp": envelope.timestamp},
            headers=_NO_STORE,
        )

    return router
```

Notes:
- Drop the unused `import json` from the plan's verbatim.
- Drop `Response` from the imports (we always return `JSONResponse`).
- Use `JSONResponse` for both error paths (the drift correction explained above).
- Keep `HTTPException` for the size-validator path so FastAPI emits its standard 422 body shape (Pydantic `min_length=1` already raises this kind for empty/whitespace; the late max-length check matches the format).

### Step 4 — Run route tests; expect PASS (7 tests)

```
PYTHONPATH=./src C:/repos/hive/.venv/Scripts/python.exe -m pytest observatory/tests/unit/sensory/test_routes.py -q
```

### Step 5 — Wire SensoryPublisher + router into service.py

Edit `observatory/service.py` in three places:

**(a)** Add to top-of-file imports (after the existing observatory.* imports, alphabetised):

```python
from observatory.sensory.publisher import SensoryPublisher
from observatory.sensory.routes import build_sensory_router
```

**(b)** Inside `lifespan(...)` — locate the `try: yield finally:` block (around lines 303-317). The instructions to "after the existing MQTT subscriber setup but before the yield" mean inserting after `task.add_done_callback(_on_mqtt_task_done)` (line 301) and before `try:` (line 303):

```python
        sensory_publisher = SensoryPublisher(settings)
        await sensory_publisher.connect()
        _app.state.sensory_publisher = sensory_publisher
        _app.state.settings = settings
```

(Use `_app` because the existing function signature names the FastAPI argument `_app` to dodge the ARG001 unused-arg lint. Don't rename it.)

Inside the existing `finally:` block (around line 305), call `sensory_publisher.disconnect()` *before* the existing teardown lines so it cleans up first:

```python
        finally:
            await sensory_publisher.disconnect()
            stop_event.set()
            ...  # existing teardown
```

**(c)** Inside `build_app(...)`, after the existing `app.include_router(build_router(region_registry=registry))` (line ~353), add:

```python
    app.include_router(build_sensory_router())
```

### Step 6 — Run full unit suite + lint

```
PYTHONPATH=./src C:/repos/hive/.venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q
C:/repos/hive/.venv/Scripts/python.exe -m ruff check observatory/sensory/ observatory/service.py observatory/tests/unit/sensory/
```

Expected: route tests (7) + earlier sensory tests (8) + config tests + remaining unit tests pass. The 3 pre-existing `test_mqtt_reconnect.py` failures (documented in `observatory/memory/decisions.md` 2026-04-29) will still fail — that's pre-existing scope, not Task 3. Note them in your report under DONE_WITH_CONCERNS rather than blocking.

Ruff: clean.

### Step 7 — Commit

Stage exactly the three Task 3 files:

```
git add observatory/sensory/routes.py observatory/service.py observatory/tests/unit/sensory/test_routes.py
```

Then commit:

```
git commit -m "$(cat <<'EOF'
observatory(v4): POST /sensory/text/in route + service wiring

Adds the single v4 REST endpoint. Validates body via Pydantic, trims
text, enforces text_max_length against runtime Settings, builds an
Envelope via Envelope.new(...), calls the SensoryPublisher dependency,
returns 202 with {id, timestamp}. ForbiddenTopicError -> 500;
PublishFailedError -> 502 with flat {error, message} body via
JSONResponse so the body shape stands alone in tests. Cache-Control
no-store on every response, matching v2 REST convention.

service.py constructs a SensoryPublisher in the lifespan, connects it
at startup, attaches to app.state for the route's dependency, and
disconnects on shutdown. Spec §4.4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

If a pre-commit hook fails: investigate, fix, re-stage, NEW commit. Never amend/no-verify.

### Step 8 — Report

Report `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` with the commit SHA. Pre-existing `test_mqtt_reconnect.py` failures are expected, not blocking.

## Cumulative gotchas

- **`PYTHONPATH=./src`** required for `shared.message_envelope` imports during pytest.
- **Custom exception handler in service.py** unwraps dict `detail` — but the route TEST app doesn't have it, hence the `JSONResponse` drift correction above.
- **Pydantic Field `min_length=1`** rejects empty strings *before* the validator runs. With the `_trim_and_check` validator that strips and re-rejects empty, whitespace-only inputs raise on the validator, while empty strings raise on Field. Both produce 422.
- **`PLR2004`** flags magic numbers; add `# noqa: PLR2004 — spec literal` only where ruff actually flags.
- **Imports alphabetical (I001).** `aiomqtt`, `pytest`, then fastapi, etc. Within `from X` the order matters: stdlib, third-party, local.
- **Pre-existing failures** in `test_mqtt_reconnect.py` are not your concern — log under DONE_WITH_CONCERNS.
- Use `C:/repos/hive/.venv/Scripts/python.exe`; system python lacks pytest.

## Definition of done for Task 3

- [ ] `observatory/sensory/routes.py` exists with `build_sensory_router()`, `get_publisher`, `get_settings`, `TextInRequest`, `TextInResponse`.
- [ ] Route returns `JSONResponse` for success + both error paths (drift fix).
- [ ] `observatory/sensory/routes.py` does NOT import `RegionReader` (spec §11).
- [ ] `observatory/tests/unit/sensory/test_routes.py` has 7 tests, all passing.
- [ ] `observatory/service.py` imports `SensoryPublisher`, `build_sensory_router`; lifespan creates+connects+attaches+disconnects publisher; `build_app` includes the sensory router.
- [ ] Full sensory unit suite green; route tests green; ruff clean.
- [ ] Single commit landed with the message above.
- [ ] Pre-existing `test_mqtt_reconnect.py` failures remain (not a Task 3 concern; flag in your report).

Begin.
