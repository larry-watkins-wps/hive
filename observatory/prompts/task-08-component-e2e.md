# Implementer prompt — Observatory v1, Task 8: End-to-end component test

## Context

You are a fresh implementer subagent executing **Task 8** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–7 shipped with review-fixes. Full observatory **unit** suite at **67 passed**, ruff clean. HEAD is `aeeb1d6`.

Task 8 adds a single **component-marked** test that:
- Boots a real `eclipse-mosquitto:2` broker via `testcontainers`.
- Constructs the observatory FastAPI app with that broker's host/port.
- Starts the app's lifespan via `TestClient`.
- Connects a WebSocket client.
- Publishes one envelope via a separate `aiomqtt.Client`.
- Asserts the envelope propagates through the observatory's subscriber → ring → hub → WS.

This is a prerequisite for Task 9+ (frontend): once this passes, we know the whole v1 backend path works end-to-end against real MQTT.

## Authoritative documents (read first)

- **Plan (Task 8):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 8:` (~line 1752). Complete code blocks for `conftest.py`, `test_end_to_end.py`, and pytest marker registration.
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Top-level guide:** `CLAUDE.md` at repo root — Windows gotchas for aiomqtt + testcontainers are mandatory reading.
- **Existing component-test precedent:** `tests/component/conftest.py` at repo root mirrors the pattern (Ryuk-disabled + `WindowsSelectorEventLoopPolicy`).
- **Build target:** `observatory/service.py::build_app(settings)` — verified by Task 7's smoke test.

## Your scope

Execute plan Steps 1–5:

1. Create `observatory/tests/component/__init__.py` (empty).
2. Create `observatory/tests/component/conftest.py` (forces selector event loop on Windows + disables Ryuk).
3. Write `observatory/tests/component/test_end_to_end.py`.
4. Verify the workspace `pyproject.toml` already has a `component` pytest marker registered (per top-level CLAUDE.md, all `[tool.pytest.ini_options]` lives at workspace root). Expected YES — don't modify if already present.
5. Run: `python -m pytest observatory/tests/component/ -m component -v` (requires Docker Desktop running).
6. Commit with plan Step 5 HEREDOC.

## Critical concerns & pre-approved guidance

### 1. MQTT subscribe/publish race

The plan's test has a race: the observatory's `aiomqtt` subscriber starts via `lifespan`'s `asyncio.create_task(_run())`, which connects + subscribes asynchronously. The test then publishes from a separate client. If the publish arrives BEFORE the observatory's subscribe completes, the broker won't deliver it (normal MQTT semantics; unretained messages only reach subscribed clients).

**Pre-approved fix:** publish with `retain=True`. Retained messages are delivered to any client that subscribes to the matching topic, immediately on subscription — eliminates the race entirely.

```python
await pub.publish(
    "hive/cognitive/prefrontal/plan",
    payload=json.dumps(envelope).encode(),
    retain=True,
)
```

The observatory treats retained envelopes the same as non-retained for the ring + WS fan-out (retained-prefix-list in `mqtt_subscriber.py` is only for the cache). So this doesn't change what the test asserts — only makes delivery deterministic.

Alternative if `retain=True` behaves unexpectedly: add a small `asyncio.sleep(0.5)` after `ws.receive_json()` (the snapshot) to give the subscriber time to subscribe. Less clean but more flexible. Prefer retain.

Log the choice in `observatory/memory/decisions.md`.

### 2. `async with client:` lifespan

`starlette.testclient.TestClient` supports BOTH sync `with` and async `async with` — the async variant runs lifespan startup/shutdown via the internal blocking portal. The plan's test uses `async with client:` inside `async def test_...(tmp_path)` — that's correct. Don't second-guess it.

### 3. `hive_repo_root=tmp_path`

The test uses an empty `tmp_path` as `hive_repo_root`. Result: `RegionRegistry.seed_from(tmp_path)` returns empty, `load_subscription_map(tmp_path)` returns empty. The envelope's `source_region="thalamus"` won't match any subscription, so `destinations` will be `()`. The test asserts `source_region == "thalamus"` but doesn't assert destinations — good.

### 4. `testcontainers.mqtt.MosquittoContainer`

Requires:
- `testcontainers[mqtt]` in pyproject.toml (already listed in `observatory/pyproject.toml` test extras).
- Docker Desktop running on the host.

Do NOT attempt to install Docker if it's missing — surface the error and report. The user will enable Docker and re-run.

`MosquittoContainer(image="eclipse-mosquitto:2")` context manager:
- `broker.get_container_host_ip()` returns the host IP (usually `"127.0.0.1"` or `"localhost"`).
- `broker.get_exposed_port(1883)` returns the mapped host port (testcontainers maps the container's 1883 to a random free host port).

### 5. `_free_port()` is cosmetic

The plan's `_free_port()` is only used for `settings.bind_port`, but `TestClient` doesn't actually bind a host port — it uses the ASGI app directly. Keep the helper to match the plan exactly; it's not load-bearing.

### 6. Ruff compliance

Expected ruff hits in a component test:
- `PLR2004` on magic numbers in polling loop (e.g. `range(50)`, `timeout=0.2`). Add `# noqa: PLR2004` as needed.
- `ASYNC110` (if your ruff includes the async group) warning on `asyncio.sleep` in a loop — not in this project's config, so skip.
- `PLC0415` on inline imports inside functions — tests sometimes do this.

## Important constraints

- **Python venv:** `source .venv/Scripts/activate` before pytest.
- **`testcontainers[mqtt]` installed:** verify with `python -c "from testcontainers.mqtt import MosquittoContainer; print('ok')"`. If not installed, run `pip install "testcontainers[mqtt]"` or `pip install -e ".[test]"` — note the install in your report.
- **Docker Desktop:** must be running for the test to pass. If it isn't, the test will fail at container startup. Report the state.
- **One commit** at task end, scoped to Task 8 files (plus `decisions.md` for the retain=True decision, plus the prompt file for audit parity). HEREDOC commit message from plan Step 5, ending `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`.
- **Scope:** touch only the three Task 8 files + optional prompt/decisions. Do NOT modify any existing observatory module. Do NOT touch `region_template/`, `glia/`, `regions/`, `bus/`, `shared/`, `tools/`, top-level `tests/`, or `observatory/pyproject.toml`.
- **Unit suite must still pass** alongside the new component test: `python -m pytest observatory/tests/unit/ -q` still 67 passed.

## What you must NOT do

- Do NOT implement Tasks 9+ (frontend).
- Do NOT modify `observatory/service.py` or any other observatory module to work around test-side issues.
- Do NOT skip the `async with client:` lifespan wrapping — the test MUST exercise the real lifespan (that's the whole point of the component test).
- Do NOT commit if Docker is unavailable / test didn't actually run — report the state honestly and let the user decide.
- Do NOT use `git add -A`; stage explicit paths.

## Verification commands

```bash
source .venv/Scripts/activate
python -c "from testcontainers.mqtt import MosquittoContainer; print('ok')"  # confirm installed
python -m pytest observatory/tests/component/ -m component -v                # the actual test
python -m pytest observatory/tests/unit/ -q                                   # unit suite unchanged (67)
python -m ruff check observatory/                                             # clean
```

## Report back (<250 words)

- Files created
- `testcontainers[mqtt]` install state (already-installed vs had-to-install)
- Docker state (running vs not)
- Component test result (passed / failed / skipped) — include error details if it failed
- Unit suite count
- Ruff result
- Commit SHA + subject — **only if the component test actually passed** with Docker. If it failed or Docker was unavailable, DO NOT commit; surface the state in the report and let the user decide.
- Any deviations (should include the `retain=True` decision)
- Timing observations (how long did `MosquittoContainer` startup take? how many polls before the envelope arrived?)
