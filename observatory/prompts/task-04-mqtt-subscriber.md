# Implementer prompt — Observatory v1, Task 4: MQTT subscriber + dispatch

## Context

You are a fresh implementer subagent executing **Task 4** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–3 shipped with review-fixes. Full observatory suite at **31 passed**, ruff clean. Current HEAD is the HANDOFF bump after Task 3's review-fix.

Task 4 wires `aiomqtt` to the existing ring buffer, retained cache, region registry, and adjacency matrix. It adds one module + one test file.

Key responsibilities of `MqttSubscriber`:
- Subscribe to `hive/#` (caller provides the client — subscriber just consumes `client.messages`).
- Parse each incoming envelope as JSON. Skip non-JSON payloads (raw hardware bytes, etc.).
- For each envelope: infer destinations from a pre-loaded `regions/<name>/subscriptions.yaml` map, update the retained cache for certain topic prefixes, update the region registry on heartbeats, and append a `RingRecord` to the ring buffer. Record a `(source, destinations)` adjacency event when both are known.

## Authoritative documents (read first)

- **Plan (Task 4):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 4:` (~line 888). Has complete code for Step 1 (tests, ~150 lines) and Step 3 (implementation, ~140 lines) and Step 5 (commit).
- **Spec:** `observatory/docs/specs/2026-04-20-observatory-design.md` — §5.1 ring buffer shape, §5.2 retained cache, §E envelope format.
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Decisions log:** `observatory/memory/decisions.md` (14 entries) — read the Task 2 / Task 3 reality-vs-plan entries to understand the pattern before you hit the same thing here.
- **Real envelope schema:** `shared/message_envelope.py` — `Envelope` dataclass, see especially the `Payload { content_type, data, encoding }` wrapper. Plan's test envelopes use a naked `payload: dict`; real envelopes nest under `payload.data`. See the heartbeat note below.
- **Real region registry:** `glia/regions_registry.yaml` — already used by `region_registry.py`; you won't touch it but be aware of the live contract.
- **Existing observatory modules you'll compose:** `observatory/ring_buffer.py`, `observatory/retained_cache.py`, `observatory/region_registry.py`, `observatory/adjacency.py`, `observatory/types.py`.

## Your scope

Execute all 5 steps of Task 4 as written in the plan:

1. Write failing test `observatory/tests/unit/test_mqtt_subscriber.py` (6 tests, 5 async + 1 sync for `load_subscription_map`).
2. Run — confirm fail.
3. Implement `observatory/mqtt_subscriber.py` with two public APIs:
   - `load_subscription_map(hive_repo_root) -> dict[str, list[str]]`
   - `class MqttSubscriber` with `__init__`, `dispatch(msg)`, `run(client, stop_event)`.
4. Run — confirm pass.
5. Ruff clean; commit with plan's Step 5 HEREDOC.

## Pre-approved reality-vs-plan reconciliation (apply during Task 4, not in a follow-up)

The plan's test fixtures emit a fictional envelope where `payload` is a naked dict (see `_envelope` helper in Step 1). Production envelopes (`shared/message_envelope.py` line 46) wrap payload in `{content_type, data, encoding}` — a heartbeat's actual stats live under `envelope["payload"]["data"]`.

**Required adjustment:** in the heartbeat branch of `dispatch()`, accept BOTH shapes — if `payload` is a dict containing a nested `"data"` dict, use that; otherwise use `payload` directly. This keeps the plan's tests passing while also working against production envelopes. Log this reconciliation in `observatory/memory/decisions.md` with the same "spec/reality wins over plan prose" rationale used by Task 2's review-fix entry.

Suggested heartbeat branch shape:
```python
if topic.startswith(_HEARTBEAT_PREFIX):
    region_name = topic[len(_HEARTBEAT_PREFIX):]
    payload = envelope.get("payload", {})
    # Real envelopes wrap heartbeat stats under payload.data per
    # shared/message_envelope.py; the plan's test fixtures pass them
    # flat. Accept both shapes.
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        payload = payload["data"]
    if isinstance(payload, dict):
        self.registry.apply_heartbeat(region_name, payload)
```

Do NOT rewrite the plan's test fixtures to the real shape — they test the flat shape deliberately so we catch both paths. You MAY add one extra test that uses the wrapped shape to pin the real-envelope path. Optional but valued.

## Important constraints

- **Python venv:** `source .venv/Scripts/activate` before `python -m pytest` / `python -m ruff`.
- **One commit** at task end with HEREDOC message from plan Step 5, ending `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. Stage only `observatory/mqtt_subscriber.py`, `observatory/tests/unit/test_mqtt_subscriber.py`, and (if touched) `observatory/memory/decisions.md`.
- **Scope boundary:** touch only the two Task 4 files (+ decisions.md for the logged reconciliation). Do NOT modify any other observatory file, and do NOT touch `region_template/`, `glia/`, `regions/`, `bus/`, `shared/`, `tools/`, top-level `tests/`, or `observatory/pyproject.toml`.
- **Ruff/lint:** workspace root owns config. Prior precedent applies (UP037, UP035, PLR2004 noqa on magic numbers, B007 `_` for unused loop vars). Expect NEW potential flags: `BLE001` on the bare `except Exception:` in `run()` — the plan already pre-applies `# noqa: BLE001` there, which is correct and justified (don't kill subscriber on one bad message).
- **TDD:** red-first. Confirm `ModuleNotFoundError` before writing the impl.
- **Do not create the aiomqtt client** — `run()` accepts an already-connected, already-subscribed client. Construction is deferred to Task 7 (service wiring). This keeps unit tests fast (no broker).

## Known gotchas to be aware of

- **aiomqtt Message.topic** is a `Topic` object with a `.value` string property in v2; some tests might mock it as a plain string. The plan's `dispatch()` has `msg.topic.value if hasattr(msg.topic, "value") else str(msg.topic)` — keep that dual-path.
- **`async for message in client.messages`** is the aiomqtt v2 iterator API. Plan uses it correctly.
- **`time.monotonic()`** is the clock the Adjacency and Decimator expect (the Task 3 review-fix anchored to this). Do not use `time.time()`.
- **`structlog` is a project-wide dependency**; use `structlog.get_logger(__name__)` at module level.
- **`ruamel.yaml`** is already pinned in `observatory/pyproject.toml`; the `_YAML = YAML(typ="safe")` pattern matches what `region_registry.py` does.
- **Windows selector event loop:** aiomqtt needs `add_reader`/`add_writer` which Windows selector loop provides. Component tests will hit this in Task 8 — unit tests here don't.

## What you must NOT do

- Do NOT implement Task 5 (REST API).
- Do NOT modify existing observatory modules.
- Do NOT add a real aiomqtt connection to unit tests.
- Do NOT use `git add -A`; stage explicit paths.
- Do NOT skip the red→green TDD cycle.
- Do NOT lose the pre-approved heartbeat-payload reconciliation (above). It's a substantive correctness fix, not an optional nicety.

## Verification commands

```bash
source .venv/Scripts/activate
python -m pytest observatory/tests/unit/test_mqtt_subscriber.py -v
python -m ruff check observatory/
python -m pytest observatory/tests/unit/ -q       # expect 31 + 6 (or 7 if you add the wrapped-shape test) = 37+ passed
```

## Report back (<200 words)

- Files created
- Test counts (new / full observatory suite)
- Ruff result
- Commit SHA + subject
- Deviations applied + rationale (should include the pre-approved heartbeat unwrap)
- Anything surprising for the reviewer
