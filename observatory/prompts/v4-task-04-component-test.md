# v4 Task 4 — Component test: POST → real broker round-trip

You are implementing Task 4 of the observatory v4 plan. Read this prompt in full before touching any file.

## Your role

Implement Task 4 only. Single test addition + commit, then stop.

## Working directory

`C:/repos/hive`. Use `C:/repos/hive/.venv/Scripts/python.exe` for python invocations. Set `PYTHONPATH=./src` for pytest invocations that touch `shared.message_envelope`.

Forward slashes; Unix shell. No `cd`.

## Predecessor state

Tasks 1–3 are committed:
- Task 1 (`370db6f`): sensory module skeleton + Settings.chat_*.
- Task 2 (`473dd30`): SensoryPublisher with connect/disconnect/publish.
- Task 3 (`cef8728`): POST /sensory/text/in route + service.py wiring.

Production POST `/sensory/text/in` is fully wired. SensoryPublisher connects to MQTT in the lifespan, the route uses dependency injection from `app.state.sensory_publisher` and `app.state.settings`.

## Spec excerpt (authoritative)

### §9.2 Backend component

- Real broker via `eclipse-mosquitto:2` testcontainer.
- POST hits the route → broker confirms a publish on `hive/external/perception` with the expected envelope.
- Round-trip latency assertion `< 500 ms`.
- (Forbidden-topic injection test is mentioned in spec §9.2 but is **out of scope for Task 4** — covered by the unit tests in Task 3 which already exercise that path with a stub publisher.)

## Existing test file

`observatory/tests/component/test_end_to_end.py` already exists with:
- `pytestmark = pytest.mark.component`
- Top-of-file imports: `dataclasses`, `json`, `socket`, `Iterator`, `Path`, `aiomqtt`, `pytest`, `TestClient` (from starlette), `MosquittoContainer`, `Settings`, `build_app`.
- A custom `_MOSQUITTO_CONF` constant.
- Helper `_free_port()` and `_seed_regions(root)`.
- **Module-scoped fixture `broker_url(tmp_path_factory)`** — yields `mqtt://host:port`. Reuses one container across all tests in the file.
- Three existing tests: `test_publish_reaches_websocket`, `test_v2_endpoints_over_real_service`, `test_v3_appendix_endpoint_over_real_service`. Read the file to confirm the fixture name and shape before writing your test.

Read it now before editing:

```
C:/repos/hive/observatory/tests/component/test_end_to_end.py
```

Confirm:
- The `broker_url` fixture name is `broker_url` (no rename needed).
- `aiomqtt`, `json`, `dataclasses` are imported at module top.
- `Settings`, `build_app`, `TestClient` are imported at module top.
- You will need to add `queue`, `threading`, `time` imports.

## Drift correction (v4 specific)

The plan's verbatim test imports `queue`, `threading`, `time`, `asyncio` *inside* the test function body. **Hoist these to module-level imports** at the top of the file (alphabetical order, in the stdlib block) — that's the file's existing style and ruff's preference (PLC0415, E402 hygiene).

Also: the plan's verbatim test has the `_capture_loop` thread block on `async for msg in c.messages:` and then `return` after one message. That's correct, but the inner `async def _go()` doesn't have a return type — ruff will not flag it (no ANN201 in workspace config), but match the file's existing style (the existing tests are mostly typed).

### Subtle correctness concern: ordering of capture vs. POST

The plan starts the capture subscriber thread, awaits its `ready` event, then the POST inside `with TestClient(app) as client:`. This works because:
1. `with TestClient(app)` triggers FastAPI startup → `SensoryPublisher.connect()` opens the publisher's aiomqtt connection.
2. Publisher publishes with `qos=1`.
3. Broker has the capture subscriber already subscribed to `hive/external/perception` with `qos=1` (after `ready.set()`).
4. Broker fans out to subscriber → captured.put(...).

This relies on the capture subscriber being subscribed *before* the publish lands. The `ready.set()` only fires after `await c.subscribe(...)` returns, which means the broker has acknowledged the subscription. So no race.

Cleanup: the daemon thread auto-dies on process exit, but `asyncio.run` inside the thread has its own loop. After capture, the inner `_go` returns, `asyncio.run` cleans the loop, and the thread joins. Acceptable.

## Step-by-step

### Step 1 — Read the test file

Use the Read tool to inspect `observatory/tests/component/test_end_to_end.py`. Note:
- Existing imports.
- The `broker_url` fixture (name and signature).
- How existing tests invoke `dataclasses.replace(Settings(), ...)`.

### Step 2 — Add new top-level imports

Insert into the existing top-of-file imports block:

```python
import asyncio  # likely already present — check
import queue
import threading
import time
```

(`asyncio` may already be there; if so, leave it. Add only the missing three.)

### Step 3 — Append the test

After the last existing test (`test_v3_appendix_endpoint_over_real_service`), append:

```python
def test_post_sensory_text_in_publishes_to_broker(
    broker_url: str, tmp_path: Path,
) -> None:
    """Spec §9.2: POST → real broker confirms publish on
    hive/external/perception with the spec §3.2 envelope shape; round-trip < 500 ms.

    Capture subscriber runs in a side-channel thread (its own asyncio loop)
    so the FastAPI app's lifespan-owned aiomqtt client and the test's
    listener don't share a single event loop. The test starts the
    listener, awaits a `ready` event (which only fires after `subscribe`
    is acknowledged by the broker), then drives the POST via TestClient.
    """
    regions_root = tmp_path / "regions"
    regions_root.mkdir()
    settings = dataclasses.replace(
        Settings(),
        mqtt_url=broker_url,
        regions_root=regions_root,
    )
    app = build_app(settings)

    captured: queue.Queue[dict] = queue.Queue()
    ready = threading.Event()
    host, _, port_s = broker_url.split("://", 1)[1].partition(":")
    port = int(port_s)

    def _capture_loop() -> None:
        async def _go() -> None:
            async with aiomqtt.Client(host, port) as c:
                await c.subscribe("hive/external/perception", qos=1)
                ready.set()
                async for msg in c.messages:
                    captured.put(json.loads(msg.payload.decode()))
                    return
        asyncio.run(_go())

    cap_thread = threading.Thread(target=_capture_loop, daemon=True)
    cap_thread.start()
    assert ready.wait(timeout=5.0), (  # noqa: PLR2004 — generous startup budget
        "capture subscriber never reported ready"
    )

    with TestClient(app) as client:
        t0 = time.monotonic()
        resp = client.post("/sensory/text/in", json={"text": "hi from test"})
        assert resp.status_code == 202  # noqa: PLR2004
        body = resp.json()
        assert "id" in body and "timestamp" in body

    env = captured.get(timeout=2.0)  # noqa: PLR2004 — drain budget
    elapsed = time.monotonic() - t0
    assert elapsed < 0.5, f"round-trip too slow: {elapsed:.2f}s"  # noqa: PLR2004 — spec literal

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

### Step 4 — Run only the new test (single-test sanity check)

```
PYTHONPATH=./src C:/repos/hive/.venv/Scripts/python.exe -m pytest "observatory/tests/component/test_end_to_end.py::test_post_sensory_text_in_publishes_to_broker" -m component -v
```

Expected: PASS in under a few seconds plus mosquitto startup. If the `< 500 ms` round-trip assertion fails on a cold container, that's flaky-on-cold-start but the broker is module-scoped — re-run, the second hit should be quick. If consistently >500 ms, document in your DONE_WITH_CONCERNS report and propose either upping the budget to 1s or noting that the broker startup is the dominant cost.

### Step 5 — Run the full component suite

```
PYTHONPATH=./src C:/repos/hive/.venv/Scripts/python.exe -m pytest observatory/tests/component/ -m component -v
```

Expected: **4 passed** (3 existing v1/v2/v3 + 1 new v4). The order matters — running standalone vs. as part of the module changes whether the broker is fresh or shared. The module-scoped fixture means within one pytest invocation, mosquitto starts once and tests share it. Note from the existing fixture docstring: the v1 test publishes a retained message to `hive/cognitive/prefrontal/plan` that persists into later tests in the module. Your new test only subscribes to `hive/external/perception`, so the bleed is harmless.

If Docker Desktop is not running, the test will skip / error at fixture setup; document and fall back to running just the unit suite.

### Step 6 — Lint

```
C:/repos/hive/.venv/Scripts/python.exe -m ruff check observatory/tests/component/test_end_to_end.py
```

Expected: clean.

### Step 7 — Commit

```
git add observatory/tests/component/test_end_to_end.py
git commit -m "$(cat <<'EOF'
observatory(v4): component test — POST → real broker round-trip

Verifies POST /sensory/text/in publishes a fully-formed Hive Envelope
on hive/external/perception with the §3.2 shape. Capture subscriber
runs in a side-channel thread (own asyncio loop) so the FastAPI app's
lifespan-owned aiomqtt client and the test listener don't share an
event loop. Round-trip latency assertion < 500 ms. Spec §9.2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

If a pre-commit hook fails: investigate, fix, re-stage, NEW commit. Never amend/no-verify.

### Step 8 — Report

Report `DONE` / `DONE_WITH_CONCERNS` / `BLOCKED` with the commit SHA and a one-line note on whether Docker Desktop was available + whether the round-trip stayed under 500 ms.

If Docker Desktop is unavailable, treat as `DONE_WITH_CONCERNS`: commit the test (still ruff-clean and the unit suite still passes), but note that the new component test couldn't be exercised in this environment — Larry's workstation will run it.

## Cumulative gotchas

- **`PYTHONPATH=./src`** for pytest.
- **conftest sets `WindowsSelectorEventLoopPolicy`** for the component package — fine for the test app's lifespan. The `_capture_loop` thread spawns its own asyncio.run which inherits the default loop policy. On Windows that means the capture thread also uses the selector loop, which is what aiomqtt needs. Good.
- **Docker Desktop required** for testcontainers `eclipse-mosquitto:2`. If not running, the test errors at fixture setup. Document if you can't run.
- **Pre-existing failures** in unit tests (`test_mqtt_reconnect.py`) — out of scope.
- Use `C:/repos/hive/.venv/Scripts/python.exe`.

## Definition of done for Task 4

- [ ] `observatory/tests/component/test_end_to_end.py` has 1 new test (`test_post_sensory_text_in_publishes_to_broker`).
- [ ] Module-level imports updated (`queue`, `threading`, `time`; `asyncio` if not already present).
- [ ] Single test passes against a real testcontainers broker (or, if Docker unavailable: ruff clean, single commit landed, flagged in DONE_WITH_CONCERNS).
- [ ] Full component suite is 4 passed (or 3 passed + 1 errored-on-fixture-setup if Docker is unavailable).
- [ ] Ruff clean on the file.
- [ ] Single commit with the message above.

Begin.
