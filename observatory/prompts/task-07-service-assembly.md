# Implementer prompt — Observatory v1, Task 7: Service assembly + CLI + Dockerfile

## Context

You are a fresh implementer subagent executing **Task 7** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–6 shipped with review-fixes. Full observatory suite at **57 passed**, ruff clean. HEAD is `af5872f`.

Task 7 wires every existing piece together. Responsibilities:

- `observatory/service.py::build_app(settings) -> FastAPI` — constructs ring/cache/registry/adjacency/subscriber/hub, wraps subscriber.dispatch to fan to the hub, creates a FastAPI app with `lifespan` (connect broker, subscribe `hive/#`, start hub delta loop, drain on shutdown), mounts the REST router, the WS router, and (if `observatory/web/` exists) static frontend.
- `observatory/__main__.py` — `python -m observatory` entry: reads env via `Settings.from_env`, warns on non-loopback bind, boots `uvicorn.run(app, host, port)`.
- `observatory/Dockerfile` — multi-stage: node build of `observatory/web-src/` → python runtime that installs the package and copies the built frontend into `observatory/web/`.

## Authoritative documents (read first)

- **Plan (Task 7):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 7:` (~line 1569). Complete code blocks for service.py, __main__.py, Dockerfile + a smoke test.
- **Spec:** `observatory/docs/specs/2026-04-20-observatory-design.md` — §6 (API surface), §7 (deployment).
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Top-level CLAUDE.md** at repo root — Windows gotchas (Selector event loop, testcontainers Ryuk).
- **Existing modules:** all of `observatory/*.py` — read `api.py`, `ws.py`, `mqtt_subscriber.py`, `config.py` before writing service.py so the composition is correct.

## Your scope

Execute plan Steps 1–5:

1. Create `observatory/service.py` with `build_app(settings)` factory.
2. Create `observatory/__main__.py` with `main()` and `if __name__ == "__main__": raise SystemExit(main())`.
3. Create `observatory/Dockerfile` (exact content from plan, verify paths).
4. Smoke test: `python -c "from observatory.config import Settings; from observatory.service import build_app; app = build_app(Settings()); print('ok')"` prints `ok` — this proves wiring works without a live broker.
5. Ruff clean; commit with plan's Step 5 HEREDOC.

## Critical concerns & pre-approved guidance

### 1. Monkey-patching `subscriber.dispatch`

The plan wraps the subscriber's dispatch method:
```python
original_dispatch = subscriber.dispatch
async def dispatch_and_fanout(msg):
    pre_len = len(ring)
    await original_dispatch(msg)
    post_len = len(ring)
    if post_len > pre_len:
        rec: RingRecord = ring.snapshot()[-1]
        await hub.broadcast_envelope(rec)
subscriber.dispatch = dispatch_and_fanout  # type: ignore[assignment]
```

This is ugly but plan-authoritative. Keep it. Consider adding a comment explaining that the wrapped dispatch is called by `subscriber.run()` (which uses `self.dispatch` via `await self.dispatch(message)` — confirm Python's method-lookup behavior: since `dispatch` was assigned as an instance attribute, `self.dispatch` will find the wrapper). Test the smoke path: the `build_app(Settings())` smoke test verifies the wrapper attaches without error.

### 2. `_parse_mqtt_url`

Plan version:
```python
def _parse_mqtt_url(url: str) -> tuple[str, int]:
    rest = url.split("://", 1)[1]
    host, _, port_s = rest.partition(":")
    return host, int(port_s or "1883")
```

This works for `mqtt://host:1883`. Unit-test it:
- `mqtt://localhost:1883` → `("localhost", 1883)`
- `mqtt://localhost` → `("localhost", 1883)` (default port)
- `mqtts://host:8883` → `("host", 8883)` — but the subsequent `aiomqtt.Client(hostname=host, port=port)` won't enable TLS; log a warning if scheme is `mqtts://` and note that TLS wiring is a v1.1 follow-up.

Optional: add a `observatory/tests/unit/test_service.py` with 2–3 tests covering `_parse_mqtt_url` and the `build_app` smoke path. The plan doesn't mandate it but the review will likely flag the absence.

### 3. `lifespan` hook

Plan version cancels the MQTT task on shutdown but doesn't await it, and calls `await hub.stop()` which also doesn't await the task cancellation. This produces a `CancelledError` warning on shutdown in some runtimes. Fold in a small hardening: `await asyncio.wait_for(task, timeout=2.0)` with `contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError)`. Log this as a deviation if you apply it.

### 4. Static mount order

```python
app.include_router(build_router(...))      # /api/*
app.include_router(build_ws_router(hub))   # /ws
# THEN static mount
app.mount("/", StaticFiles(directory=..., html=True), name="web")
```

Routers must be registered BEFORE the `/` mount. FastAPI resolves routes top-to-bottom; a `/` mount registered first would shadow `/api/*`. Confirm the plan's order is correct (it is).

### 5. `hive_repo_root` default is CWD

`Settings()` defaults `hive_repo_root` to `Path(".").resolve()`. For the smoke test, that's the current directory — if the smoke test is run from `C:\repos\hive`, `seed_from` will successfully load 19 regions. If run from elsewhere, the registry will be empty (not a failure; just an empty map). Consider whether the smoke test should assert one or the other — plan says just `print('ok')`, so leave as-is.

### 6. Dockerfile

Plan's Dockerfile:
```dockerfile
COPY observatory/web-src/package.json observatory/web-src/package-lock.json* ./
```
The `package-lock.json*` glob is a v1 placeholder — the frontend doesn't exist yet (Tasks 9+). Building the Docker image will fail in v1 because `observatory/web-src/` doesn't exist. That's acceptable: the Dockerfile lands in v1 as a shape-for-v2. Add a comment at the top of the Dockerfile noting it requires `web-src/` scaffolding from Task 9.

## Important constraints

- **Python venv:** `source .venv/Scripts/activate` before pytest/ruff/smoke. `aiomqtt` and `uvicorn` should already be installed (pyproject.toml test extras include them; if not, `pip install aiomqtt uvicorn[standard]`).
- **One commit** at task end, scoped to the Task 7 files. HEREDOC message from plan Step 5, ending `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. Optionally include `observatory/tests/unit/test_service.py` if you add it.
- **Scope:** touch only `observatory/service.py`, `observatory/__main__.py`, `observatory/Dockerfile`, and optionally `observatory/tests/unit/test_service.py`, `observatory/memory/decisions.md`, `observatory/prompts/task-07-service-assembly.md`. Do NOT modify any prior observatory module.
- **Ruff clean:** apply the usual mechanical noqa precedents (PLR2004, BLE001 for broad excepts in lifespan, PLC0415 inline imports in tests).
- **TDD-ish:** the smoke test IS the test for this task. If you add the optional unit tests for `_parse_mqtt_url`, write them before the implementation.

## What you must NOT do

- Do NOT implement Task 8 (component test with real broker).
- Do NOT create `observatory/web-src/` or frontend files — those are Tasks 9+.
- Do NOT modify existing observatory modules (api.py, ws.py, mqtt_subscriber.py, etc.) — if you find a real bug, log in decisions.md and flag for a follow-up.
- Do NOT start an actual MQTT connection during the smoke test — `build_app(Settings())` only constructs the app; `lifespan` is not invoked until an ASGI client starts.

## Verification commands

```bash
source .venv/Scripts/activate
# Smoke test (plan Step 4)
python -c "from observatory.config import Settings; from observatory.service import build_app; app = build_app(Settings()); print('ok')"
# If you added a test file:
python -m pytest observatory/tests/unit/test_service.py -v
# Full suite
python -m pytest observatory/tests/unit/ -q       # expect 57 + any new = 57+ passed
python -m ruff check observatory/                 # clean
```

## Report back (<250 words)

- Files created
- Smoke test result
- Unit test counts (if you added test_service.py)
- Ruff result
- Commit SHA + subject
- Any deviations + rationale (log in decisions.md if material)
- Anything surprising (especially: lifecycle warnings, missing deps, wiring issues you had to route around)
