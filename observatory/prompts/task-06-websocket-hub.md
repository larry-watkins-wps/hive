# Implementer prompt — Observatory v1, Task 6: WebSocket hub + snapshot + live fan-out

## Context

You are a fresh implementer subagent executing **Task 6** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–5 shipped with review-fixes. Full observatory suite at **49 passed**, ruff clean. HEAD is `9fa2c63`.

Task 6 introduces `ConnectionHub` and a `/ws` WebSocket endpoint that:

- Sends a `snapshot` JSON message on connect containing current regions, retained cache, last ~500 ring records, and `server_version`.
- Fans live envelopes out to each connected client as `envelope` messages (per-client `Decimator` enforces the rate budget).
- Runs a background 2 s delta loop publishing `adjacency` and `region_delta` messages to all clients.

Runs `fastapi` + `starlette.testclient.TestClient`. `fastapi` is already installed in `.venv` after Task 5.

## Authoritative documents (read first)

- **Plan (Task 6):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 6:` (~line 1325). Complete code blocks for test (Step 1, ~75 lines) and implementation (Step 3, ~125 lines).
- **Spec:** `observatory/docs/specs/2026-04-20-observatory-design.md` — §5.3 (WebSocket message contract: `snapshot`, `envelope`, `region_delta`, `adjacency`, `decimated`).
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Existing collaborators:** `observatory/adjacency.py`, `observatory/decimator.py`, `observatory/region_registry.py`, `observatory/retained_cache.py`, `observatory/ring_buffer.py`, `observatory/types.py`. DO NOT modify these.
- **Review-fix history worth knowing:** `Decimator.drops_in_current_window()` + `total_dropped()` are the canonical accessors (old `drop_count()` kept as a deprecated alias). `Adjacency.snapshot()` returns mean msgs/sec. `_window_start` is `None` initially, anchored to first event.
- **Decisions log:** `observatory/memory/decisions.md` — 20+ entries; append new ones for non-obvious calls.

## Your scope

Execute all 5 steps of Task 6 as written in the plan:

1. Write failing test `observatory/tests/unit/test_ws.py` (2 tests: snapshot-on-connect + envelope-fan-out).
2. Run — confirm fail.
3. Implement `observatory/ws.py` with `ConnectionHub` class + `build_ws_router(hub)` helper.
4. Run — confirm pass.
5. Ruff clean; commit with plan's Step 5 HEREDOC.

## CRITICAL risk — cross-loop async in plan's test (read before writing any code)

The plan's Step 1 test has this line:

```python
asyncio.get_event_loop().run_until_complete(hub.broadcast_envelope(rec))
```

This is fragile in Python 3.12 (our target):

- `asyncio.get_event_loop()` in a sync test thread with no running loop emits `DeprecationWarning` and will raise `RuntimeError` in Python 3.14.
- `starlette.testclient.TestClient.websocket_connect` runs FastAPI in a **separate thread with its own event loop**. The `_Client.queue` (an `asyncio.Queue`) and its internal getter futures live in THAT loop. Calling `broadcast_envelope` from the main-thread loop puts onto the queue from a different loop — `asyncio.Queue` is loop-agnostic in 3.10+, but the server's serve() task has already awaited `client.queue.get()` which creates a future bound to the server loop. Resolving it from the main loop either silently hangs or raises `got Future attached to a different loop`.

**Repair strategies (pick one; log choice in `decisions.md`):**

### Option A (preferred): Use `TestClient.portal` to run the broadcast in the server loop

Starlette's `TestClient` exposes `portal_factory` / `portal` (anyio `BlockingPortal`). Use it to execute the async call in the correct loop:

```python
with client.websocket_connect("/ws") as ws:
    _ = ws.receive_json()  # snapshot
    # portal.call blocks the test thread and runs the coroutine in the server's loop
    client.portal.call(hub.broadcast_envelope, rec)
    msg = ws.receive_json()
```

If `TestClient.portal` is not a public attribute in the installed version, investigate `client.portal_factory()` as a context manager or use `anyio.from_thread.start_blocking_portal` inside `TestClient`'s thread.

### Option B: Split into pure unit tests

- `test_snapshot_message_shape_unit`: construct a hub directly (no WS, no TestClient), call `hub.snapshot_message()`, assert the dict shape. Fast and deterministic.
- `test_snapshot_on_connect_via_testclient`: keep the plan's snapshot WS test.
- `test_broadcast_envelope_enqueues_on_client_unit`: create a hub, instantiate a `_Client` directly (bypassing WS), add it to `hub._clients`, call `await hub.broadcast_envelope(rec)` inside `pytest.mark.asyncio`, assert `client.queue.get_nowait()` returns the expected envelope.

This pattern gives better isolation than the plan's mixed sync/async test and avoids the cross-loop problem entirely. Mention in the commit that this is a structural improvement over the plan's test shape, and log in `decisions.md`.

### Option C: Make `broadcast_envelope` thread-safe

Add a companion `broadcast_envelope_from_anywhere(rec)` that uses `asyncio.run_coroutine_threadsafe(..., self._loop)` where `self._loop` is captured in `start()`. More API surface; prefer A or B.

**Recommendation:** Try Option B first — it cleanly tests both the snapshot shape and the fan-out logic without TestClient/WS coupling, and leaves a simpler test for snapshot-on-connect. You can still include the WS-snapshot test to prove `build_ws_router` wires up correctly.

## Other gotchas

- **`_ring_record_to_payload`** converts `destinations: tuple[str, ...]` to `list[str]` for JSON. Tests check `== ["prefrontal_cortex"]` — ensure conversion is correct.
- **`ConnectionHub.serve()`** uses `except Exception: # noqa: BLE001` to swallow per-connection errors. Retain the noqa.
- **`Decimator` construction per client:** plan creates `Decimator(max_rate=self._max_ws_rate)` inside `serve()`. Decimator's `max_rate <= 0` guard applies — `settings.max_ws_rate` is 200 by default.
- **`_delta_task`** is an optional `asyncio.Task`. Confirm that `stop()` properly cancels without waiting (or with a short timeout) — current plan code uses bare `.cancel()` and doesn't await the cancellation.
- **Queue high-water drop:** the plan silently drops envelopes when `c.queue.qsize() > _QUEUE_HIGH_WATER`. Consider emitting a `decimated` WebSocket message per spec §5.3 so the client knows drops are happening. Optional — can be deferred to a review-fix if you want to keep Task 6 scoped tight.
- **Ruff precedents:** PLR2004 noqa on magic numbers in tests; BLE001 noqa retained on bare `except`; keep `from __future__ import annotations`.
- **`starlette.testclient.TestClient`** is imported in the plan test; this is Starlette's sync WS test client. Available via `fastapi`'s transitive dep.

## Important constraints

- **Python venv:** `source .venv/Scripts/activate` before pytest/ruff.
- **One commit** at task end. HEREDOC message as in plan Step 5, ending `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. Stage only Task 6 files (+ `decisions.md` + this prompt file for audit parity).
- **Scope:** touch only the two Task 6 files. Do NOT modify any other observatory file.
- **TDD:** red-first.

## What you must NOT do

- Do NOT implement Task 7 (service assembly). `ConnectionHub.start/stop` are public hooks for Task 7 to call; wire-up is deferred.
- Do NOT modify `Decimator`, `Adjacency`, or any other existing observatory module.
- Do NOT skip the red→green cycle.
- Do NOT commit cross-loop-broken tests just because they happen to pass locally — they will flake in CI. Choose a repair strategy.

## Verification commands

```bash
source .venv/Scripts/activate
python -m pytest observatory/tests/unit/test_ws.py -v
python -m ruff check observatory/
python -m pytest observatory/tests/unit/ -q        # expect 49 + N = 51+ passed
```

## Report back (<250 words)

- Files created
- Test counts (new / full observatory suite)
- Ruff result
- Commit SHA + subject
- **Which repair strategy (A / B / C) you used and why** — log the choice in `decisions.md`
- Other deviations + rationale
- Anything surprising for the reviewer (especially: any test flakiness, lifecycle teardown issues, or queue-overflow behavior you observed)
