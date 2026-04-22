# Hive v0 — Design Specification

**Status:** Draft for review
**Author:** Phase 2 session, 2026-04-19
**Audience:** Implementers of Hive v0 and future maintainers
**Supersedes:** Nothing (first spec)
**Informs:** `docs/superpowers/plans/2026-04-19-hive-v0-plan.md` (to be written)

> This specification translates the approved design in
> `docs/principles.md`, `docs/architecture.md`, and `docs/starter_prompts/`
> into concrete APIs, schemas, and behaviors sufficient for implementation.
> Where this spec surfaces gaps or contradictions in the upstream design,
> they are captured in **Section L: Open Questions** rather than resolved
> silently.

---

## Table of contents

- [Section 0 — Preamble](#section-0--preamble)
- [Section A — Core runtime (`region_template/`)](#section-a--core-runtime-region_template)
- [Section B — MQTT layer (`bus/`)](#section-b--mqtt-layer-bus)
- [Section C — LLM adapter (LiteLLM integration)](#section-c--llm-adapter-litellm-integration)
- [Section D — Memory system](#section-d--memory-system)
- [Section E — Glia (infrastructure)](#section-e--glia-infrastructure)
- [Section F — Configuration](#section-f--configuration)
- [Section G — Bootstrap](#section-g--bootstrap)
- [Section H — Observability](#section-h--observability)
- [Section I — Testing strategy](#section-i--testing-strategy)
- [Section J — Safety & recovery](#section-j--safety--recovery)
- [Section K — Developer ergonomics](#section-k--developer-ergonomics)
- [Section L — Open questions](#section-l--open-questions)
- [Appendix 1 — Full file layout](#appendix-1--full-file-layout)
- [Appendix 2 — Principles traceability matrix](#appendix-2--principles-traceability-matrix)

---

## Section 0 — Preamble

### 0.1 Purpose

Implementation-ready specification for **Hive v0**. Concrete enough that a Phase-4 implementer can write the code without needing to reinvent design decisions.

**This spec does not redesign Hive.** When the spec surfaces gaps or contradictions, they land in **Section L: Open Questions**, not in silent overrides.

### 0.2 Scope

In scope:

- Shared runtime code under `region_template/`
- MQTT layer (`bus/`): broker config, ACLs, envelope schema
- Glial infrastructure (`glia/`): supervision, ACL mediation, rollback
- Per-region configuration, bootstrap, developer workflow
- Testing, observability, safety & recovery
- Docker-based deployment (see 0.5)

Out of scope:

- Internal prompts/handlers of any specific region (region-owned, evolves at runtime)
- Production security hardening (v0 is local-host; TLS, auth federation, secrets rotation deferred)
- Multi-host deployment, cloud packaging, observability backends
- Web UI / dashboard (CLI only at v0)
- Model fine-tuning, embedding storage (LTM is text at v0)

### 0.3 Non-goals

- **Determinism.** Principle XIV rejects it. No byte-identical output tests.
- **Orchestration.** Principle XIII. Nothing in `region_template/` or `glia/` commands a region to act.
- **A master region.** No region has privileged runtime control over others. ACC has narrow proposal-to-authorization authority for spawns and code changes; that is not general control.
- **Optimization.** v0 optimizes for clarity and biological fidelity, not throughput.

### 0.4 Target environment

| Dimension | Choice | Rationale |
|---|---|---|
| Python | **3.11** | Mature `asyncio`, pattern matching, TOML stdlib, wide install base. |
| MQTT broker | **mosquitto 2.0.x** default; swappable | Full ACL support; spec stays broker-agnostic where possible. |
| MQTT client | **`aiomqtt` 2.x** (wraps paho-mqtt) | Native asyncio, context manager, tracks paho upstream. |
| Containerization | **Docker** + **Docker Compose v2** | Single-host v0, per-region isolation, trivial restart. |
| Container base | **python:3.11-slim-bookworm**, pinned by digest | Small, predictable. |
| Git | **2.40+** | Per-region repositories via plain `git` CLI. |
| LLM abstraction | **LiteLLM 1.x** | Principle XI. |
| Envelope schema | **JSON Schema Draft 2020-12** | Language-agnostic. Validated with `jsonschema` 4.x. |
| Config format | **YAML 1.2** via **`ruamel.yaml`** | Preserves comments during region self-edits. |
| Logging | **`structlog` 24.x** → stdout JSON lines | Docker collects stdout natively. |
| Process manager | **Docker daemon** via `docker` SDK 7.x (from glia) | See Section E. |

Pinned versions live in `region_template/pyproject.toml` and `docker-compose.yaml`.

### 0.5 Deployment model: Docker-first

**Every Hive component runs as a container.** v0 architectural commitment.

```
┌─────────────────────────────────────────────────────────────────┐
│                  Docker host (dev laptop / server)              │
│                                                                 │
│   ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│   │ mosquitto   │  │ glia         │  │ region containers      │ │
│   │ container   │◄─┤ supervisor   │─►│ (one per region,       │ │
│   │  :1883      │  │ (docker.sock │  │  14 at v0)             │ │
│   └─────────────┘  │  mounted)    │  │                        │ │
│                    └──────────────┘  │ all use shared image   │ │
│                                      │ hive-region:v0,        │ │
│                                      │ selected by env var.   │ │
│                                      └────────────────────────┘ │
│                                                                 │
│   Bridge network `hive_net`. Only broker reachable by default.  │
└─────────────────────────────────────────────────────────────────┘
```

**Key Docker decisions:**

| Decision | Choice | Why |
|---|---|---|
| Images | **One shared image** `hive-region:v0`; region identity via `HIVE_REGION=<name>` env var | Principle VII maps to "one image, many containers." |
| Region state | Bind-mount `./regions/<name>/:/hive/region/:rw` | Per-region git persists on host; dev can inspect. |
| Shared DNA | Bind-mount `./region_template/:/hive/region_template/:ro` and `./shared/:/hive/shared/:ro` | Kernel-enforced Principle VI boundary. |
| Sandbox | Self-modify tools take paths relative to `/hive/region/` and refuse escapes | Stronger than Python sandbox. |
| Network | Single `hive_net` bridge; broker at `mqtt://broker:1883` | MQTT ACLs enforce topic isolation, not network. |
| Glia | Privileged container with `/var/run/docker.sock` mounted; Docker SDK for start/stop/restart | Documented in Sections E and J. |
| Restart | `docker restart <container>` with exponential backoff | Atomic, fast, log-preserving. |
| Compose | `docker-compose.yaml` at repo root: broker + glia only | Regions launched by glia at runtime for neurogenesis. |
| Dev mode | `hive up --dev` launches broker + one region, skips ACL, enables hot-reload | Section K. |

**Non-Docker fallback:** `hive up --no-docker` runs regions as local Python processes. Debugging only. Section G.5.

### 0.6 Conventions used in this spec

- Python signatures use PEP 484 type hints with `from __future__ import annotations`. Async methods marked `async def`.
- JSON Schemas are Draft 2020-12, inlined in backticks.
- YAML examples are YAML 1.2, 2-space indent.
- MQTT topic names follow `docs/architecture.md` § 4 exactly. Wildcards: `+` (single level), `#` (multi-level).
- **MUST / SHOULD / MAY** per RFC 2119, capitalized when normative.
- Principle references inline as `(P-II)` = Principle II. Every non-obvious choice justified against a principle.
- **Biology anchor** blocks describe the biology when a choice is contested.
- **Failure modes** tabulated per component for coverage review.

### 0.7 Glossary

| Term | Meaning |
|---|---|
| **Region** | Cognitive container with LLM, prompt, memory, handlers. One Docker container. |
| **Glia** | Infrastructure. No LLM, no deliberation. Lifecycle, ACL mediation, rollback. |
| **Runtime / DNA** | Code in `region_template/`. Shared across all regions. |
| **Gene expression** | Per-region artifacts: `prompt.md`, `subscriptions.yaml`, `handlers/`, `memory/`. |
| **STM** | Short-term memory, `memory/stm.json`. |
| **LTM** | Long-term memory, `memory/ltm/*.md`. |
| **Envelope** | JSON wrapper on every MQTT payload. |
| **Modulator** | Retained topic under `hive/modulator/*`; ambient chemical field. |
| **Rhythm** | Broadcast topic under `hive/rhythm/*`; oscillatory timing. |
| **Heartbeat** | Liveness publish to `hive/system/heartbeat/<region>`. |
| **Sleep cycle** | Lifecycle phase where a region may consolidate and self-modify. |
| **Capability profile** | Declared permissions in `config.yaml`. Framework-enforced. |

### 0.8 Principles honored in Section 0

- **P-VI** (DNA / gene expression) enforced at Docker volume layer — physical boundary.
- **P-VII** (one template, many regions) via one shared image.
- **P-XI** (LLM-agnostic) via LiteLLM commitment.
- **P-XVI** (signal types) by pinning envelope as JSON Schema.

---

## Section A — Core runtime (`region_template/`)

### A.1 Overview

`region_template/` is **the DNA** (P-VI). It is the only Python code shared across all regions. A region's Docker container entry point is:

```bash
python -m region_template.runtime --config /hive/region/config.yaml
```

All 14 v0 regions run the same runtime code. Differentiation comes entirely from `config.yaml`, `prompt.md`, `subscriptions.yaml`, `handlers/`, and `memory/` in the region's own directory (P-VII).

### A.2 Module layout

```
region_template/
├── __init__.py
├── runtime.py              # RegionRuntime: event loop, lifecycle
├── mqtt_client.py          # Async MQTT client with envelope wrap/unwrap
├── llm_adapter.py          # LiteLLM wrapper, capability gating
├── memory.py               # STM/LTM interface, consolidation hooks
├── self_modify.py          # Sleep-only tools: append_appendix, edit_handlers, …
├── appendix.py             # AppendixStore — single writer of rolling.md appendix
├── prompt_assembly.py      # load_system_prompt — joins starter prompt + appendix
├── sleep.py                # Sleep state machine, consolidation driver
├── capability.py           # Capability enforcement decorator + registry
├── config_loader.py        # config.yaml loader + schema validation
├── handlers_loader.py      # Dynamic handler discovery and sandboxed import
├── git_tools.py            # Per-region git operations
├── logging_setup.py        # structlog configuration
├── heartbeat.py            # Heartbeat emitter
├── errors.py               # Exception hierarchy
├── types.py                # Shared dataclasses / TypedDicts / enums
└── pyproject.toml          # Pinned runtime dependencies
```

Each module's responsibility is outlined below. `runtime.py` is the orchestrator; every other module is a thin capability it composes.

### A.3 `RegionRuntime` — the event loop

The runtime's public entry point is the `RegionRuntime` class. Its job is to:

1. Load and validate `config.yaml` (F-Section).
2. Connect to MQTT, subscribe per `subscriptions.yaml`.
3. Load handlers from `handlers/`.
4. Run the heartbeat-paced event loop until shutdown.
5. Transition between wake and sleep states as triggers fire.
6. Gracefully tear down on SIGTERM (Docker stop).

#### A.3.1 Public API

```python
# region_template/runtime.py
from __future__ import annotations
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

from .config_loader import RegionConfig, load_config
from .types import LifecyclePhase
from .errors import ConfigError

if TYPE_CHECKING:
    from .mqtt_client import MqttClient
    from .llm_adapter import LlmAdapter
    from .memory import MemoryStore
    from .self_modify import SelfModifyTools
    from .sleep import SleepCoordinator


class RegionRuntime:
    """DNA for every Hive region. Runs as a single asyncio event loop."""

    def __init__(self, config_path: Path) -> None:
        self.config: RegionConfig = load_config(config_path)
        self.region_name: str = self.config.name
        self.root: Path = config_path.parent  # regions/<name>/
        self.phase: LifecyclePhase = LifecyclePhase.BOOTSTRAP
        self._shutdown = asyncio.Event()

        # Composed capabilities — created during bootstrap():
        self.mqtt: MqttClient
        self.llm: LlmAdapter
        self.memory: MemoryStore
        self.tools: SelfModifyTools
        self.sleep: SleepCoordinator

    async def bootstrap(self) -> None:
        """One-time init: validate, connect, subscribe, load handlers.

        MUST be called before run(). On failure, raises ConfigError
        or ConnectionError; glia will observe exit code and restart
        per policy (Section E.4).
        """
        ...

    async def run(self) -> None:
        """Main event loop. Returns only on shutdown."""
        ...

    async def shutdown(self, reason: str) -> None:
        """Graceful teardown. Idempotent.

        Ordering:
        1. Stop accepting new MQTT messages (unsubscribe).
        2. Drain in-flight LLM calls (with timeout).
        3. Flush STM to disk.
        4. Publish final heartbeat with status='shutdown'.
        5. Disconnect MQTT (LWT will NOT fire; clean disconnect).
        """
        ...

    # ── Phase transitions ─────────────────────────────────────────
    async def _enter_wake(self) -> None: ...
    async def _enter_sleep(self) -> None: ...
    async def _enter_shutdown(self, reason: str) -> None: ...

    # ── Event handlers ────────────────────────────────────────────
    async def _on_message(self, envelope: Envelope) -> None: ...
    async def _on_heartbeat_tick(self) -> None: ...
    async def _on_sleep_request_accepted(self) -> None: ...
```

#### A.3.2 Entry point

```python
# region_template/__main__.py
import argparse
import asyncio
import signal
from pathlib import Path
from .runtime import RegionRuntime
from .logging_setup import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()

    configure_logging()  # structlog JSON to stdout
    runtime = RegionRuntime(args.config)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def _signal_handler() -> None:
        loop.create_task(runtime.shutdown("SIGTERM"))

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _signal_handler)

    try:
        loop.run_until_complete(runtime.bootstrap())
        loop.run_until_complete(runtime.run())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
```

### A.4 Lifecycle: bootstrap → wake → sleep → restart

The runtime is a finite-state machine with four phases.

```
        ┌───────────┐
        │ BOOTSTRAP │ ◄── container start
        └─────┬─────┘
              │ bootstrap() success
              ▼
        ┌───────────┐
    ┌──►│   WAKE    │◄─┐
    │   └─────┬─────┘  │
    │         │        │ sleep complete, no restart
    │         │ sleep trigger
    │         ▼        │
    │   ┌───────────┐  │
    │   │   SLEEP   │──┘
    │   └─────┬─────┘
    │         │ sleep complete, restart required
    │         ▼
    │   ┌───────────┐
    │   │ SHUTDOWN  │ ─► container exit
    │   │ (restart) │
    │   └───────────┘
    │
    └─── any phase: SIGTERM → SHUTDOWN (terminal)
```

#### A.4.1 Phase enum

```python
# region_template/types.py
from enum import StrEnum


class LifecyclePhase(StrEnum):
    BOOTSTRAP = "bootstrap"
    WAKE = "wake"
    SLEEP = "sleep"
    SHUTDOWN = "shutdown"
```

#### A.4.2 BOOTSTRAP phase

Ordered steps in `RegionRuntime.bootstrap()`:

| # | Step | Failure behavior |
|---|---|---|
| 1 | Load and validate `config.yaml` against the JSON Schema in F.2 | Raise `ConfigError`, exit 2. Glia does NOT restart (F-Section). |
| 2 | Configure `structlog` with region name + correlation binding | N/A |
| 3 | Initialize the per-region git repo if not already (first boot) | Raise `GitError`, exit 3. |
| 4 | Connect to MQTT (with LWT) with exponential backoff (1s, 2s, 4s, 8s; cap at 30s; try for ≤ 60s total) | Raise `ConnectionError`, exit 4. Glia restarts. |
| 5 | Publish initial heartbeat with `status="boot"` | If publish fails, retry once; continue. |
| 6 | Read `subscriptions.yaml`; subscribe to each topic at the declared QoS | ACL rejection: log WARN, skip topic, continue. |
| 7 | If region is `mPFC`, publish bootstrap `hive/self/*` retained topics (see L.1 for the mPFC-owned topic set and B.4 for the full table). Other regions SHOULD subscribe to `hive/self/#` before proceeding. | Non-fatal. |
| 8 | Load handlers from `handlers/` (A.6) | On any handler import error: log ERROR, mark handler `degraded`; continue. |
| 9 | Initialize `MemoryStore` (read STM; do not load LTM into memory — queried on demand). | STM corruption: back up to `memory/stm.json.corrupt.<ts>` and start empty. |
| 10 | Set phase → `WAKE`. Publish `hive/system/heartbeat/<region>` with `status="wake"`. | — |

A region that fails bootstrap exits with a non-zero code. Glia's restart policy (E.4) discriminates by exit code.

#### A.4.3 WAKE phase

The wake phase is a concurrent asyncio loop with three primary coroutines:

1. **Message loop** (`_message_consumer`) — pulls envelopes from the MQTT queue and dispatches to handlers.
2. **Heartbeat tick** (`_heartbeat_loop`) — every `heartbeat_interval_s` (default 5s), emits heartbeat AND invokes `_on_heartbeat_tick` which gives the region a chance to run baseline activity (P-VIII).
3. **Sleep monitor** (`_sleep_monitor`) — watches for sleep triggers (A.4.5).

```python
async def run(self) -> None:
    assert self.phase == LifecyclePhase.WAKE
    tasks = [
        asyncio.create_task(self._message_consumer(), name="msg"),
        asyncio.create_task(self._heartbeat_loop(), name="hb"),
        asyncio.create_task(self._sleep_monitor(), name="sleep"),
    ]
    await self._shutdown.wait()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
```

Each handler invocation is wrapped in a supervision block:

```python
async def _dispatch(self, envelope: Envelope) -> None:
    handler = self._handler_for(envelope.topic)
    if handler is None:
        return  # not our topic
    try:
        async with asyncio.timeout(handler.timeout_s):
            await handler(envelope, ctx=self.ctx)
    except asyncio.TimeoutError:
        log.warn("handler_timeout", topic=envelope.topic, ...)
        await self._publish_metacog_error("handler_timeout", envelope)
    except Exception:
        log.exception("handler_crash", topic=envelope.topic, ...)
        await self._publish_metacog_error("handler_crash", envelope)
```

Handler crashes DO NOT crash the runtime. Metacognitive-error publication (`hive/metacognition/error/detected`) lets ACC observe and react (P-XIII).

#### A.4.4 SLEEP phase

Entry to sleep is cooperative:

1. Region publishes `hive/system/sleep/request` with its name.
2. Glia checks the region's inbound queue depth via MQTT (inspecting `hive/system/heartbeat/<region>` metadata, which includes a queue-depth snapshot). If `queue_depth_messages < sleep_max_queue_depth` (config, default 5), glia publishes `hive/system/sleep/granted` with the region name.
3. Region receives grant, transitions phase → `SLEEP`, cancels the **normal handler-dispatch** message consumer, and brings up a **minimal SLEEP-phase listener** (A.4.4.1). Heartbeat emission continues with `status="sleep"`.
4. `SleepCoordinator.run(ctx)` executes the sleep pipeline (Section D.5).
5. On completion, one of:
   - **No handler changes** → phase → `WAKE`, tear down the SLEEP-phase listener, resume the normal message consumer.
   - **Handler / prompt / subscription changes** → phase → `SHUTDOWN`, publish `hive/system/restart/request` with `reason="self_modification_commit=<sha>"`, exit 0.

##### A.4.4.1 SLEEP-phase message handling

During SLEEP, the normal handler-dispatch pipeline is paused — user-level traffic queues at the broker (QoS 1 delivery guarantees it on wake). But a small set of **system topics** must still be processed, otherwise sleep-internal flows (spawn replies, modulator-driven abort) cannot complete.

The runtime's SLEEP-phase listener subscribes to (and only to):

| Topic | Purpose |
|---|---|
| `hive/system/spawn/complete` (filter by `change_id` or name) | Reply to `spawn_new_region` calls |
| `hive/system/spawn/failed` (same filter) | Reply to `spawn_new_region` calls |
| `hive/system/codechange/failed` (ACC only) | Reply to `approve_code_change` calls (post-v0) |
| `hive/modulator/cortisol` | Fuel for `SleepCoordinator.abort()` when cortisol > threshold |
| `hive/broadcast/shutdown` | Graceful shutdown path must work during sleep |
| `hive/system/sleep/force` | Operator or ACC may escalate |

Messages on these topics are delivered to an in-process `asyncio.Queue` consumed by `SleepCoordinator`. Every other topic's messages buffer at the broker and are delivered on WAKE resumption (MQTT clean_session=false + QoS 1).

Handlers registered for the above topics in `handlers/` are NOT invoked during SLEEP — the SLEEP listener is a framework mechanism, not a handler dispatch path. This keeps sleep reasoning deterministic and prevents a handler from interfering with sleep-internal protocols.

Glia's restart policy treats exit 0 as "planned restart" (E.4).

Biology anchor (P-I): real sleep is not interruptible by casual stimuli. Hive sleep is weakly interruptible — a sufficiently urgent modulator (`cortisol > 0.8`) MAY trigger `SleepCoordinator.abort()`, which rolls back in-progress self-modifications and forces a `WAKE` transition. See A.8.

#### A.4.5 Sleep triggers

A region enters the sleep-request state when any of the following becomes true in `_sleep_monitor`:

| Trigger | Condition | Configurable? |
|---|---|---|
| Quiet window | No inbound messages for `sleep_quiet_window_s` (default 300s) | Yes, in `config.yaml` |
| Explicit request | Region's own logic called `ctx.request_sleep(reason)` | N/A |
| Heartbeat cycle | Every `sleep_max_wake_s` (default 3600s) force at least one sleep | Yes |
| External command | Received `hive/system/sleep/force` with matching region name | Operator / ACC only |
| STM pressure | STM size exceeds `stm_max_bytes` (default 256 KB) | Yes |

Exactly ONE trigger fires per transition. The fired trigger is recorded in the sleep's commit message (D.5.6).

#### A.4.6 SHUTDOWN phase

Two flavors:

- **Planned (exit 0):** graceful. Flush STM, publish final heartbeat with status (`sleep_restart`, `shutdown_signal`), disconnect MQTT cleanly. LWT does NOT fire.
- **Crash (exit nonzero):** LWT fires (`hive/system/heartbeat/<region>` with `status="dead"` retained). Glia observes and handles per policy.

Shutdown is bounded by `shutdown_timeout_s` (default 30s). If exceeded, runtime raises SystemExit with force code 137.

### A.5 Heartbeat cadence

Each region emits a heartbeat every `heartbeat_interval_s` (default 5s). Schema:

```json
{
  "region": "auditory_cortex",
  "status": "wake",
  "phase": "wake",
  "ts": "2026-04-19T10:30:00.000Z",
  "uptime_s": 1234,
  "handler_count": 3,
  "queue_depth_messages": 0,
  "llm_tokens_used_lifetime": 142301,
  "stm_bytes": 1823,
  "last_error_ts": null,
  "build_sha": "abcdef1"
}
```

`status` values: `boot | wake | sleep | sleep_restart | shutdown | dead` (dead set only by LWT).

Retained: **no**. Glia subscribes with QoS 1 to `hive/system/heartbeat/+` and maintains its own liveness map in memory (E.3).

**Why heartbeat carries queue depth**: sleep grant in A.4.4 step 2 needs this without a separate RPC.

### A.6 Handler plugin system

Handlers are per-region Python functions that respond to specific MQTT topics.

#### A.6.1 Handler contract

```python
# regions/<name>/handlers/example.py
from region_template.types import Envelope, HandlerContext

SUBSCRIPTIONS = ["hive/sensory/auditory/text"]
TIMEOUT_S = 10
QOS = 1


async def handle(envelope: Envelope, ctx: HandlerContext) -> None:
    text = envelope.payload["data"]
    ...  # use ctx.publish(), ctx.llm.complete(), ctx.memory.write_stm(), etc.
```

`SUBSCRIPTIONS`, `TIMEOUT_S`, `QOS` are module-level constants the loader reads.

A handler module MAY declare:

| Constant | Type | Default | Meaning |
|---|---|---|---|
| `SUBSCRIPTIONS` | `list[str]` | required | Topics this handler responds to |
| `TIMEOUT_S` | `int \| float` | 30 | Hard timeout on the handler coroutine |
| `QOS` | `int` | 1 | MQTT QoS to subscribe at |
| `ON_HEARTBEAT` | `bool` | False | Also called on each heartbeat tick |
| `REQUIRES_CAPABILITY` | `list[str]` | `[]` | Capabilities that must be declared in config |

#### A.6.2 `HandlerContext`

```python
@dataclass(frozen=True)
class HandlerContext:
    region_name: str
    phase: LifecyclePhase
    publish: Callable[..., Awaitable[None]]
    llm: LlmAdapter
    memory: MemoryStore
    tools: SelfModifyTools  # present but gated by capability + phase
    request_sleep: Callable[[str], None]
    log: structlog.BoundLogger
```

`tools` is always present. Individual tool calls fail if capability is missing (A.7) or phase != SLEEP (for self-modification tools).

#### A.6.3 Handler discovery

On bootstrap step 8:

```python
# region_template/handlers_loader.py
def discover(handlers_dir: Path) -> list[HandlerModule]:
    """Import every .py file under handlers_dir that isn't __init__.py,
    lint for the SUBSCRIPTIONS constant, and return a list of loaded
    HandlerModule objects. Import failures are logged as ERROR and the
    module is marked degraded (skipped). A region with zero valid
    handlers is legal — many starter regions begin that way."""
```

Loader rules:

- Only `.py` files directly under `handlers/` (no recursion at v0).
- A file lacking `SUBSCRIPTIONS` is skipped with a WARN.
- Duplicate topic→handler mappings cause BOOTSTRAP to fail (`ConfigError`).
- Hot-reload is available in dev mode via a `watchfiles` observer (Section K.3).

#### A.6.4 Topic dispatch

Dispatch is exact-match first, wildcard second. Wildcard handlers (those with `+`/`#` in `SUBSCRIPTIONS`) run AFTER exact-match handlers for the same envelope. Ties within a tier are resolved by registration order (deterministic by handler filename sort).

A handler that does NOT want to process a message MUST return without side effects. Raising to signal "not interested" is forbidden — it trips the crash path.

### A.7 Self-modification tool interfaces

`self_modify.py` exposes a small set of tools callable only during SLEEP and only if the region's capability profile permits. Tools are methods of a `SelfModifyTools` class instantiated once per region.

Every tool:

1. Verifies capability (raises `CapabilityDenied`).
2. Verifies phase == SLEEP (raises `PhaseViolation`).
3. Performs the action.
4. Returns a structured result (no exceptions for expected failures).

#### A.7.1 `append_appendix`

> **2026-04-21 divergence (append-only prompt evolution).** The prior `edit_prompt` tool has been **removed**. `regions/<name>/prompt.md` is now immutable constitutional DNA — written once at region birth by `glia/spawn_executor.py` and never overwritten. Evolution of a region's self-instructions happens via a per-region append-only appendix at `regions/<name>/memory/appendices/rolling.md`, owned by `region_template.appendix.AppendixStore`. Rationale: an early PFC self-mod cycle replaced its ~200-line constitutional starter prompt with a 4-item TODO list; the pipeline worked but the LLM's judgment on rewriting its own DNA was self-destructive. Removing the footgun is safer than adding guardrails around full prompt rewrites. See `docs/HANDOFF.md` Phase 11 "2026-04-21 — Append-only prompt evolution" divergence entry.

```python
async def append_appendix(self, section_body: str, trigger: str) -> AppendixResult:
    """Append a new dated section to regions/<name>/memory/appendices/rolling.md.

    Constraints:
    - trigger: non-empty, < 200 chars (used as H2 heading suffix and commit message)
    - section_body: valid UTF-8, < 64 KB
    - Lazy-creates rolling.md on first append
    - Framework prepends an H2 heading: '## <ISO-8601-timestamp> — <trigger>'
    - Atomicity: write to rolling.md.tmp, fsync, rename (via shared _atomic_write_text)
    """
```

`AppendixResult`: `{path: Path, bytes_appended: int, section_count: int}`.

**System-prompt assembly.** At every LLM call that builds a system prompt (today: sleep review; future: handler-driven LLM calls), `region_template.prompt_assembly.load_system_prompt` joins:

```
<prompt.md starter DNA>

# Evolution appendix

<rolling.md content>
```

The starter half is stable across calls (Anthropic cache-friendly); the appendix half grows over sleep cycles. The effective system prompt is `starter + "\n\n# Evolution appendix\n\n" + appendix`, presented to the LLM as a single `role="system"` message. STM / events / schema come through a separate `role="user"` message.

**Consolidation follow-up (deferred).** `rolling.md` is unbounded; summarization of older sections into a gist will be added once multi-week appendix data exists. Anthropic prompt caching on the stable starter half is the first-line token-cost mitigation in the meantime.

#### A.7.2 `edit_subscriptions`

```python
async def edit_subscriptions(
    self,
    subscriptions: list[SubscriptionEntry],
    reason: str,
) -> EditResult:
    """Overwrite regions/<name>/subscriptions.yaml.

    SubscriptionEntry = {topic: str, qos: int, description: str}

    Constraints:
    - Each topic must be syntactically valid MQTT (no trailing slash,
      no whitespace, wildcards only in last-but-one or last position).
    - The runtime verifies — via ACL probe on next boot (not here) —
      that the region has permission. Framework cannot check ACL
      itself because ACLs are broker-side; boot failure is the signal.
    """
```

#### A.7.3 `edit_handlers`

```python
async def edit_handlers(
    self,
    writes: list[HandlerWrite],
    deletes: list[str],
    reason: str,
) -> EditResult:
    """Create, overwrite, or delete files in regions/<name>/handlers/.

    HandlerWrite = {path: str, content: str}
    deletes = list of path strings (relative to handlers/)

    Constraints:
    - path must not contain '..' or '/..' (escape check)
    - path must end in '.py' (or be 'handlers/__init__.py')
    - After all writes/deletes, a static syntax check (ast.parse) is
      run on every .py file. Syntax error: no-op all changes, return
      EditResult(ok=False, error="syntax: <msg>").
    - reason min length 10 chars (handlers are high-impact).
    """
```

#### A.7.4 `write_memory`

Two variants: STM is ephemeral; LTM is consolidated.

```python
async def write_stm(self, key: str, value: Any) -> None:
    """Upsert a key in memory/stm.json. Atomic write-rename.
    Callable in WAKE too. No git commit — STM is working state.
    Raises StmOverflow if stm.json would exceed stm_max_bytes."""

async def write_ltm(
    self,
    filename: str,
    content: str,
    reason: str,
) -> EditResult:
    """Create or append to memory/ltm/<filename>.md. Sleep-only.
    Appends a dated heading block; never overwrites silently.
    Commits via commit_changes(). reason included in commit."""
```

#### A.7.5 `commit_changes`

```python
async def commit_changes(self, message: str) -> CommitResult:
    """Stage all tracked + new files under regions/<name>/ (sans
    .git/, __pycache__/), run git commit -m <message>.

    CommitResult = {sha: str, files_changed: int, lines_added: int,
                    lines_removed: int}

    Called automatically at the end of each self-modifying sleep step.
    MAY be called explicitly by handlers during sleep to checkpoint
    mid-pipeline (see D.5)."""
```

Commits are signed with `committer="<region_name> <region@hive.local>"`. Author is the same. Commit messages follow the template in D.5.7.

#### A.7.6 `request_restart`

```python
async def request_restart(self, reason: str) -> None:
    """Publish hive/system/restart/request with region + reason.
    Then gracefully transition phase → SHUTDOWN (exit 0).

    Glia's restart policy treats exit 0 as planned restart and will
    bring the container back up."""
```

Preconditions (all framework-checked):

- Phase == SLEEP
- `git status --porcelain` empty (must `commit_changes` first)
- Last commit has sha != the sha `/hive/region/.git/HEAD` had at bootstrap (at least one change since boot)

If any fails, returns `{ok: False, reason}`.

#### A.7.7 `spawn_new_region`

**Privileged tool.** Capability flag `can_spawn: true` is set ONLY for `anterior_cingulate` in F.3. Any other region calling this gets `CapabilityDenied` immediately.

**Why sleep-only:** a spawn creates persistent DNA-level side effects (new region directory, git repo, ACL entries, new container). Principle IX applies to all persistent architectural mutations, not just local handler edits. Treating spawn as sleep-only inherits the gating (phase, commit, rollback) that makes self-modification safe.

**Reply delivery:** the 30s block is serviced by the SLEEP-phase listener (A.4.4.1). `SelfModifyTools.spawn_new_region` publishes `hive/system/spawn/request`, then awaits an `asyncio.Future` that resolves when `hive/system/spawn/complete` (or `/failed`) arrives on the SLEEP listener with a matching `correlation_id`. On timeout, the Future is cancelled; glia may still publish `spawn/complete` later (best-effort reconciliation — the calling region has already recorded the request in STM and can observe the outcome on next WAKE via `hive/system/spawn/complete` retained by glia in a rolling 100-event log — see E.11).

```python
async def spawn_new_region(self, proposal: SpawnProposal) -> SpawnResult:
    """Publish hive/system/spawn/request with the full proposal.
    Blocks (up to 30s) waiting for hive/system/spawn/complete or
    hive/system/spawn/failed.

    SpawnProposal = {
      name: str,                # must match /^[a-z][a-z0-9_]{2,30}$/
      role: str,                # free-form description
      modality: str | None,     # e.g. 'olfactory', 'haptic', or null
      llm: {provider, model, params},
      capabilities: CapabilityProfile,
      starter_prompt: str,      # goes into prompt.md
      initial_subscriptions: list[SubscriptionEntry],
    }

    SpawnResult = {ok: bool, sha: str | None, reason: str | None}
    """
```

Biology anchor (P-I): in real brains, adult neurogenesis is rare and tightly regulated (hippocampus, SVZ). Hive mirrors this by gating spawn authority to a single region (ACC) and by making glia a pure executor — it never decides to spawn.

#### A.7.8 Capability gating in code

```python
# region_template/capability.py
from functools import wraps

def requires_capability(*caps: str):
    def dec(fn):
        @wraps(fn)
        async def wrapper(self, *a, **kw):
            for c in caps:
                if not self._caps.get(c):
                    raise CapabilityDenied(c)
            return await fn(self, *a, **kw)
        return wrapper
    return dec


def sleep_only(fn):
    @wraps(fn)
    async def wrapper(self, *a, **kw):
        if self._runtime.phase != LifecyclePhase.SLEEP:
            raise PhaseViolation(self._runtime.phase)
        return await fn(self, *a, **kw)
    return wrapper
```

Applied:

```python
class SelfModifyTools:
    @requires_capability("self_modify")
    @sleep_only
    async def append_appendix(self, ...): ...

    @requires_capability("self_modify")
    @sleep_only
    async def edit_handlers(self, ...): ...

    @requires_capability("can_spawn")
    @sleep_only
    async def spawn_new_region(self, ...): ...
```

### A.8 Wake/sleep state machine — detailed transitions

```
                   (async)
                   enter sleep: publish sleep/request, wait for grant
            ┌─────────────────────────────────────────────┐
            │                                             │
   ┌────────▼─────────┐   grant received   ┌──────────────▼──┐
   │       WAKE       │──────────────────►│      SLEEP       │
   │  (message loop   │                    │  (consolidate,  │
   │   running)       │                    │   self-modify)  │
   └────────▲─────────┘                    └────────┬───────┘
            │                                       │
            │             no changes               │ changes committed
            │◄──────────────────────────────────────┤
            │                                       ▼
            │                               ┌──────────────┐
            │                               │   SHUTDOWN   │
            │                               │  (exit 0,    │
            │                               │   planned    │
            │                               │   restart)   │
            │                               └──────┬───────┘
            │                                      │ docker restart
            │                                      ▼
            │                               ┌──────────────┐
            └───────────────────────────────┤  BOOTSTRAP   │
                                            │  (new code)  │
                                            └──────────────┘

   Crash at any point → exit nonzero → LWT fires → glia observes
```

Transition table:

| From | To | Trigger | Side effects |
|---|---|---|---|
| BOOTSTRAP | WAKE | bootstrap() success | Publish heartbeat `wake` |
| BOOTSTRAP | SHUTDOWN | ConfigError (exit 2) | No LWT (not connected) |
| BOOTSTRAP | SHUTDOWN | ConnectionError (exit 4) | No LWT |
| WAKE | sleep_request | any trigger in A.4.5 | Publish sleep/request |
| sleep_request | SLEEP | grant received | Stop message consumer |
| sleep_request | WAKE | timeout or denial | Log WARN, continue |
| SLEEP | WAKE | no handler changes | Resume message consumer |
| SLEEP | SHUTDOWN | changes committed, restart required | Publish restart/request |
| SLEEP | WAKE | forced abort (modulator > threshold) | Emergency wake via SleepCoordinator.abort(); in-progress edits reverted |
| any | SHUTDOWN | SIGTERM | Graceful path |
| any | crash | unhandled exception in runtime loop | Exit nonzero; LWT fires |

### A.9 Error hierarchy

```python
# region_template/errors.py

class HiveError(Exception):
    """Base."""

class ConfigError(HiveError):
    """config.yaml invalid or missing. Exit 2. Glia does NOT restart."""

class ConnectionError(HiveError):  # shadows builtin; fully-qualified only
    """MQTT unreachable after retries. Exit 4. Glia restarts with backoff."""

class CapabilityDenied(HiveError):
    """Tool call made without declared capability. Runtime-local."""

class PhaseViolation(HiveError):
    """Sleep-only tool called during wake (or vice versa)."""

class HandlerError(HiveError):
    """Base for handler-raised errors."""

class SandboxEscape(HiveError):
    """Tool attempted to write outside regions/<name>/. Fatal; crashes the region."""

class LlmError(HiveError):
    """Wraps LiteLLM exceptions; has .retryable attribute."""

class GitError(HiveError):
    """Per-region git operation failed."""

class StmOverflow(HiveError):
    """STM write would exceed configured max."""
```

Classification:

| Error | Phase caught | Action |
|---|---|---|
| `ConfigError`, `ConnectionError`, `GitError`, `SandboxEscape` | any | Fatal, exit nonzero |
| `CapabilityDenied`, `PhaseViolation` | runtime | Return error to caller; log INFO |
| `LlmError` (retryable) | runtime | Retry per policy (C.5); eventual fail → publish metacog error |
| `LlmError` (non-retryable) | runtime | Publish metacog error; continue |
| `HandlerError` | dispatch | Log, publish metacog error, continue |
| `StmOverflow` | dispatch | Force a sleep trigger; fail the current write |

### A.10 Concurrency model

- One asyncio event loop per container. No threads.
- MQTT I/O via `aiomqtt`.
- LLM calls via `httpx.AsyncClient` (underpinning LiteLLM).
- Git operations are blocking; wrapped via `asyncio.to_thread()`. Concurrency cap = 1 (no concurrent git commits in the same region).
- Handler dispatch is concurrent: each envelope spawns a task, bounded by a semaphore (default 8 concurrent handlers; `handler_concurrency_limit` in config).
- Backpressure: when the semaphore is full, the message consumer pauses pulling new envelopes. If paused > `backpressure_warn_s` (default 10s), publish `hive/metacognition/error/detected` with kind `backpressure`.

### A.11 Principles honored in Section A

- **P-III** (Sovereignty): region owns its lifecycle; no external actor drives it.
- **P-VII** (One template): `RegionRuntime` is literally one class.
- **P-VIII** (Always thinking): heartbeat tick guarantees baseline activity.
- **P-IX** (Wake/sleep): four-phase FSM enforces modification only in sleep.
- **P-X** (Capability honesty): decorators gate every self-modifying tool.
- **P-XII** (Every change committed): `commit_changes` is mandatory before `request_restart`.
- **P-XIII** (Emergence): handler crashes are surfaced as metacog errors, not corrected by the runtime.
- **P-XIV** (Chaos): runtime does NOT retry semantics-laden handlers; only I/O.

### A.12 Failure modes catalog

| Mode | Detected by | Handling |
|---|---|---|
| Bad config YAML | `config_loader.load_config` | Exit 2; no restart |
| MQTT broker unreachable | `mqtt_client.connect` | Retry 60s; exit 4; glia restarts |
| ACL reject on subscribe | `mqtt_client.subscribe` | Log WARN, skip topic |
| Handler import syntax error | `handlers_loader.discover` | Skip handler, ERROR log |
| Handler runtime exception | `_dispatch` | Publish metacog error; continue |
| Handler timeout | `_dispatch` | Publish metacog error; continue |
| LLM rate-limit | `llm_adapter` | Backoff; retry once; escalate |
| LLM over budget | `llm_adapter` | Fail call; publish metacog error |
| STM oversize | `memory.write_stm` | `StmOverflow`; force sleep |
| Git commit failure | `git_tools` | Fatal for the sleep cycle; no restart request; log ERROR |
| Sandbox escape attempt | `self_modify` tools | `SandboxEscape`; crash region; glia restarts |
| Sleep grant never arrives | `_sleep_monitor` | After 60s timeout, log WARN, stay awake, retry after 5× quiet-window |
| Self-modified code fails to boot | next BOOTSTRAP | Exit 2 → glia rolls back (E.5) |

---

## Section B — MQTT layer (`bus/`)

The MQTT layer is the nervous system (P-II). Every inter-region signal flows through it. This section specifies the broker, the ACLs, the envelope schema, QoS choices, retained-flag conventions, and the connection lifecycle.

### B.1 Module layout

```
bus/
├── mosquitto.conf             # Broker configuration
├── acl.conf                   # Generated from templates/, applied by glia
├── acl_templates/             # Per-region ACL fragments (jinja2)
│   ├── _base.j2              # Common rules (LWT, heartbeat)
│   ├── auditory_cortex.j2
│   ├── visual_cortex.j2
│   ├── mpfc.j2
│   ├── acc.j2
│   └── … one per region
├── topic_schema.md            # Canonical reference (mirrors architecture.md §4)
└── passwd                     # Password file (dev: plaintext; prod: mosquitto_passwd)

shared/
├── message_envelope.py        # Envelope dataclass + JSON Schema + validator
├── envelope_schema.json       # Draft 2020-12 JSON Schema (source of truth)
└── topics.py                  # Typed topic constants, wildcards, helpers
```

`bus/` is read by mosquitto and glia. `shared/` is imported by `region_template/` and glia.

### B.2 Message envelope — JSON Schema

**Every** MQTT payload published by Hive code (non-hardware topics) is a JSON envelope conforming to this schema. Hardware topics (e.g., `hive/hardware/mic`) carry raw bytes and are exempt.

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hive.local/schemas/envelope/v1.json",
  "title": "Hive Message Envelope v1",
  "type": "object",
  "required": ["id", "timestamp", "source_region", "topic", "payload", "envelope_version"],
  "additionalProperties": false,
  "properties": {
    "envelope_version": {
      "type": "integer",
      "const": 1,
      "description": "Schema version. Breaking changes bump this."
    },
    "id": {
      "type": "string",
      "format": "uuid",
      "description": "UUID v4 unique to this message. Used for deduplication and tracing."
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "RFC 3339 UTC timestamp with millisecond precision."
    },
    "source_region": {
      "type": "string",
      "pattern": "^[a-z][a-z0-9_]{2,30}$",
      "description": "Region name. Must match the region's config.name."
    },
    "topic": {
      "type": "string",
      "minLength": 1,
      "description": "MQTT topic this was published to. Duplicated in payload for convenience; MUST match actual pub topic."
    },
    "reply_to": {
      "type": ["string", "null"],
      "description": "Optional: topic the receiver SHOULD respond on."
    },
    "correlation_id": {
      "type": ["string", "null"],
      "format": "uuid",
      "description": "Links a chain of messages that descend from an originating event."
    },
    "attention_hint": {
      "type": "number",
      "minimum": 0.0,
      "maximum": 1.0,
      "description": "Publisher's suggested priority. Thalamus uses this for gating. Default 0.5."
    },
    "payload": {
      "type": "object",
      "required": ["content_type", "data"],
      "additionalProperties": false,
      "properties": {
        "content_type": {
          "type": "string",
          "enum": [
            "text/plain",
            "application/json",
            "application/hive+memory-query",
            "application/hive+memory-response",
            "application/hive+sensory-features",
            "application/hive+motor-intent",
            "application/hive+modulator",
            "application/hive+self-state",
            "application/hive+spawn-proposal",
            "application/hive+spawn-request",
            "application/hive+code-change-proposal",
            "application/hive+reflection",
            "application/hive+error"
          ],
          "description": "Payload MIME-ish type. Specialized types have their own sub-schemas (B.3)."
        },
        "data": {
          "description": "Type depends on content_type. Validated by matching sub-schema."
        },
        "encoding": {
          "type": "string",
          "enum": ["utf-8", "base64"],
          "default": "utf-8"
        }
      }
    }
  }
}
```

#### B.2.1 Python dataclass

```python
# shared/message_envelope.py
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal
import json
import uuid
from jsonschema import Draft202012Validator

ENVELOPE_VERSION = 1

ContentType = Literal[
    "text/plain",
    "application/json",
    "application/hive+memory-query",
    # ...
]

@dataclass(frozen=True)
class Payload:
    content_type: ContentType
    data: Any
    encoding: Literal["utf-8", "base64"] = "utf-8"

@dataclass(frozen=True)
class Envelope:
    source_region: str
    topic: str
    payload: Payload
    envelope_version: int = ENVELOPE_VERSION
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(
            timespec="milliseconds"
        )
    )
    reply_to: str | None = None
    correlation_id: str | None = None
    attention_hint: float = 0.5

    def to_json(self) -> bytes:
        return json.dumps(asdict(self)).encode("utf-8")

    @classmethod
    def from_json(cls, data: bytes) -> "Envelope":
        obj = json.loads(data.decode("utf-8"))
        _VALIDATOR.validate(obj)
        p = obj.pop("payload")
        return cls(payload=Payload(**p), **obj)


_VALIDATOR = Draft202012Validator(
    json.loads((Path(__file__).parent / "envelope_schema.json").read_text())
)
```

#### B.2.2 Validation policy

- **Producers** always validate before publish (fail fast in dev; log + drop in prod).
- **Consumers** validate before dispatch. Invalid envelope → publish `hive/metacognition/error/detected` with kind `poison_message` and drop.
- **Hardware topics** (raw bytes) bypass validation. A hardware publisher that wraps raw bytes in an envelope is MISBEHAVING and the consumer should log at ERROR.

### B.3 Content-type sub-schemas

Each `content_type` has a stable `data` shape. Non-exhaustive at v0; regions can add new types by publishing a Code Change Proposal that includes the new sub-schema.

#### B.3.1 `application/hive+memory-query`

```json
{
  "type": "object",
  "required": ["question", "topics"],
  "properties": {
    "question": {"type": "string", "minLength": 1, "maxLength": 2000},
    "topics": {
      "type": "array",
      "items": {"type": "string"},
      "description": "Free-form tags to guide retrieval, e.g. ['user:alex', 'topic:project-x']."
    },
    "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 5},
    "timeframe_hint": {
      "type": "string",
      "enum": ["any", "today", "this_week", "this_month", "ltm_only"],
      "default": "any"
    }
  }
}
```

#### B.3.2 `application/hive+memory-response`

```json
{
  "type": "object",
  "required": ["query_id", "results"],
  "properties": {
    "query_id": {"type": "string", "format": "uuid"},
    "results": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["source", "content", "confidence"],
        "properties": {
          "source": {"type": "string", "description": "e.g. 'ltm/episodes/2026-04-10.md'"},
          "content": {"type": "string"},
          "confidence": {"type": "number", "minimum": 0, "maximum": 1},
          "emotional_tag": {"type": "string", "enum": ["neutral", "positive", "negative", "alarming"]}
        }
      }
    }
  }
}
```

#### B.3.3 `application/hive+modulator`

```json
{
  "type": "object",
  "required": ["value"],
  "properties": {
    "value": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    "decay_half_life_s": {"type": "number", "minimum": 1, "description": "Producer's intended decay; informational."},
    "cause": {"type": "string", "description": "Short phrase: 'loud_impulse', 'low_token_budget', ..."}
  }
}
```

#### B.3.4 `application/hive+self-state`

> **2026-04-22 divergence:** `developmental_stage` and `age` removed. Developmental state is emergent from accumulated experience, not a categorical field; age is computed on demand as `delta(first_memory_timestamp, now)` via hippocampus query. See `docs/HANDOFF.md` Phase 11 divergence entry.

```json
{
  "type": "object",
  "properties": {
    "identity": {"type": "string"},
    "values": {"type": "array", "items": {"type": "string"}},
    "personality": {"type": "string"},
    "autobiographical_index": {"type": "object"}
  }
}
```

One `hive/self/*` topic per scalar field (mPFC splits the object across topics for retained-granularity). See B.4 for topic mapping.

#### B.3.5 `application/hive+error`

For `hive/metacognition/error/detected`:

```json
{
  "type": "object",
  "required": ["kind", "detail"],
  "properties": {
    "kind": {
      "type": "string",
      "enum": [
        "handler_timeout",
        "handler_crash",
        "poison_message",
        "source_spoof",
        "llm_failure",
        "llm_over_budget",
        "backpressure",
        "capability_denied",
        "sandbox_escape",
        "acl_rejected",
        "acl_render_failure",
        "acl_conflict",
        "git_failure",
        "oom_kill",
        "crash_loop",
        "region_config_error",
        "region_git_error",
        "region_rollback",
        "rollback_failed",
        "singleton_violation",
        "unknown_region_type",
        "spawn_rejected",
        "codechange_rejected",
        "codechange_failed",
        "codechange_rollback",
        "self_model_mismatch"
      ],
      "description": "Closed enumeration. Adding a kind requires a spec update and envelope_version bump. Consumers MUST reject unknown kinds as poison_message."
    },
    "detail": {"type": "string"},
    "context": {"type": "object", "description": "kind-specific additional fields"}
  }
}
```

#### B.3.6 `application/hive+motor-intent`

Carried on `hive/motor/intent` and `hive/motor/speech/intent`.

```json
{
  "type": "object",
  "required": ["action"],
  "properties": {
    "action": {"type": "string", "minLength": 1, "description": "Free-form action label, e.g. 'write_file', 'http_get', or for speech: 'speak'"},
    "text": {"type": "string", "description": "For speech intents: the utterance text"},
    "parameters": {"type": "object", "description": "Action-specific arguments"},
    "urgency": {"type": "string", "enum": ["low", "normal", "high"], "default": "normal"},
    "deadline_ms": {"type": "integer", "minimum": 0, "description": "Optional SLA. 0 = no deadline."}
  }
}
```

#### B.3.7 `application/hive+sensory-features`

Carried on `hive/sensory/*/features`. Intentionally schema-light — sensory regions own the shape per modality.

```json
{
  "type": "object",
  "required": ["modality", "features"],
  "properties": {
    "modality": {"type": "string", "enum": ["visual", "auditory", "haptic", "olfactory"]},
    "features": {
      "type": "object",
      "description": "Modality-specific feature bag. Consumers look up keys they care about and ignore the rest. Publisher SHOULD document the key set in its starter prompt."
    },
    "ts_window_ms": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2, "description": "[start_ms, end_ms] observation window"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
  }
}
```

#### B.3.8 `application/hive+spawn-proposal`

Carried on `hive/system/spawn/proposed` (any region may publish to suggest a spawn; ACC deliberates).

```json
{
  "type": "object",
  "required": ["name", "role", "rationale"],
  "properties": {
    "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{2,30}$"},
    "role": {"type": "string", "minLength": 10, "maxLength": 500},
    "modality": {"type": ["string", "null"], "description": "New modality this region owns, if any"},
    "rationale": {"type": "string", "minLength": 20, "description": "Why this region is needed. ACC reads this."},
    "suggested_llm": {
      "type": "object",
      "properties": {
        "provider": {"type": "string"},
        "model": {"type": "string"}
      }
    },
    "suggested_capabilities": {"$ref": "#/$defs/capabilities"}
  }
}
```

#### B.3.9 `application/hive+spawn-request`

Carried on `hive/system/spawn/request` (only ACC may publish; glia executes).

```json
{
  "type": "object",
  "required": ["name", "role", "llm", "capabilities", "starter_prompt", "initial_subscriptions"],
  "properties": {
    "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{2,30}$"},
    "role": {"type": "string", "minLength": 10, "maxLength": 500},
    "modality": {"type": ["string", "null"]},
    "llm": {
      "type": "object",
      "required": ["provider", "model"],
      "properties": {
        "provider": {"type": "string"},
        "model": {"type": "string"},
        "params": {"type": "object"}
      }
    },
    "capabilities": {"$ref": "#/$defs/capabilities"},
    "starter_prompt": {"type": "string", "minLength": 100},
    "initial_subscriptions": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["topic", "qos"],
        "properties": {
          "topic": {"type": "string"},
          "qos": {"type": "integer", "minimum": 0, "maximum": 1},
          "description": {"type": "string"}
        }
      }
    },
    "approved_by_acc": {"type": "string", "format": "uuid", "description": "ID of ACC's deliberation record"}
  }
}
```

#### B.3.10 `application/hive+code-change-proposal`

Carried on `hive/system/codechange/proposed` and `hive/system/codechange/approved`.

```json
{
  "type": "object",
  "required": ["change_id", "patch", "justification", "affected_regions"],
  "properties": {
    "change_id": {"type": "string", "format": "uuid"},
    "patch": {"type": "string", "description": "Unified diff against region_template/ or bus/"},
    "justification": {"type": "string", "minLength": 50},
    "affected_regions": {"type": "array", "items": {"type": "string"}},
    "approver_region": {"type": "string", "description": "Required on /approved: which cognitive region authorized"},
    "human_cosigner": {"type": "string", "description": "Required on /approved at v0: email or key ID"},
    "cosign_signature": {"type": "string", "description": "Required on /approved: detached signature over patch+change_id"}
  }
}
```

#### B.3.11 `application/hive+reflection`

Carried on `hive/metacognition/reflection/request` and `hive/metacognition/reflection/response`.

```json
{
  "type": "object",
  "properties": {
    "topic": {"type": "string", "description": "What to reflect on; e.g., 'recent anger', 'identity since last sleep'"},
    "depth": {"type": "string", "enum": ["quick", "deep"], "default": "quick"},
    "context": {"type": "string", "description": "Optional pre-context from the asker"},
    "reflection": {"type": "string", "description": "On /response: the reflection itself"},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
  },
  "oneOf": [
    {"required": ["topic"]},
    {"required": ["reflection"]}
  ]
}
```

#### B.3.12 Validation policy for unmatched content types

If a consumer receives an envelope whose `content_type` is listed in the envelope `content_type` enum (B.2) but has no sub-schema in B.3.1 – B.3.11, the consumer MUST:

- Accept the envelope (the outer schema passed).
- Skip deep validation of `payload.data`.
- Log at DEBUG the missing sub-schema reference.

Adding a new content-type to B.2 requires adding its B.3 sub-schema in the same spec update — no orphan types. The "Other content types" slot (e.g., `application/hive+reflection`) exists so new types can be added incrementally without breaking existing consumers.

### B.4 Topic catalog (canonical)

This is the single source of truth for topics in v0. `bus/topic_schema.md` MUST be regenerated from this table during implementation. Each row lists the topic, retained flag, QoS, publisher ACL, subscriber ACL, and content_type.

Legend:

- **R** = retained flag
- **QoS** = default publish QoS (consumers MAY subscribe at lower)
- **Publishers** = who MAY publish (glia-enforced via ACL template B.6)
- **Subscribers** = who MAY subscribe (same)
- `*` in a column means "any region that declares interest"
- `—` means "none" (topic is terminal or one-way)

#### Hardware — raw I/O, ACL-gated

| Topic | R | QoS | Publishers | Subscribers | Content |
|---|---|---|---|---|---|
| `hive/hardware/mic` | N | 0 | `auditory_cortex` (producer handler, or OS bridge running as auditory_cortex) | `auditory_cortex` | raw bytes (not envelope) |
| `hive/hardware/camera` | N | 0 | `visual_cortex` | `visual_cortex` | raw bytes |
| `hive/hardware/speaker` | N | 1 | `broca_area` | glia's audio-bridge (not a region) | raw bytes |
| `hive/hardware/motor` | N | 1 | `motor_cortex` | glia's motor-bridge | raw bytes |

Hardware bridges are Section E.8.

#### Sensory — processed output, broadcast-safe

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/sensory/visual/processed` | N | 1 | `visual_cortex` | `*` |
| `hive/sensory/visual/features` | N | 1 | `visual_cortex` | `*` |
| `hive/sensory/auditory/text` | N | 1 | `auditory_cortex` | `*` |
| `hive/sensory/auditory/features` | N | 1 | `auditory_cortex` | `*` |
| `hive/sensory/auditory/events` | N | 1 | `auditory_cortex` | `*` |
| `hive/sensory/input/text` | N | 1 | external bridge (host typing) | `*` |

#### Cognitive — inter-region messaging

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/cognitive/thalamus/attend` | N | 1 | `thalamus` | `*` |
| `hive/cognitive/prefrontal/plan` | N | 1 | `prefrontal_cortex` | `*` |
| `hive/cognitive/hippocampus/query` | N | 1 | `*` | `hippocampus` |
| `hive/cognitive/hippocampus/response` | N | 1 | `hippocampus` | `*` |
| `hive/cognitive/association/integrate` | N | 1 | `association_cortex` | `*` |
| `hive/cognitive/<region>/#` | N | 1 | `*` (to publish TO `<region>`) | `<region>` (only) |

The wildcard rule: `hive/cognitive/<region>/request` is a dedicated inbox for `<region>`. Only `<region>` subscribes. Any region publishes.

#### Motor — pre-hardware intents

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/motor/intent` | N | 1 | `prefrontal_cortex`, `basal_ganglia` | `motor_cortex` |
| `hive/motor/intent/cancel` | N | 1 | `prefrontal_cortex` | `motor_cortex` |
| `hive/motor/speech/intent` | N | 1 | `prefrontal_cortex`, `basal_ganglia` | `broca_area` |
| `hive/motor/speech/cancel` | N | 1 | `prefrontal_cortex` | `broca_area` |
| `hive/motor/speech/complete` | N | 1 | `broca_area` | `*` |
| `hive/motor/complete` | N | 1 | `motor_cortex` | `*` |
| `hive/motor/failed` | N | 1 | `motor_cortex`, `broca_area` | `*` |
| `hive/motor/partial` | N | 1 | `motor_cortex` | `*` |

#### System — framework/infrastructure

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/system/heartbeat/<region>` | N (normal); retained on LWT | 1 | `<region>` | `glia` |
| `hive/system/sleep/request` | N | 1 | `*` | `glia` |
| `hive/system/sleep/granted` | N | 1 | `glia` | `*` |
| `hive/system/sleep/force` | N | 1 | `glia`, `anterior_cingulate` | `*` |
| `hive/system/restart/request` | N | 1 | `*` | `glia` |
| `hive/system/spawn/proposed` | N | 1 | `*` | `anterior_cingulate`, `hippocampus` |
| `hive/system/spawn/request` | N | 1 | `anterior_cingulate` | `glia` |
| `hive/system/spawn/complete` | N | 1 | `glia` | `*` |
| `hive/system/spawn/failed` | N | 1 | `glia` | `*` |
| `hive/system/spawn/query` | N | 1 | `*` | `glia` |
| `hive/system/spawn/query_response` | N | 1 | `glia` | `*` |
| `hive/system/codechange/proposed` | N | 1 | `*` | `anterior_cingulate`, external human |
| `hive/system/codechange/approved` | N | 1 | `anterior_cingulate` (co-signed) | `glia` |
| `hive/system/metrics/compute` | R (last value) | 0 | `glia` | `*` |
| `hive/system/metrics/tokens` | R | 0 | `glia` | `*` |
| `hive/system/metrics/region_health` | R | 0 | `glia` | `*` |
| `hive/system/region_stats/<region>` | N | 0 | `<region>` | `glia` |

#### Metacognition — ACC channels

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/metacognition/error/detected` | N | 1 | `*` | `anterior_cingulate`, `glia` (logging) |
| `hive/metacognition/conflict/observed` | N | 1 | `anterior_cingulate`, `medial_prefrontal_cortex` | `*` |
| `hive/metacognition/reflection/request` | N | 1 | `*` | `medial_prefrontal_cortex`, `anterior_cingulate` |
| `hive/metacognition/reflection/response` | N | 1 | `medial_prefrontal_cortex`, `anterior_cingulate` | `*` |

#### Attention — shared state

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/attention/focus` | **R** | 1 | `prefrontal_cortex` | `*` |
| `hive/attention/salience` | **R** | 1 | `thalamus` | `*` |

#### Self — global identity

> **2026-04-22 divergence:** `hive/self/developmental_stage` and `hive/self/age` removed. See `docs/HANDOFF.md` Phase 11 divergence entry.

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/self/identity` | **R** | 1 | `medial_prefrontal_cortex` | `*` |
| `hive/self/values` | **R** | 1 | `medial_prefrontal_cortex` | `*` |
| `hive/self/personality` | **R** | 1 | `medial_prefrontal_cortex` | `*` |
| `hive/self/autobiographical_index` | **R** | 1 | `medial_prefrontal_cortex` | `*` |

#### Interoception — felt body state

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/interoception/compute_load` | **R** | 0 | `insula` | `*` |
| `hive/interoception/token_budget` | **R** | 0 | `insula` | `*` |
| `hive/interoception/region_health` | **R** | 0 | `insula` | `*` |
| `hive/interoception/felt_state` | **R** | 0 | `insula` | `*` |

#### Habit

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/habit/suggestion` | N | 1 | `basal_ganglia` | `motor_cortex`, `broca_area`, `prefrontal_cortex` |
| `hive/habit/reinforce` | N | 1 | `vta` | `basal_ganglia` |
| `hive/habit/learned` | N | 1 | `basal_ganglia` | `*` |

#### Modulator — ambient chemical fields

All retained. QoS 0 (publisher re-publishes often; occasional loss is acceptable, retained value catches new subscribers).

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/modulator/dopamine` | **R** | 0 | `vta` | `*` |
| `hive/modulator/cortisol` | **R** | 0 | `amygdala` (v0) | `*` |
| `hive/modulator/norepinephrine` | **R** | 0 | `amygdala` (v0) | `*` |
| `hive/modulator/serotonin` | **R** | 0 | `raphe_nuclei` (post-v0) | `*` |
| `hive/modulator/acetylcholine` | **R** | 0 | `basal_forebrain` (post-v0) | `*` |
| `hive/modulator/oxytocin` | **R** | 0 | `hypothalamus` (post-v0) | `*` |

**Important**: `serotonin` etc. have publisher slots reserved even in v0 so new modulator regions spawn without requiring an ACL migration. At v0 the slots are empty (no publisher); subscribers see no retained value and treat that as the neutral/default.

#### Rhythm — oscillatory timing

Broadcast, not retained. A late subscriber simply misses prior ticks.

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/rhythm/gamma` | N | 0 | glia's `rhythm_generator` bridge | `*` |
| `hive/rhythm/beta` | N | 0 | glia | `*` |
| `hive/rhythm/theta` | N | 0 | glia | `*` |

Rhythm generator is a glia service (E.7). It publishes a tiny envelope:

```json
{"beat": 12345, "rate_hz": 40, "ts": "2026-04-19T10:30:00.025Z"}
```

`beat` is a monotonic counter per rhythm band.

#### Broadcast

| Topic | R | QoS | Publishers | Subscribers |
|---|---|---|---|---|
| `hive/broadcast/shutdown` | N | 1 | `glia` | `*` |

### B.5 Retained-flag conventions

Retained topics have a specific semantic (P-XVI):

- **Modulators** — current level of an ambient chemical.
- **Self** — current narrative identity facts.
- **Interoception** — current felt body state.
- **Attention** — current focus/salience.
- **System metrics** — latest snapshot only.
- **Heartbeat LWT** — `status="dead"` retained on unexpected disconnect; the same topic is otherwise non-retained.

A publisher using retained semantics MUST:

1. Publish the updated value whenever it changes (no polling).
2. To **explicitly clear** a retained value (e.g., amygdala zeroing cortisol before sleep), publish a zero-length payload with `retain=true` — this is MQTT's native clear-retained mechanism and is honored by both the broker (removes the retained slot) and the envelope validator (zero-length payloads are exempt from schema validation for the clear case). Consumers MUST treat a zero-length payload on a retained topic as "topic cleared; return to default."
3. Document the decay/TTL policy in its starter prompt (already done for amygdala, VTA).

A publisher MUST NOT publish retained to a topic not on the retained list in B.4.

### B.6 ACL rules (mosquitto format)

Glia generates `acl.conf` from templates. Base skeleton:

```
# bus/acl.conf  (generated — DO NOT hand-edit)
# Generated at 2026-04-19T10:30:00Z by glia/acl_manager.py

# Deny by default
pattern deny #

# ── Common rules for every region ─────────────────────────────────
user %c
# Every region publishes its own heartbeat and per-region stats
pattern write hive/system/heartbeat/%c
pattern write hive/system/region_stats/%c
# Every region publishes metacog errors and sleep requests
topic write hive/metacognition/error/detected
topic write hive/system/sleep/request
topic write hive/system/restart/request
# Every region subscribes to globally broadcast state
topic read hive/self/#
topic read hive/interoception/#
topic read hive/modulator/#
topic read hive/attention/#
topic read hive/rhythm/#
topic read hive/system/sleep/granted
topic read hive/system/metrics/#
topic read hive/broadcast/#

# ── Per-region rules (generated from acl_templates/) ──────────────

user auditory_cortex
topic read  hive/hardware/mic
topic write hive/sensory/auditory/text
topic write hive/sensory/auditory/features
topic write hive/sensory/auditory/events
topic read  hive/cognitive/auditory_cortex/#
topic write hive/cognitive/auditory_cortex/#

user visual_cortex
topic read  hive/hardware/camera
topic write hive/sensory/visual/processed
topic write hive/sensory/visual/features
topic read  hive/cognitive/visual_cortex/#
topic write hive/cognitive/visual_cortex/#

user medial_prefrontal_cortex
topic write hive/self/identity
topic write hive/self/values
topic write hive/self/personality
topic write hive/self/autobiographical_index
topic write hive/metacognition/conflict/observed
topic write hive/metacognition/reflection/response
topic read  hive/metacognition/reflection/request
topic write hive/cognitive/hippocampus/query
topic write hive/cognitive/anterior_cingulate/query
topic write hive/cognitive/basal_ganglia/query

user amygdala
topic write hive/modulator/cortisol
topic write hive/modulator/norepinephrine
topic read  hive/sensory/visual/processed
topic read  hive/sensory/visual/features
topic read  hive/sensory/auditory/features
topic read  hive/sensory/auditory/events
topic write hive/cognitive/hippocampus/encoding_hint
topic read  hive/cognitive/hippocampus/response

user vta
topic write hive/modulator/dopamine
topic write hive/habit/reinforce
topic read  hive/motor/complete
topic read  hive/motor/speech/complete
topic read  hive/motor/failed

user anterior_cingulate
topic read  hive/metacognition/#
topic write hive/metacognition/conflict/observed
topic write hive/metacognition/reflection/response
topic read  hive/system/spawn/proposed
topic write hive/system/spawn/request
topic read  hive/system/codechange/proposed
topic write hive/system/codechange/approved
topic write hive/system/sleep/force
topic write hive/cognitive/hippocampus/query

user glia
# Glia has near-root access for its infrastructure role
topic write hive/system/sleep/granted
topic write hive/system/spawn/complete
topic write hive/system/spawn/failed
topic write hive/system/metrics/#
topic write hive/broadcast/#
topic write hive/rhythm/#
topic read  hive/system/#
topic read  hive/metacognition/error/detected

# ... (one block per region)
```

Templates live in `bus/acl_templates/<region>.j2`. Glia renders all templates into one `acl.conf`, signals mosquitto via `docker kill -s SIGHUP mosquitto` to reload. This is a **mechanism** (E.6). Glia never decides what the template says — the templates are authored at design time or during approved code-change flows.

#### B.6.1 ACL conflicts

Two templates cannot grant the same topic to two different regions unless the topic is explicitly in the "broadcast-safe" set (sensory processed, modulator read, self read, etc.). Glia's ACL manager runs a consistency check before reload:

- Overlapping WRITE on a non-broadcast topic → abort reload, log ERROR, notify ACC via `hive/metacognition/error/detected` with kind `acl_rejected`.
- Subscribe to a hardware/restricted topic by an unauthorized region → abort reload.

### B.7 QoS policy

| Topic class | QoS default | Reasoning |
|---|---|---|
| Hardware raw | 0 | Streaming byte volume; one lost packet is fine |
| Sensory processed | 1 | Every transcript/feature vector matters |
| Cognitive messages | 1 | Each is a deliberate signal |
| Motor intents | 1 | Action must not be lost |
| Motor completions | 1 | Consumers (VTA for reinforcement) need each outcome |
| System/heartbeat | 1 | Glia needs exact liveness |
| Metacognition | 1 | ACC must see errors |
| Attention (retained) | 1 | Goal state matters |
| Self (retained) | 1 | Identity matters |
| Interoception (retained) | 0 | High-frequency; retained value is catch-up |
| Modulator (retained) | 0 | Same |
| Rhythm | 0 | Periodic; missed tick is just a missed tick |
| Broadcast shutdown | 1 | Must arrive |

QoS 2 is NOT used — its overhead (4-way handshake) is not justified at v0.

### B.8 Broker configuration — mosquitto

```conf
# bus/mosquitto.conf
listener 1883 0.0.0.0
protocol mqtt

# Persistence for retained topics across broker restarts
persistence true
persistence_location /mosquitto/data/
persistence_file mosquitto.db
autosave_interval 60

# ACLs
acl_file /mosquitto/config/acl.conf

# Auth
password_file /mosquitto/config/passwd
allow_anonymous false

# Connection limits
max_connections 256
max_inflight_messages 100
max_queued_messages 1000
queue_qos0_messages false  # drop QoS 0 when queue full

# Retained message size cap (Hive envelopes are small)
message_size_limit 1048576  # 1 MB hard cap

# Logging
log_dest stdout
log_type error
log_type warning
log_type notice
log_type information
log_timestamp true
connection_messages true
```

Notes:

- `allow_anonymous false` — every region authenticates as its own user; the ACL is anchored on `%c` (username).
- `persistence` ON — retained modulator/self/interoception values survive broker restart. Non-retained queues do not (intentional).
- `message_size_limit` of 1 MB cages poison payloads. Sensory/envelope payloads are always well under this; hardware topics that exceed (high-resolution image) should chunk (not v0's concern).

### B.9 Connection lifecycle — client side

```python
# region_template/mqtt_client.py
import aiomqtt
from aiomqtt import Will, ProtocolVersion

class MqttClient:
    def __init__(self, cfg: MqttConfig, region_name: str) -> None:
        self._cfg = cfg
        self._region_name = region_name
        self._client: aiomqtt.Client | None = None
        self._out_queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=256)
        self._in_queue: asyncio.Queue[Envelope] = asyncio.Queue(maxsize=256)

    async def connect(self) -> None:
        lwt_payload = Envelope(
            source_region=self._region_name,
            topic=f"hive/system/heartbeat/{self._region_name}",
            payload=Payload(
                content_type="application/json",
                data={"status": "dead", "detail": "lwt"},
            ),
        ).to_json()

        will = Will(
            topic=f"hive/system/heartbeat/{self._region_name}",
            payload=lwt_payload,
            qos=1,
            retain=True,
        )

        attempt = 0
        while attempt < self._cfg.max_connect_attempts:
            try:
                self._client = aiomqtt.Client(
                    hostname=self._cfg.host,
                    port=self._cfg.port,
                    identifier=f"hive-{self._region_name}",
                    username=self._region_name,
                    password=self._cfg.password,
                    will=will,
                    keepalive=self._cfg.keepalive_s,
                    protocol=ProtocolVersion.V5,
                    clean_session=False,  # resumable session for QoS 1 delivery
                )
                await self._client.__aenter__()
                return
            except (aiomqtt.MqttError, OSError) as e:
                delay = min(30, 2 ** attempt)
                log.warn("mqtt_connect_retry", attempt=attempt, delay_s=delay, err=str(e))
                await asyncio.sleep(delay)
                attempt += 1
        raise ConnectionError(f"mqtt unreachable after {attempt} attempts")
```

Key details:

- **Last Will and Testament**: when the region dies unexpectedly, broker publishes the LWT to `hive/system/heartbeat/<region>` with `status="dead"` and retained=true. Glia sees this and reacts (E.3).
- **Clean disconnect**: shutdown path calls `await self._client.__aexit__()` without setting LWT; broker does NOT publish the will.
- **Resumable session**: `clean_session=False` so QoS 1 messages queued for a temporarily disconnected region are delivered on reconnect.
- **MQTT v5**: required for features we rely on (`user properties` for tracing, `session expiry`).

### B.10 Reconnection policy

- Disconnect mid-run: `aiomqtt` raises `MqttError` to the consumer loop.
- Runtime catches at the MQTT-client boundary, marks self as "disconnected", pauses all publishes (queuing them to `_out_queue` up to 256), attempts reconnect with exp backoff (1s, 2s, 4s, 8s, 16s, 30s, ...).
- On reconnect: re-subscribe all topics; drain `_out_queue`.
- If reconnect fails for `reconnect_give_up_s` (default 120s): raise `ConnectionError`, exit 4. Glia restarts the container.

### B.11 Session storage

- Mosquitto persists sessions (`clean_session=false`) so a restarted region receives QoS 1 messages queued during its downtime.
- Session expiry: 1 hour. A region down longer than that loses queued messages. This is intentional — a dead-for-an-hour region should not receive old messages on revival.
- Retained topics are delivered immediately on reconnect regardless of session state.

### B.12 Envelope enrichment

When a handler publishes a message that was caused by another message (reply, derivative, triggered action), it SHOULD propagate `correlation_id`:

```python
# inside a handler
async def handle(envelope, ctx):
    # ... produce a response ...
    await ctx.publish(
        topic="hive/cognitive/prefrontal/plan",
        content_type="text/plain",
        data="...",
        correlation_id=envelope.correlation_id or envelope.id,  # start new chain if none
    )
```

The `correlation_id` lets the trace tool (H.4) reconstruct multi-hop chains.

### B.13 Principles honored in Section B

- **P-II** (nervous system): every signal is an MQTT message.
- **P-IV** (modality isolation): ACLs block cross-modal hardware access at the broker.
- **P-XVI** (signal types): retained-flag rules implement modulator semantics; broadcast rules implement rhythm semantics.
- **P-XII** (auditability): envelope `id` + `correlation_id` enable full trace reconstruction.

### B.14 Failure modes catalog

| Mode | Detected by | Handling |
|---|---|---|
| Malformed envelope JSON | consumer `from_json` | Publish metacog `poison_message`, drop |
| Schema violation | consumer validator | Publish metacog `poison_message`, drop |
| ACL rejection on SUBSCRIBE | `mqtt_client.subscribe` | Log WARN, continue without that topic |
| ACL rejection on PUBLISH | broker returns reason | Publish metacog `acl_rejected`, drop |
| Unknown content_type | consumer | Publish metacog `poison_message`, drop |
| Wrong source_region | consumer | Publish metacog (`source_spoof`), drop |
| Broker unreachable | reconnect loop | Exponential backoff, eventual exit 4 |
| Broker restart | client reconnects | Resume queued; retained topics re-flow |
| LWT published (dead region) | glia subscriber | Attempt restart per E.4 |
| Oversized message (> 1 MB) | broker | Reject; publisher gets MqttError |
| Queue overflow at producer | `_out_queue.put_nowait` | Drop message, log ERROR, publish metacog `backpressure` |

---

## Section C — LLM adapter (LiteLLM integration)

The LLM adapter is the shared interface between regions and any LLM provider. Principle XI commits Hive to provider-agnosticism via LiteLLM. This section specifies the adapter API, per-region configuration, capability enforcement, token accounting, retry policy, and prompt caching.

### C.1 Module layout

```
region_template/
├── llm_adapter.py          # LlmAdapter class, the public interface
├── llm_providers.py        # Provider-specific helper functions (thin)
├── llm_cache.py            # Prompt-cache control (provider-dependent)
├── token_ledger.py         # Per-region and global token accounting
└── llm_errors.py           # Wraps LiteLLM errors into Hive taxonomy
```

### C.2 Design posture

- Regions **never import LiteLLM directly**. They call `ctx.llm.complete(...)`. This is the only approved LLM entry point.
- The adapter is a thin wrapper around LiteLLM; we do not reimplement retry, routing, or streaming.
- Capability enforcement lives in the adapter — a region without `vision: true` cannot submit image parts; a region without `tool_use: advanced` cannot submit tool definitions.
- Token ledger is in-adapter so that every call is counted without handler cooperation.

### C.3 Public API

```python
# region_template/llm_adapter.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from .types import LifecyclePhase
from .capability import requires_capability


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str | list[ContentPart]
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ContentPart:
    type: Literal["text", "image", "audio"]
    data: Any  # text: str; image: bytes or URL dict; audio: bytes ref


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema


@dataclass(frozen=True)
class CompletionRequest:
    messages: Sequence[Message]
    tools: Sequence[Tool] = ()
    max_tokens: int = 2048
    temperature: float = 0.7
    top_p: float = 1.0
    stop: Sequence[str] = ()
    stream: bool = False
    cache_strategy: Literal["none", "system", "system_and_messages"] = "system"
    purpose: str = "general"  # tagged in logs and ledger for analysis


@dataclass(frozen=True)
class CompletionResult:
    text: str
    tool_calls: list[ToolCall]
    finish_reason: Literal["stop", "length", "tool_calls", "content_filter", "error"]
    usage: TokenUsage
    model: str
    cached_prefix_tokens: int  # 0 if no cache hit
    elapsed_ms: int
    raw: dict[str, Any]  # provider-specific response for diagnostics


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


class LlmAdapter:
    """Public interface used by handlers via ctx.llm."""

    def __init__(
        self,
        config: RegionConfig,
        capability_profile: CapabilityProfile,
        ledger: TokenLedger,
    ) -> None: ...

    async def complete(self, req: CompletionRequest) -> CompletionResult:
        """Run an LLM call. Enforces capability, records usage.

        Raises:
          LlmError: on non-retryable provider errors, budget exceeded,
                    or exhausted retries.
          CapabilityDenied: if the request requires a capability this
                    region has not declared (vision, tool_use:advanced).
        """

    async def stream(self, req: CompletionRequest) -> AsyncIterator[StreamChunk]:
        """Streamed variant. Only callable if request.stream=True."""

    def estimate_tokens(self, messages: Sequence[Message]) -> int:
        """Cheap token estimate. Used for budget pre-checks."""
```

### C.4 Per-region configuration

Each region's `config.yaml` declares its LLM choice:

```yaml
# regions/<name>/config.yaml
name: auditory_cortex
llm:
  provider: anthropic
  model: claude-sonnet-4-6
  params:
    temperature: 0.3
    max_tokens: 4096
  budgets:
    per_call_max_tokens: 4096       # hard cap per single call
    per_hour_input_tokens: 500_000  # soft cap; warns at 80%, fails at 100%
    per_hour_output_tokens: 100_000
    per_day_cost_usd: 20            # optional; pulled from LiteLLM cost table
  retry:
    max_attempts: 3
    initial_backoff_s: 1
    max_backoff_s: 10
  caching:
    strategy: system_and_messages   # none | system | system_and_messages
    ttl_hint_s: 300                 # Anthropic 5-min cache
```

Provider-specific fields travel through `params`. LiteLLM normalizes.

### C.5 Call flow

```
Handler                  LlmAdapter                  TokenLedger           LiteLLM               Provider
   │  complete(req) ────────►│                              │                    │                    │
   │                         │ verify capability()          │                    │                    │
   │                         │ estimate tokens()            │                    │                    │
   │                         │ reserve(est) ─────────────►  │                    │                    │
   │                         │◄────────── ok/over_budget    │                    │                    │
   │                         │ attach cache_control         │                    │                    │
   │                         │ call_litellm() ──────────────────────────────►    │                    │
   │                         │                              │                    │ acompletion()─────►│
   │                         │                              │                    │◄─────── response ──│
   │                         │◄──────────────── response ────────────────────────│                    │
   │                         │ record actual ─────────────► │                    │                    │
   │                         │ build CompletionResult       │                    │                    │
   │  ◄─────── result ───────│                              │                    │                    │
```

#### C.5.1 Capability check

Applied by decorator:

```python
class LlmAdapter:
    async def complete(self, req: CompletionRequest) -> CompletionResult:
        self._verify_capabilities(req)
        ...

    def _verify_capabilities(self, req: CompletionRequest) -> None:
        if any(
            isinstance(c, ContentPart) and c.type == "image"
            for m in req.messages for c in _parts(m)
        ):
            if not self._caps.vision:
                raise CapabilityDenied("vision")

        if req.tools:
            need = "advanced" if len(req.tools) > 3 else "basic"
            if self._caps.tool_use not in _at_least(need):
                raise CapabilityDenied(f"tool_use:{need}")

        if req.stream and not self._caps.stream:
            raise CapabilityDenied("stream")
```

`CapabilityDenied` is caught at the handler dispatch layer → metacog error `capability_denied`.

#### C.5.2 Budget pre-reservation

Token ledger (`token_ledger.py`) tracks usage rolling windows. `reserve()` adds an estimate to a "reserved" bucket; `record(actual)` replaces it with the real number.

```python
class TokenLedger:
    def reserve(self, estimate: int) -> ReservationHandle: ...
    def record(self, handle: ReservationHandle, actual: TokenUsage) -> None: ...
    def over_budget(self, window: Literal["per_hour", "per_day"]) -> bool: ...
```

If `over_budget("per_hour")`: raise `LlmError("over_budget")` immediately (no provider call). Handler dispatch converts to metacog `llm_over_budget` and INSULA reads the resulting publication when updating interoception.

The ledger also publishes a metric every 60 seconds:

- `hive/system/metrics/tokens` (retained, from GLIA aggregating across regions; each region reports its numbers to glia via `hive/system/region_stats/<name>` — E.9)

### C.6 Prompt caching strategy

Caching is provider-dependent. At v0 we support:

- **Anthropic**: native prompt caching via `cache_control` on messages. 5-minute TTL. Minimum 1024 tokens to cache.
- **OpenAI**: automatic prefix caching since GPT-4-Turbo. No client action needed.
- **Ollama / local**: KV-cache reuse is automatic when you keep the same conversation.

The `cache_strategy` field in `CompletionRequest` controls the Anthropic-specific behavior:

| Strategy | Effect |
|---|---|
| `none` | No `cache_control` set anywhere. |
| `system` (default) | `cache_control: {"type": "ephemeral"}` on the last content part of the system message only. Good for rarely-changing prompts. |
| `system_and_messages` | Cache markers on system + last two user messages. Good for long-running conversations where recent turns repeat. |

The adapter inserts these markers transparently; handlers do not manage cache directly.

**Starter prompts are cache-friendly.** They are stable for the region's lifetime between sleeps. Putting cache markers around the static prompt prefix yields ~90% input-token savings in typical handler calls.

#### C.6.1 Cache hit telemetry

`CompletionResult.cached_prefix_tokens` exposes the cache read. The ledger records both cache-read (billed cheaper) and cache-write tokens separately. Observability (Section H) surfaces cache hit rate per region.

### C.7 Retry policy

Retryable errors (re-request after backoff):

- `RateLimitError` (HTTP 429)
- `APIConnectionError` (network)
- `ServiceUnavailableError` (HTTP 503)
- `InternalServerError` (HTTP 500)

Non-retryable errors (fail fast):

- `AuthenticationError` (bad API key — operator issue)
- `BadRequestError` (400 — request is malformed; retrying will not help)
- `ContextWindowExceededError` (messages too long)
- `ContentPolicyError` (blocked by provider moderation)

Backoff: exponential, jitter ±25%, cap at `max_backoff_s`. `max_attempts=3` default.

```python
async def _call_with_retry(self, req: CompletionRequest) -> dict:
    attempts = 0
    while True:
        attempts += 1
        try:
            return await litellm.acompletion(...)
        except litellm.RateLimitError as e:
            if attempts >= self._retry_cfg.max_attempts:
                raise LlmError("rate_limit_exhausted", retryable=False, cause=e)
            await asyncio.sleep(self._backoff(attempts))
        except litellm.APIConnectionError as e:
            ...
        except litellm.BadRequestError as e:
            raise LlmError("bad_request", retryable=False, cause=e)
        ...
```

### C.8 Failure surfacing

The adapter never suppresses a failure silently. On terminal failure:

1. Publish `hive/metacognition/error/detected` with `kind="llm_failure"` and `detail=<reason>`.
2. Raise `LlmError` to the handler; handler decides whether to retry with different params, fall back to a cheaper model, or give up.

Fallback tier is **not automatic** at v0. A handler that wants fallback implements it explicitly:

```python
try:
    result = await ctx.llm.complete(req)
except LlmError as e:
    if e.kind == "context_window_exceeded":
        # Summarize STM then retry
        ...
    raise
```

Principle XIV (chaos): not every error is worth masking. Silent fallbacks hide behavior.

### C.9 Provider selection map

LiteLLM provider strings (non-exhaustive) supported at v0:

| `provider` | Notes |
|---|---|
| `anthropic` | Anthropic API direct |
| `bedrock` | AWS Bedrock (Claude, Mistral, Titan, etc.) |
| `openai` | OpenAI API |
| `azure` | Azure OpenAI |
| `google` | Vertex AI, Gemini |
| `ollama` | Local model via Ollama HTTP |
| `vllm` | Self-hosted vLLM OpenAI-compatible endpoint |
| `groq` | Groq (fast cheap llama) |

Model strings follow LiteLLM conventions. Config snippet:

```yaml
# Running local Llama on Ollama
llm:
  provider: ollama
  model: ollama/llama3.3:70b
  params:
    api_base: http://ollama:11434
```

### C.10 Env / secrets

API keys live in env vars (never in `config.yaml`). The standard names LiteLLM already reads:

- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `AZURE_API_KEY`, `AZURE_API_BASE`
- `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` + `AWS_REGION_NAME`
- `GOOGLE_APPLICATION_CREDENTIALS`
- `GROQ_API_KEY`
- `OLLAMA_API_BASE`

At bootstrap, the adapter verifies the required env var for the chosen provider exists. Missing → `ConfigError` on bootstrap (exit 2).

Secrets propagation in Docker:

- `docker-compose.yaml` pulls from a `.env` file on the host.
- Regions receive only the env vars relevant to their provider (Compose `environment:` allow-list — but at v0 we pass them all; hardening deferred to post-v0).

### C.11 Token ledger details

```python
@dataclass
class RollingWindow:
    window_s: int
    samples: deque[tuple[float, int]]  # (ts, tokens)

    def add(self, tokens: int, ts: float = time.time()) -> None: ...
    def sum(self, now: float = time.time()) -> int: ...  # prunes old


class TokenLedger:
    def __init__(self, budgets: Budgets) -> None:
        self._budgets = budgets
        self._hourly_in = RollingWindow(3600)
        self._hourly_out = RollingWindow(3600)
        self._daily_cost_usd = RollingWindow(86400)
        self._reservations: dict[str, int] = {}

    def reserve(self, estimate: int) -> str:
        h = uuid.uuid4().hex
        self._reservations[h] = estimate
        return h

    def record(self, h: str, usage: TokenUsage, cost_usd: float) -> None:
        self._reservations.pop(h, None)
        now = time.time()
        self._hourly_in.add(usage.input_tokens - usage.cache_read_tokens, now)
        self._hourly_out.add(usage.output_tokens, now)
        self._daily_cost_usd.add(cost_usd * 1_000_000, now)  # micro-USD for int math

    def effective_usage(self) -> EffectiveUsage:
        reserved_in = sum(self._reservations.values())
        return EffectiveUsage(
            input_hour=self._hourly_in.sum() + reserved_in,
            output_hour=self._hourly_out.sum(),
            cost_day_usd=self._daily_cost_usd.sum() / 1_000_000,
        )

    def over_budget(self) -> str | None:
        u = self.effective_usage()
        if u.input_hour > self._budgets.per_hour_input_tokens:
            return "per_hour_input"
        if u.output_hour > self._budgets.per_hour_output_tokens:
            return "per_hour_output"
        if u.cost_day_usd > self._budgets.per_day_cost_usd:
            return "per_day_cost"
        return None
```

**Soft warning** is raised at 80% of any cap — the adapter logs at WARN and publishes metacog `llm_over_budget` with `context.stage="warning"`. Hard rejection at 100%.

### C.12 Global budget aggregation

Each region's ledger publishes its current usage to `hive/system/region_stats/<region>` every 60 seconds. Glia aggregates into the retained `hive/system/metrics/tokens`:

```json
{
  "aggregated_input_tokens_hour": 1_820_000,
  "aggregated_output_tokens_hour": 310_000,
  "aggregated_cost_usd_day": 41.20,
  "per_region": {
    "prefrontal_cortex": {"input_hour": 820_000, "output_hour": 120_000, ...},
    "auditory_cortex": {"input_hour": 120_000, ...},
    ...
  }
}
```

The insula (interoception region) subscribes to this and publishes `hive/interoception/token_budget` after its own processing.

### C.13 Streaming

Streaming is supported for handlers that opt in (e.g., broca may stream speech output for low latency).

- `CompletionRequest.stream=True` → use `LlmAdapter.stream()` instead of `complete()`.
- `stream()` yields `StreamChunk` objects with `{delta_text, tool_delta, finish_reason}`.
- Token accounting for streaming: the adapter accumulates output tokens chunk-by-chunk and records on terminal chunk.
- A region must declare `capabilities.stream: true` in config (default false) to use streaming.

### C.14 LiteLLM config file

For per-region router settings beyond env, `region_template/litellm.config.yaml` (bundled in the image) captures:

```yaml
model_list:
  - model_name: claude-opus
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      max_tokens: 4096
  - model_name: claude-haiku
    litellm_params:
      model: anthropic/claude-haiku-4-6-20260401
  - model_name: llama-local
    litellm_params:
      model: ollama/llama3.3:70b
      api_base: os.environ/OLLAMA_API_BASE

litellm_settings:
  drop_params: true            # silently drop unsupported per-provider fields
  max_budget: null             # per-region budget is authoritative
  set_verbose: false
  telemetry: false             # Hive does its own telemetry
```

Region config's `llm.model` is either a bare provider/model string OR the name of a router entry here. The adapter resolves both.

### C.15 Principles honored in Section C

- **P-X** (capability honesty): adapter refuses calls that exceed declared capability.
- **P-XI** (LLM-agnostic substrate): LiteLLM integration is the substrate; no handler codes to a provider API.
- **P-XII** (every change committed): token-ledger state is **not** committed (it's ephemeral usage); but cost-relevant decisions (model changes) are.
- **P-XIV** (chaos): no silent fallbacks; failures surface to ACC.

### C.16 Failure modes catalog

| Mode | Detected | Handling |
|---|---|---|
| Unknown provider | bootstrap config validator | `ConfigError`; exit 2 |
| Missing API key | bootstrap adapter init | `ConfigError`; exit 2 |
| Rate limit (retryable) | adapter | Exponential backoff, retry, surface on exhaustion |
| Context window exceeded | provider 400 | `LlmError`; handler responsibility to shrink |
| Content policy block | provider 400 | `LlmError`; surface to metacog; handler may retry with different phrasing |
| Over budget (soft) | ledger | Log WARN; publish metacog warning; call proceeds |
| Over budget (hard) | ledger | `LlmError`; no call; metacog error |
| Streaming disconnect | adapter | Surface as `LlmError("stream_truncated")` |
| Malformed tool-use response | adapter parser | `LlmError("malformed_tool_call")`; no retry |
| Capability mismatch | `_verify_capabilities` | `CapabilityDenied`; metacog error |

---

## Section D — Memory system

Memory is private to its owning region (P-V). Cross-region access happens only via MQTT query/response. This section specifies STM, LTM, consolidation, per-region git integration, and the query protocol.

### D.1 Memory taxonomy

| Layer | Lives in | Written during | Shape | Authority |
|---|---|---|---|---|
| **STM** (short-term) | `regions/<name>/memory/stm.json` | WAKE or SLEEP | Single JSON object: typed dict | Region only |
| **LTM** (long-term) | `regions/<name>/memory/ltm/*.md` | SLEEP only | Markdown files; append-only per filename | Region only |
| **Index** | `regions/<name>/memory/index.json` | SLEEP only | Lightweight term-postings map for LTM retrieval | Region only |
| **Git history** | `regions/<name>/.git/` | SLEEP only (excepts STM snapshot) | Commits on every self-modification cycle | Region only |

No region reads another region's filesystem. The filesystem sandbox (Docker bind mount) makes cross-region reads impossible in practice.

### D.2 STM — short-term memory

STM holds working state: in-flight conversations, recent goals, scratch notes, partially formed thoughts.

#### D.2.1 Schema

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hive.local/schemas/stm/v1.json",
  "type": "object",
  "required": ["schema_version", "region", "updated_at", "slots"],
  "additionalProperties": false,
  "properties": {
    "schema_version": {"type": "integer", "const": 1},
    "region": {"type": "string"},
    "updated_at": {"type": "string", "format": "date-time"},
    "slots": {
      "type": "object",
      "patternProperties": {
        "^[a-z][a-z0-9_]{0,63}$": {
          "type": "object",
          "required": ["value", "written_at", "origin"],
          "properties": {
            "value": {},
            "written_at": {"type": "string", "format": "date-time"},
            "origin": {
              "type": "object",
              "properties": {
                "topic": {"type": "string"},
                "envelope_id": {"type": "string"},
                "correlation_id": {"type": "string"}
              }
            },
            "ttl_s": {"type": ["integer", "null"], "minimum": 1},
            "tags": {"type": "array", "items": {"type": "string"}}
          }
        }
      }
    },
    "recent_events": {
      "type": "array",
      "description": "Ring buffer of recent envelope summaries. Capped length.",
      "items": {
        "type": "object",
        "properties": {
          "envelope_id": {"type": "string"},
          "topic": {"type": "string"},
          "ts": {"type": "string", "format": "date-time"},
          "summary": {"type": "string", "maxLength": 500}
        }
      }
    }
  }
}
```

Regions mostly interact with `slots` (structured key/value) and `recent_events` (ring buffer).

#### D.2.2 Python API

```python
# region_template/memory.py
class MemoryStore:
    async def write_stm(self, key: str, value: Any,
                        origin: OriginRef | None = None,
                        ttl_s: int | None = None,
                        tags: list[str] = ()) -> None: ...

    async def read_stm(self, key: str) -> StmSlot | None: ...

    async def list_stm(self, tag: str | None = None) -> list[StmSlot]: ...

    async def delete_stm(self, key: str) -> bool: ...

    async def record_event(self, envelope: Envelope, summary: str) -> None:
        """Append to recent_events ring buffer."""

    async def stm_size_bytes(self) -> int: ...
```

Atomicity: every STM write uses atomic write-rename (`stm.json.tmp` → `stm.json`). Concurrent writes in a region are serialized by an `asyncio.Lock` held by the `MemoryStore`.

#### D.2.3 TTL handling

Slots with `ttl_s` are pruned lazily: `read_stm` returns None for expired slots; a background coroutine sweeps every 60s and deletes them to prevent unbounded growth.

#### D.2.4 STM size caps

`stm_max_bytes` (config, default 256 KB) is checked after every write. On overflow:

1. If the ring buffer `recent_events` is over half the budget, trim oldest 50% of events.
2. Else raise `StmOverflow`. The dispatcher in the runtime catches this and schedules a sleep trigger within 10s.

### D.3 LTM — long-term memory

LTM is a flat directory of Markdown files. Each file is append-only by convention; actual writes use `write_ltm(filename, content)` which prepends a dated H2 section.

#### D.3.1 File layout

```
regions/<name>/memory/
├── stm.json
├── index.json
└── ltm/
    ├── core/                          # Autobiographical anchors
    │   ├── identity.md               # Who I am, how I formed
    │   ├── relationships.md          # Known entities, faces, voices
    │   └── lessons.md                # Durable learnings
    ├── episodes/                      # Temporal episodes
    │   ├── 2026-04-19T001.md        # One episode per significant event
    │   └── 2026-04-19T002.md
    ├── knowledge/                     # Semantic: facts, patterns
    │   └── <topic>.md
    └── procedural/                    # How-to notes (motor, broca)
        └── <skill>.md
```

Regions partition by convention; a region may simplify (e.g., `amygdala` has no `procedural/`).

#### D.3.2 Markdown structure

Each file uses a strict header + sections:

```markdown
---
topic: sunset_paintings
tags: [painting, visual, art]
created_at: 2026-04-15T10:30:00Z
updated_at: 2026-04-19T14:12:00Z
importance: 0.7
emotional_tag: positive
---

## 2026-04-19T14:12

Painted a second sunset today. User commented on the warmth of the orange.
Serotonin was elevated (0.75). Cross-referenced with 2026-04-15T10:30 episode.

## 2026-04-15T10:30

Initial sunset painting. Dopamine spiked at user's response.
```

YAML front-matter is authoritative for indexing. Sections are free-form Markdown.

#### D.3.3 LTM write API

```python
class MemoryStore:
    async def write_ltm(
        self,
        path: str,           # e.g. "episodes/2026-04-19T001.md"
        content: str,        # text block (no front-matter; that's auto-managed)
        metadata: LtmMetadata,
        reason: str,         # commit message component
    ) -> LtmWriteResult:
        """Create or append to an LTM file. Atomic. Called from SleepCoordinator."""

    async def query_ltm(self, q: MemoryQuery) -> list[MemoryHit]:
        """Search own LTM. Returns hits ranked by relevance * recency * importance."""
```

Only called during SLEEP. The capability decorator `@sleep_only` is applied.

#### D.3.4 Importance score

Each LTM entry gets an importance score (0.0–1.0):

- Explicit hint from `emotional_tag` (positive/alarming → boost).
- Modulator levels at time of write (high NE → elevated importance).
- Number of cross-references to the same entry over time.
- Manual override by the region's sleep logic.

The score influences retention (low-importance entries are candidates for pruning during `consolidate_ltm`) and ranking during query.

### D.4 Index

`index.json` is a lightweight postings list that speeds LTM retrieval. Rebuilt during each sleep's consolidation step.

```json
{
  "schema_version": 1,
  "built_at": "2026-04-19T14:12:00Z",
  "documents": {
    "episodes/2026-04-19T001.md": {
      "tags": ["painting", "visual"],
      "topic": "sunset_paintings",
      "created_at": "2026-04-15T10:30:00Z",
      "updated_at": "2026-04-19T14:12:00Z",
      "importance": 0.7,
      "term_counts": {"sunset": 3, "orange": 2, "warmth": 1}
    }
  },
  "postings": {
    "sunset": ["episodes/2026-04-19T001.md", "episodes/2026-04-15T002.md"],
    ...
  }
}
```

Retrieval is a plain BM25 over term_counts + tag-match boost + recency decay. No external search engine at v0. A region with few LTM files (day-1 Hive) skips the index entirely.

Post-v0 may add embedding-based retrieval. The API is stable enough that an embedding implementation swaps in without handler changes.

### D.5 Consolidation protocol (sleep)

Memory consolidation is the primary work of sleep. It is **local to each region** (P-V). There is no hippocampus-coordinated global consolidation — each region consolidates itself.

#### D.5.1 High-level phases (per sleep)

```
SLEEP enter
   │
   ▼
1. Snapshot STM                  ──►  keep a read-only copy in memory
   │
   ▼
2. Review recent_events          ──►  LLM: "what mattered today?"
   │
   ▼
3. Integrate to LTM              ──►  create/append episode files
   │
   ▼
4. Prune STM                     ──►  drop ephemeral slots; keep working state
   │
   ▼
5. Rebuild index                 ──►  one-shot scan of ltm/
   │
   ▼
6. Revise prompt (optional)      ──►  if regional logic decides
   │
   ▼
7. Modify handlers (optional)    ──►  if self_modify + change needed
   │
   ▼
8. Commit                        ──►  one git commit per sleep
   │
   ▼
9. Decide: restart or resume wake
```

Steps 6 and 7 are per-region decisions. A passive region (amygdala at v0 has minimal procedural learning) might skip 6 and 7 entirely; an active one (motor_cortex, hippocampus) frequently runs them.

#### D.5.2 The `SleepCoordinator` class

```python
# region_template/sleep.py
class SleepCoordinator:
    def __init__(self, runtime: RegionRuntime) -> None: ...

    async def run(self) -> SleepResult:
        """Execute the full sleep pipeline. Called by runtime after grant."""
        snap = await self._snapshot_stm()
        review = await self._review_events(snap)
        await self._integrate_to_ltm(review)
        await self._prune_stm()
        await self._rebuild_index()
        proposals = await self._propose_self_mods(review)
        if proposals.appendix_entry:
            await self._append_appendix(proposals.appendix_entry)
        if proposals.handler_edits:
            ok = await self._apply_handler_edits(proposals.handler_edits)
            if not ok:
                return SleepResult(status="no_change", restart=False)
        commit = await self._commit()
        if proposals.needs_restart:
            return SleepResult(status="committed_restart", restart=True, sha=commit.sha)
        return SleepResult(status="committed_in_place", restart=False, sha=commit.sha)

    async def abort(self, reason: str) -> None:
        """Emergency exit from sleep. Rolls back uncommitted changes.

        Called when cortisol spikes above `sleep_abort_cortisol_threshold`
        during sleep (default 0.85) — biology analog to nightmare/wakeup."""
```

Each `_*` method is overridable by a region via a `sleep_hook.py` handler file, but defaults are implemented in `region_template`.

#### D.5.3 Review events — LLM prompt scaffold

A default review prompt (stored in `region_template/sleep_prompts/default_review.md`):

```
You are <region> during sleep consolidation.

Here is a summary of your recent wake period:
- stm snapshot: {stm_summary}
- recent events: {recent_events}
- current modulators: {modulator_snapshot}
- current self state: {self_state}

Identify:
1. Events worth storing as episodes in LTM (1-5 candidates)
2. Patterns worth promoting to knowledge/ or procedural/ notes
3. Any STM slots that should be cleared
4. An appendix entry to append to your rolling evolution log (optional) — only the new section body; the framework prepends the timestamped H2 heading. prompt.md itself is immutable DNA and is never rewritten (see A.7.1).

Return a JSON object matching this schema: {review_schema}
```

Regions override this file during sleep if they want different review heuristics. Default works for v0.

#### D.5.4 Handler revision

Handler edits during sleep go through `edit_handlers`. Before commit:

1. Run `ast.parse` on every `.py` under `handlers/` → syntax gate.
2. Run `python -m compileall -q handlers/` → bytecode gate.
3. Run any tests under `handlers/tests/` (optional at v0) → test gate.

If any gate fails:

- Revert all handler writes (`git checkout -- handlers/`).
- Mark the edit `skipped` in the sleep result.
- Log WARN. The next sleep may try again.

#### D.5.5 Pre-restart verification

When `SleepResult.restart == True`, the runtime runs one final verification before publishing `hive/system/restart/request`:

```python
def _pre_restart_verify(self) -> None:
    subprocess.check_call(["python", "-c",
        "from region_template.runtime import RegionRuntime; "
        "from pathlib import Path; "
        "RegionRuntime(Path('/hive/region/config.yaml'))"])
```

This dry-imports the runtime with the new handler code without connecting to MQTT. If the import raises, the region does NOT request restart and instead reverts the handler commit:

```bash
git revert --no-edit HEAD
git commit --amend -m "revert: handler edit failed pre-restart verify"
```

This prevents the restart loop described in J.3.

#### D.5.6 Sleep commit message template

```
sleep: <trigger> @ <ts>

- events reviewed: <n>
- ltm writes: <n>  files: <list>
- stm pruned: <k> slots
- appendix: <+N section(s)|unchanged>
- handlers: <changed|unchanged>
- restart required: <yes|no>

reason: <free-form from review step>
```

Trigger values as enumerated in A.4.5. The message is machine-parseable for audit tooling (H.4).

#### D.5.7 Per-region git integration

Each region's directory is its own git repository. Operations are mechanical:

```python
# region_template/git_tools.py
class GitTools:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._ensure_repo()

    def _ensure_repo(self) -> None:
        if not (self._root / ".git").exists():
            run(["git", "init"], cwd=self._root)
            run(["git", "config", "user.name", self._region_name()], cwd=self._root)
            run(["git", "config", "user.email",
                 f"{self._region_name()}@hive.local"], cwd=self._root)
            run(["git", "add", "."], cwd=self._root)
            run(["git", "commit", "-m", "initial region state"], cwd=self._root)

    def status_clean(self) -> bool: ...

    def commit_all(self, message: str) -> CommitResult:
        run(["git", "add", "-A"], cwd=self._root)
        run(["git", "commit", "-m", message], cwd=self._root)
        sha = run(["git", "rev-parse", "HEAD"], cwd=self._root).stdout.strip()
        return CommitResult(sha=sha, ...)

    def revert_to(self, sha: str) -> None:
        run(["git", "reset", "--hard", sha], cwd=self._root)

    def last_good_sha(self) -> str:
        """Returns HEAD^ (parent of current commit). Used by glia rollback."""
```

All operations are local (no remotes). The region's git never pushes anywhere. Glia can tar up region directories for backup, but the authoritative history lives in `.git`.

### D.6 Cross-region memory queries

A region that needs another region's memory publishes to `hive/cognitive/<target>/query` (inbox per B.4). The target region decides whether and how to respond.

#### D.6.1 Query envelope

```json
{
  "envelope_version": 1,
  "id": "…",
  "source_region": "prefrontal_cortex",
  "topic": "hive/cognitive/hippocampus/query",
  "reply_to": "hive/cognitive/prefrontal_cortex/response",
  "correlation_id": "…",
  "attention_hint": 0.7,
  "payload": {
    "content_type": "application/hive+memory-query",
    "data": {
      "question": "What did the user say about project X yesterday?",
      "topics": ["user:alex", "project-x"],
      "timeframe_hint": "this_week",
      "max_results": 5
    }
  }
}
```

The target (here hippocampus) subscribes to `hive/cognitive/hippocampus/query`, its handler runs an LLM-assisted search over its own LTM, and publishes a response envelope to the `reply_to` topic.

#### D.6.2 Response envelope

```json
{
  "envelope_version": 1,
  "id": "…",
  "source_region": "hippocampus",
  "topic": "hive/cognitive/prefrontal_cortex/response",
  "correlation_id": "…",
  "payload": {
    "content_type": "application/hive+memory-response",
    "data": {
      "query_id": "…",
      "results": [
        {
          "source": "episodes/2026-04-18T003.md",
          "content": "Alex mentioned project X is behind schedule; asked Hive to summarize risks",
          "confidence": 0.82,
          "emotional_tag": "neutral"
        }
      ]
    }
  }
}
```

#### D.6.3 Query handler pattern

A target region handles memory queries in a single handler, e.g. `regions/hippocampus/handlers/memory_query.py`:

```python
SUBSCRIPTIONS = ["hive/cognitive/hippocampus/query"]
TIMEOUT_S = 30

async def handle(envelope, ctx):
    q = MemoryQuery(**envelope.payload["data"])
    # 1. Run BM25 over ltm/ for initial candidates
    candidates = await ctx.memory.query_ltm(q)
    # 2. Optionally LLM-rerank
    top = await _rerank_with_llm(ctx, q, candidates)
    # 3. Publish response
    await ctx.publish(
        topic=envelope.reply_to,
        correlation_id=envelope.correlation_id or envelope.id,
        content_type="application/hive+memory-response",
        data={"query_id": envelope.id, "results": top},
    )
```

#### D.6.4 Refusal and partial responses

A region MAY refuse. It publishes a response with `results: []` and, optionally, a metacog note explaining why (e.g., "insufficient confidence"). This respects P-III (sovereignty): memory queries are requests, not demands.

#### D.6.5 Timeout & reliability

The querier sets a handler-level timeout (default 30s) and does not retry at v0. If no response arrives, the querier may proceed without memory context and note the gap to ACC via metacog error.

### D.7 Hippocampus — the special case

Hippocampus is not privileged for memory access (it does not read other regions' files). It is privileged by convention: it is the region with the richest LTM schema, dedicated encoding/retrieval handlers, and a **cross-region memory broker role**.

Hippocampus's unique responsibilities:

- Answers `hive/cognitive/hippocampus/query` from any region.
- Receives `hive/cognitive/hippocampus/encoding_hint` (from amygdala for emotional tagging; from mPFC for core-memory flagging).
- Holds the autobiographical index's canonical copy; mPFC publishes a pointer at `hive/self/autobiographical_index`.

Other regions keep their own LTM for region-specific procedural/knowledge memory. Cross-region semantic memory lives in hippocampus.

### D.8 Memory rollback

Git is the rollback substrate (P-XII). Scenarios:

| Scenario | Rollback mechanism |
|---|---|
| Handler edit breaks boot | Glia `git reset --hard HEAD~1` in region dir (E.5) |
| Prompt edit leads to erratic behavior (days later) | ACC may publish `hive/system/codechange/proposed` requesting a revert; handled by human or another region |
| STM corruption | `stm.json.corrupt.<ts>` backup + empty restart (A.4.2 step 9) |
| LTM entry wrong | Region's own sleep cycle edits/appends; history preserved in git |

Corrupt git repo is treated as fatal (exit 3; manual recovery required).

### D.9 Principles honored in Section D

- **P-V** (private memory): Docker mount isolates; cross-region is MQTT-only.
- **P-XII** (every change committed): sleep commits; LTM append-only; git is per-region.
- **P-IX** (wake/sleep): LTM writes and index rebuilds are sleep-only.
- **P-XIII** (emergence): hippocampus is conventional, not privileged; any region may refuse queries.

### D.10 Failure modes catalog

| Mode | Detected | Handling |
|---|---|---|
| STM corruption | JSON parse error on boot | Move to `stm.json.corrupt.<ts>`; start empty; log WARN |
| STM overflow | `write_stm` size check | `StmOverflow`; force sleep trigger |
| LTM file collision | Write to existing non-append-mode file | Raise `LtmPathConflict`; sleep retries with suffix |
| Index rebuild failure | parse error in ltm/ file | Log WARN, skip file; retry next sleep |
| Query timeout | querier handler | Proceed without memory; metacog error |
| Memory-response schema violation | consumer validator | Drop + metacog `poison_message` |
| Git commit empty | `git commit` default refuses empty commits → non-zero exit → `GitError` | Sleep logs "no changes" and exits sleep cleanly |
| Git lock contention | concurrent writes (impossible within one region) | N/A by design |
| Handler edit ast.parse fails | sleep pipeline | Revert; next sleep retries |

---

## Section E — Glia (infrastructure)

Glia is the dumb infrastructure layer. It runs processes, watches heartbeats, mediates ACL changes, rolls back failed boots, and publishes system metrics. **It never deliberates.** Its only judgment is mechanical: exit codes, schema validity, threshold comparisons.

### E.1 Module layout

```
glia/
├── Dockerfile
├── pyproject.toml
├── __main__.py                    # Entrypoint
├── supervisor.py                  # Main loop: launcher + monitor + ACL + rollback + metrics
├── launcher.py                    # start / stop / restart region containers
├── heartbeat_monitor.py           # Liveness map, LWT handler, restart trigger
├── acl_manager.py                 # Render templates, apply SIGHUP, verify
├── rollback.py                    # Per-region git revert on boot failure
├── registry.py                    # Read regions/ directory, parse configs
├── bridges/                       # Hardware-to-MQTT glue (non-cognitive)
│   ├── mic_bridge.py
│   ├── speaker_bridge.py
│   ├── camera_bridge.py
│   ├── motor_bridge.py
│   ├── input_text_bridge.py       # host stdin → hive/sensory/input/text
│   └── rhythm_generator.py        # gamma/beta/theta ticks
├── metrics.py                     # Aggregates per-region stats; publishes hive/system/metrics/*
└── codechange_executor.py         # Executes approved region_template/ changes
```

### E.2 Process model

Glia runs as a **single container** (`hive-glia:v0`) with:

- **Read-write** mount `./regions/:/hive/regions/:rw` — glia writes during rollback (`git revert`/`reset --hard` in E.5) and during spawn scaffolding (E.11). Day-to-day reads (list regions, parse config) dominate; writes are rare and sleep-triggered. Despite RW access, glia NEVER edits handler code, prompts, or memory — the filesystem sandbox is enforced by **convention and code review**, not by the mount mode (since `git reset` inherently needs write access).
- Read-write mount `./region_template/:/hive/region_template/:rw` **only when processing an approved code-change** (mounted via a short-lived sidecar, see E.10).
- Read-write mount `/var/run/docker.sock:/var/run/docker.sock` so it can manage containers on the host.
- Read-write mount `./bus/:/hive/bus/:rw` so it can regenerate `acl.conf`.

Internally, glia's `supervisor.py` runs a single asyncio loop that owns:

1. MQTT client for system-level topics (heartbeats, sleep/spawn/restart requests, metacog errors).
2. Docker client (sync calls via `asyncio.to_thread()`).
3. A set of background coroutines (launcher, monitor, ACL manager, rollback watcher, metrics aggregator, bridges).

### E.3 Heartbeat monitoring

Glia subscribes to `hive/system/heartbeat/+` at QoS 1. It builds an in-memory liveness map:

```python
@dataclass
class RegionLiveness:
    region: str
    last_heartbeat_ts: float
    last_status: str
    consecutive_misses: int
    queue_depth: int
    uptime_s: int
    build_sha: str | None
```

Rules:

- On heartbeat received, reset `consecutive_misses=0`, update fields.
- On LWT received (`status="dead"` with retained=true), mark region dead; trigger restart policy.
- Every 5s, sweep the map: if `time.time() - last_heartbeat_ts > heartbeat_miss_threshold_s` (default 30s), increment `consecutive_misses`.
- If `consecutive_misses > max_misses` (default 3, i.e., ~90s since last heartbeat), treat as dead regardless of LWT (broker can miss LWTs if the broker itself was down). Trigger restart.

### E.4 Restart policy

Regions emit exit codes through Docker. Glia observes via `docker.events.listen()` (streaming) and via periodic `docker ps --filter status=exited`.

| Exit code | Meaning | Glia response |
|---|---|---|
| 0 | Planned restart (self-modification) | Restart once, with a 2s pause (let broker process LWT). |
| 1 | Unexpected runtime error | Exponential backoff: 5s, 15s, 45s, 90s, 180s; cap at 300s |
| 2 | Config error | Do NOT restart. Publish metacog error `region_config_error` with region name. Requires human intervention. |
| 3 | Git error | Do NOT restart. Publish metacog `region_git_error`. |
| 4 | MQTT connection failure | Backoff as for code 1 (probably transient). |
| 137 | SIGKILL | Backoff as for code 1. |
| 139 | Segfault | Log critical; backoff as code 1; if recurs within 1 hour, stop restarting. |

Crash-loop protection: if a region has crashed **5 times within 10 minutes**, glia stops auto-restart, publishes metacog `crash_loop` with the region name, and waits for a human (or ACC-approved code change) to intervene. An operator CLI (`hive restart <name> --force`) resets the counter.

### E.5 Rollback on boot failure

If a region exits with code 2 or 3 (or dies within 30s of a planned restart following self-modification), glia runs rollback:

```python
async def rollback_region(region: str, reason: str) -> RollbackResult:
    root = Path(f"/hive/regions/{region}")
    if not (root / ".git").exists():
        return RollbackResult(ok=False, reason="no git")

    # 1. Get previous commit
    prev = run(["git", "rev-parse", "HEAD~1"], cwd=root).stdout.strip()
    if not prev:
        return RollbackResult(ok=False, reason="no parent commit")

    # 2. Revert
    run(["git", "revert", "--no-edit", "HEAD"], cwd=root)

    # 3. Relaunch
    launcher.start(region)

    # 4. Publish event
    await publish("hive/metacognition/error/detected", {
        "kind": "region_rollback",
        "detail": f"rolled back to {prev}",
        "context": {"region": region, "reason": reason, "reverted_sha": prev},
    })
    return RollbackResult(ok=True, reverted_to=prev)
```

Rollback is **mechanism only**. Glia does not evaluate whether the code was actually bad; it trusts that an exit 2/3 after a commit from the region itself is a strong signal.

If rollback fails (revert conflicts, no parent, second crash after rollback), glia stops and publishes metacog `rollback_failed`. The region stays down until manual intervention.

### E.6 ACL manager

`acl_manager.py` renders `bus/acl_templates/*.j2` → `bus/acl.conf` and signals mosquitto to reload.

```python
class AclManager:
    async def render_and_apply(self) -> ApplyResult:
        # 1. Enumerate existing regions
        regions = self._registry.list_regions()

        # 2. Render each template
        base = self._render("_base.j2")
        per_region = [self._render(f"{r}.j2", region=r) for r in regions]

        # 3. Consistency check (see B.6.1)
        conflict = self._check_conflicts(per_region)
        if conflict:
            return ApplyResult(ok=False, reason=f"acl conflict: {conflict}")

        # 4. Atomic write
        tmp = BUS_DIR / "acl.conf.tmp"
        tmp.write_text(base + "\n" + "\n".join(per_region))
        tmp.replace(BUS_DIR / "acl.conf")

        # 5. Signal mosquitto container
        docker.containers.get("mosquitto").kill(signal="SIGHUP")

        # 6. Verify (best-effort)
        await asyncio.sleep(0.5)
        # Check broker log for "reloading config" line; if not present,
        # still treat as applied (logs are best-effort)

        return ApplyResult(ok=True)
```

Triggered by:

- Bootstrap (initial apply).
- New region spawn (E.8).
- Approved code change that modifies `bus/acl_templates/` (E.10).
- Operator CLI `hive acl reload`.

### E.7 Rhythm generator

A built-in bridge publishes rhythm topics. Runs as a task inside glia.

```python
# glia/bridges/rhythm_generator.py
async def run(mqtt: MqttClient):
    gamma_hz, beta_hz, theta_hz = 40, 20, 6
    # Each rhythm runs its own loop; sleeps correspond to its period
    await asyncio.gather(
        _emit("hive/rhythm/gamma", gamma_hz, mqtt),
        _emit("hive/rhythm/beta", beta_hz, mqtt),
        _emit("hive/rhythm/theta", theta_hz, mqtt),
    )

async def _emit(topic: str, hz: float, mqtt: MqttClient):
    beat = 0
    period = 1.0 / hz
    while True:
        envelope = _build_rhythm_envelope(topic, beat, hz)
        await mqtt.publish(topic, envelope, qos=0, retain=False)
        beat += 1
        await asyncio.sleep(period)
```

Jitter: up to ±10% allowed by the biology analog (neural rhythms jitter). A tight-loop scheduler is not required.

### E.8 Hardware bridges

Glia hosts bridges that translate raw hardware to MQTT topics. These are **not cognitive** — they are dumb I/O pumps, bundled with glia because they need host device access (audio device, camera device, etc.). Each bridge runs as a task and only operates on hardware assigned to it.

| Bridge | Direction | Hardware | MQTT topic |
|---|---|---|---|
| `mic_bridge` | in | `/dev/snd` (PulseAudio) | `hive/hardware/mic` (raw bytes) |
| `camera_bridge` | in | `/dev/video0` | `hive/hardware/camera` (raw bytes) |
| `speaker_bridge` | out | `/dev/snd` | subscribes `hive/hardware/speaker` |
| `motor_bridge` | out | stubbed at v0 | subscribes `hive/hardware/motor` |
| `input_text_bridge` | in | TCP socket on localhost:7777 | `hive/sensory/input/text` |

Bridges are enabled/disabled via `glia/config.yaml`. If a bridge can't initialize (no device), it logs WARN and is disabled; it doesn't crash glia.

At v0, only `input_text_bridge` is enabled by default. Audio/camera require a deliberate enablement flag (operator opts in). Biology anchor: Hive without sensory hardware enabled is a sensorily-blind teenager; still fully functional internally.

### E.9 System metrics aggregation

Glia publishes three retained topics:

- `hive/system/metrics/compute` — CPU and memory pressure from `docker stats` on region containers
- `hive/system/metrics/tokens` — aggregated from per-region `hive/system/region_stats/<region>`
- `hive/system/metrics/region_health` — derived from the liveness map

Cadence: every 30s. Payloads are JSON; schemas are in `shared/metric_schemas.json`.

`compute` payload:

```json
{
  "total_cpu_pct": 45.3,
  "total_mem_mb": 8192,
  "per_region": {
    "prefrontal_cortex": {"cpu_pct": 12.1, "mem_mb": 512},
    ...
  }
}
```

`region_health` payload:

```json
{
  "summary": "healthy",
  "regions_up": 14,
  "regions_degraded": 0,
  "regions_down": 0,
  "per_region": {
    "prefrontal_cortex": {"status": "wake", "consecutive_misses": 0, "uptime_s": 12345},
    ...
  }
}
```

These feed insula, which re-interprets them as interoceptive state (`hive/interoception/*`).

### E.10 Code-change executor

When ACC approves a `region_template/` change (the DNA), glia executes it. This is the ONE code path that writes to `region_template/` at runtime.

Flow (from `hive/system/codechange/approved`):

```json
{
  "change_id": "uuid",
  "patch": "<unified diff>",
  "approver_region": "anterior_cingulate",
  "human_cosigner": "alice@example.com",  # required at v0
  "justification": "…",
  "affected_regions": ["*"]  # or specific regions
}
```

1. **Verify cosignature**: at v0, requires a matching `HIVE_HUMAN_COSIGN_PUBKEY` env-configured signature on the patch. Missing or invalid → reject, publish metacog `codechange_rejected`.
2. **Write patch** to `region_template/` via a short-lived privileged container:
   ```bash
   docker run --rm -v ./region_template/:/hive/region_template/:rw \
     hive-codechange-executor:v0 --patch /tmp/change.patch
   ```
3. **Rebuild** `hive-region:v0` image with `docker build`.
4. **Rolling restart** of affected regions: for each region, `docker stop` → `docker run` with new image. Exponential stagger to avoid total Hive downtime.
5. **Observe**: if any region fails to boot with the new image, halt the rollout, roll back the image tag (`hive-region:v0` → `hive-region:v0-prev`), restart the partially-rolled regions on the old tag. Publish `hive/metacognition/error/detected` kind `codechange_rollback`.

Human cosigning is **non-negotiable at v0** (P-XV: bootstrap minimally, then let go — but the DNA layer is the last thing we let go of).

### E.11 Spawn executor

On `hive/system/spawn/request` from ACC:

1. **Schema check**: validate payload against `application/hive+spawn-request`.
2. **Name uniqueness**: reject if `regions/<name>` exists or name is on the reserved-region list.
3. **Scaffold** `regions/<name>/`:
   - `config.yaml` from the payload (writes through `config_loader.serialize`).
   - `prompt.md` = `starter_prompt`.
   - `subscriptions.yaml` from `initial_subscriptions`.
   - `handlers/__init__.py` (empty).
   - `memory/stm.json` (empty skeleton) and `memory/ltm/` (empty dir).
   - `git init` + initial commit.
4. **ACL template**: copy `bus/acl_templates/_new_region_stub.j2` to `bus/acl_templates/<name>.j2`, parameterized by `initial_subscriptions`.
5. **Apply ACL** via `AclManager.render_and_apply()`.
6. **Launch** via `launcher.start(name)`.
7. On success, publish `hive/system/spawn/complete` with the name, the originating `correlation_id` (copied from the spawn/request envelope), and the initial commit sha. Glia ALSO keeps a rolling 100-event log of recent spawn outcomes in memory; on any `hive/system/spawn/query` inbound from a region (including ACC after wake-from-sleep), glia responds with the matching record if found. This covers the race where a SLEEP-phase-blocking caller (A.7.7) missed the original complete.
8. On any failure, clean up (`rm -rf regions/<name>`, revert ACL template), publish `hive/system/spawn/failed` with the reason and correlation_id.

Spawn is mechanical. Glia never evaluates whether the spawn is a good idea — that was ACC's job.

### E.12 Operator CLI

Glia exposes a CLI via a thin companion container for operator use:

```
hive up                          # start broker + glia + all regions
hive down                        # graceful shutdown
hive status                      # region liveness + health
hive logs <region>               # stream logs
hive restart <region> [--force]  # restart, reset crash counter
hive sleep <region>              # force a sleep request
hive kill <region>               # docker kill
hive acl reload                  # re-render and apply ACL
hive spawn <config.yaml>         # operator-invoked spawn (bypasses ACC; for bootstrap only)
hive shell <region>              # exec bash in a running region container
hive inspect <region>            # print config, subs, last heartbeat, etc.
```

The CLI is implemented as `hive` (binary symlinked into the operator's PATH) → calls glia's JSON API on a Unix domain socket mounted at `/var/run/hive.sock`. This is the only interface that lets an operator directly control Hive.

Bootstrap-only commands (`spawn` without ACC approval) emit a WARN log and a metacog note; they are meant for the initial brain-up and for recovering from pathological states.

### E.13 Graceful shutdown

On `docker stop glia` or operator `hive down`:

1. Publish `hive/broadcast/shutdown` with `grace_s` (default 30).
2. Watch heartbeats; regions should transition to SHUTDOWN and publish their last heartbeat.
3. After `grace_s`, `docker stop` any region still running.
4. `docker stop mosquitto` last (so region LWTs have a chance to flow before broker dies).
5. Glia itself exits last.

If any region disobeys (stays WAKE after broadcast), glia logs WARN and proceeds anyway.

### E.14 Glia's own resilience

- Glia restarts itself via Docker's `--restart unless-stopped` policy.
- On restart, glia re-reads the liveness map from scratch (nothing persisted). First 60s are a "silent observation" window where glia does not trigger any restarts — it's waiting for heartbeats to repopulate.
- Glia's state (crash counters, reservations) is in-memory only. Loss across restarts is acceptable; recovery is mechanical.

### E.15 Principles honored in Section E

- **P-I** (biology): glia is modeled directly on glial cells — support only, never cognition.
- **P-XIII** (emergence over orchestration): glia publishes metrics; regions respond. Glia never commands.
- **P-XV** (bootstrap then let go): glia owns bootstrap; once running, regions self-evolve. Glia executes approved changes but doesn't author them.

### E.16 Failure modes catalog

| Mode | Detected | Handling |
|---|---|---|
| Region crash-loop | restart counter | Stop auto-restart; metacog `crash_loop` |
| Region boot failure after self-mod | exit code within 30s of restart | Git revert, relaunch |
| ACL template syntax error | jinja2 render | Abort apply; previous acl.conf stays; metacog `acl_render_failure` |
| ACL conflict | `_check_conflicts` | Abort apply; metacog `acl_conflict` |
| mosquitto container down | docker poll | Restart mosquitto container; while down, all Hive is paused |
| Docker daemon unreachable | docker SDK | Glia exits 1; `--restart` brings it back |
| Spawn request for existing region | name check | `hive/system/spawn/failed` with reason `name_taken` |
| Spawn request violates schema | validator | `spawn/failed`, reason `schema_invalid` |
| Code-change patch fails to apply | short-lived executor container | `codechange/failed`; log patch; no retry |
| Code-change image build failure | docker build exit | Rollback to prev image tag; metacog `codechange_failed` |
| Bridge device unavailable | on init | Disable bridge; log WARN; Hive boots without it |
| LWT received but container still running | `docker inspect` | Ignore LWT; trust docker state (rare race) |

---

## Section F — Configuration

Configuration lives in three places and is loaded in this precedence order (highest wins):

1. Environment variables (operator/secrets)
2. `regions/<name>/config.yaml` (region-specific)
3. `region_template/defaults.yaml` (framework defaults)

### F.1 `config.yaml` — canonical per-region config

```yaml
# regions/prefrontal_cortex/config.yaml
name: prefrontal_cortex
role: "executive function: planning, reasoning, speech intent generation"
schema_version: 1

# LLM choice (see C.4)
llm:
  provider: anthropic
  model: claude-sonnet-4-6
  params:
    temperature: 0.5
    max_tokens: 4096
  budgets:
    per_call_max_tokens: 4096
    per_hour_input_tokens: 2_000_000
    per_hour_output_tokens: 300_000
    per_day_cost_usd: 50
  retry:
    max_attempts: 3
    initial_backoff_s: 1
    max_backoff_s: 10
  caching:
    strategy: system_and_messages
    ttl_hint_s: 300

# Capability profile — framework-enforced (P-X)
capabilities:
  self_modify: true        # may edit own prompt/handlers during sleep
  tool_use: advanced       # may declare tools in LLM calls
  vision: false            # may submit image content parts
  audio: false             # may submit audio content parts
  stream: true             # may use streaming
  can_spawn: false         # may call spawn_new_region (only ACC at v0)
  modalities: [text]       # coarse modality assertion

# Lifecycle tuning
lifecycle:
  heartbeat_interval_s: 5
  sleep_quiet_window_s: 300
  sleep_max_wake_s: 3600
  sleep_max_queue_depth: 5
  sleep_abort_cortisol_threshold: 0.85
  shutdown_timeout_s: 30

# Memory tuning
memory:
  stm_max_bytes: 262144           # 256 KB
  recent_events_max: 200
  ltm_query_default_k: 5
  index_rebuild_interval_sleeps: 10  # rebuild every N sleeps

# Handler dispatch
dispatch:
  handler_concurrency_limit: 8
  handler_default_timeout_s: 30
  backpressure_warn_s: 10

# MQTT
mqtt:
  broker_host: broker           # docker-compose service name
  broker_port: 1883
  keepalive_s: 30
  max_connect_attempts: 10
  reconnect_give_up_s: 120
  password_env: MQTT_PASSWORD_PREFRONTAL_CORTEX   # read from env

# Logging / telemetry
logging:
  level: info
  structured: true
  include_envelope_ids: true
```

### F.2 JSON Schema for `config.yaml`

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://hive.local/schemas/region-config/v1.json",
  "title": "Hive Region Config",
  "type": "object",
  "required": ["name", "role", "schema_version", "llm", "capabilities"],
  "properties": {
    "schema_version": {"type": "integer", "const": 1},
    "name": {"type": "string", "pattern": "^[a-z][a-z0-9_]{2,30}$"},
    "role": {"type": "string", "minLength": 10, "maxLength": 500},
    "llm": {
      "type": "object",
      "required": ["provider", "model"],
      "properties": {
        "provider": {"type": "string"},
        "model": {"type": "string"},
        "params": {"type": "object"},
        "budgets": {
          "type": "object",
          "properties": {
            "per_call_max_tokens": {"type": "integer", "minimum": 128},
            "per_hour_input_tokens": {"type": "integer", "minimum": 1000},
            "per_hour_output_tokens": {"type": "integer", "minimum": 1000},
            "per_day_cost_usd": {"type": "number", "minimum": 0}
          }
        },
        "retry": {
          "type": "object",
          "properties": {
            "max_attempts": {"type": "integer", "minimum": 1, "maximum": 10},
            "initial_backoff_s": {"type": "number", "minimum": 0.1},
            "max_backoff_s": {"type": "number", "minimum": 1}
          }
        },
        "caching": {
          "type": "object",
          "properties": {
            "strategy": {"enum": ["none", "system", "system_and_messages"]},
            "ttl_hint_s": {"type": "integer", "minimum": 10}
          }
        }
      }
    },
    "capabilities": {
      "type": "object",
      "required": ["self_modify", "tool_use", "vision", "audio"],
      "properties": {
        "self_modify": {"type": "boolean"},
        "tool_use": {"enum": ["none", "basic", "advanced"]},
        "vision": {"type": "boolean"},
        "audio": {"type": "boolean"},
        "stream": {"type": "boolean"},
        "can_spawn": {"type": "boolean"},
        "modalities": {
          "type": "array",
          "items": {"enum": ["text", "vision", "audio", "motor", "smell", "haptic"]}
        }
      }
    },
    "lifecycle": {
      "type": "object",
      "properties": {
        "heartbeat_interval_s": {"type": "integer", "minimum": 1, "maximum": 60},
        "sleep_quiet_window_s": {"type": "integer", "minimum": 30},
        "sleep_max_wake_s": {"type": "integer", "minimum": 60},
        "sleep_max_queue_depth": {"type": "integer", "minimum": 0},
        "sleep_abort_cortisol_threshold": {"type": "number", "minimum": 0, "maximum": 1},
        "shutdown_timeout_s": {"type": "integer", "minimum": 5}
      }
    },
    "memory": {
      "type": "object",
      "properties": {
        "stm_max_bytes": {"type": "integer", "minimum": 1024, "maximum": 1048576},
        "recent_events_max": {"type": "integer", "minimum": 10},
        "ltm_query_default_k": {"type": "integer", "minimum": 1, "maximum": 50},
        "index_rebuild_interval_sleeps": {"type": "integer", "minimum": 1}
      }
    },
    "dispatch": {
      "type": "object",
      "properties": {
        "handler_concurrency_limit": {"type": "integer", "minimum": 1, "maximum": 64},
        "handler_default_timeout_s": {"type": "number", "minimum": 1},
        "backpressure_warn_s": {"type": "integer", "minimum": 1}
      }
    },
    "mqtt": {
      "type": "object",
      "properties": {
        "broker_host": {"type": "string"},
        "broker_port": {"type": "integer", "minimum": 1, "maximum": 65535},
        "keepalive_s": {"type": "integer", "minimum": 5},
        "max_connect_attempts": {"type": "integer", "minimum": 1},
        "reconnect_give_up_s": {"type": "integer", "minimum": 10},
        "password_env": {"type": "string"}
      }
    },
    "logging": {
      "type": "object",
      "properties": {
        "level": {"enum": ["debug", "info", "warn", "error"]},
        "structured": {"type": "boolean"},
        "include_envelope_ids": {"type": "boolean"}
      }
    }
  },
  "additionalProperties": false
}
```

### F.3 Regional anatomy registry

`glia/registry.py` maintains the canonical list of region *types* and their default capabilities. New regions MUST be added here (by ACC spawn or human code change) before they can launch.

```yaml
# glia/regions_registry.yaml
schema_version: 1
regions:
  # ---- Cognitive ----
  medial_prefrontal_cortex:
    layer: cognitive
    required_capabilities: [self_modify, tool_use]
    default_capabilities: {self_modify: true, tool_use: advanced, vision: false, audio: false}
    singleton: true

  prefrontal_cortex:
    layer: cognitive
    required_capabilities: [self_modify, tool_use]
    default_capabilities: {self_modify: true, tool_use: advanced}
    singleton: true

  anterior_cingulate:
    layer: cognitive
    required_capabilities: [self_modify, tool_use, can_spawn]
    default_capabilities: {self_modify: true, tool_use: advanced, can_spawn: true}
    singleton: true

  hippocampus:
    layer: cognitive
    required_capabilities: [self_modify, tool_use]
    default_capabilities: {self_modify: true, tool_use: advanced}
    singleton: true

  thalamus:
    layer: cognitive
    required_capabilities: [tool_use]
    default_capabilities: {self_modify: true, tool_use: basic}
    singleton: true

  association_cortex:
    layer: cognitive
    required_capabilities: [self_modify]
    default_capabilities: {self_modify: true, tool_use: basic}
    singleton: true

  # ---- Sensory ----
  visual_cortex:
    layer: sensory
    required_capabilities: [self_modify, vision]
    default_capabilities: {self_modify: true, tool_use: basic, vision: true}
    singleton: true

  auditory_cortex:
    layer: sensory
    required_capabilities: [self_modify, audio]
    default_capabilities: {self_modify: true, tool_use: basic, audio: true}
    singleton: true

  # ---- Motor ----
  motor_cortex:
    layer: motor
    required_capabilities: [self_modify, tool_use]
    default_capabilities: {self_modify: true, tool_use: advanced}
    singleton: true

  broca_area:
    layer: motor
    required_capabilities: [self_modify, tool_use]
    default_capabilities: {self_modify: true, tool_use: advanced, stream: true}
    singleton: true

  # ---- Modulatory ----
  amygdala:
    layer: modulatory
    required_capabilities: []
    default_capabilities: {self_modify: true, tool_use: basic}
    singleton: true

  vta:
    layer: modulatory
    required_capabilities: []
    default_capabilities: {self_modify: true, tool_use: basic}
    singleton: true

  # ---- Homeostatic ----
  insula:
    layer: homeostatic
    required_capabilities: []
    default_capabilities: {self_modify: true, tool_use: basic}
    singleton: true

  basal_ganglia:
    layer: homeostatic
    required_capabilities: [self_modify]
    default_capabilities: {self_modify: true, tool_use: basic}
    singleton: true

  # ---- Post-v0 slots (publisher-reserved via ACL, no container yet) ----
  raphe_nuclei:
    layer: modulatory
    singleton: true
    reserved: true

  locus_coeruleus:
    layer: modulatory
    singleton: true
    reserved: true

  hypothalamus:
    layer: modulatory
    singleton: true
    reserved: true

  basal_forebrain:
    layer: modulatory
    singleton: true
    reserved: true

  cerebellum:
    layer: motor
    singleton: true
    reserved: true
```

`singleton: true` means only one container may exist with this name. `reserved: true` means the registry acknowledges the type but no container runs at v0.

### F.4 Environment variables

#### Required on host

```
# Anthropic key (or equivalent for other providers)
ANTHROPIC_API_KEY=sk-ant-...

# MQTT auth
# One per region; glia loads from .env and passes to containers
MQTT_PASSWORD_PREFRONTAL_CORTEX=...
MQTT_PASSWORD_MEDIAL_PREFRONTAL_CORTEX=...
MQTT_PASSWORD_ANTERIOR_CINGULATE=...
# ... one per region

# Cosign pubkey for code changes (human approval)
HIVE_HUMAN_COSIGN_PUBKEY=ssh-ed25519 AAAA...

# Deployment mode
HIVE_ENV=dev    # dev | prod
HIVE_ROOT=/opt/hive
```

#### Injected into region containers

Compose `.env` → compose sets these on the container:

```
HIVE_REGION=prefrontal_cortex
HIVE_BROKER_HOST=broker
ANTHROPIC_API_KEY=...
MQTT_PASSWORD=...   # region-specific, renamed by compose
```

#### Secret rotation

v0 commits to manual rotation. A change to a password requires:

1. Regenerate `bus/passwd` via `mosquitto_passwd`.
2. Update host `.env`.
3. `hive restart <region>` (or whole stack).

Automated rotation deferred to post-v0.

### F.5 Config loader

```python
# region_template/config_loader.py
from ruamel.yaml import YAML
from jsonschema import Draft202012Validator

def load_config(path: Path) -> RegionConfig:
    yaml = YAML(typ="safe")
    data = yaml.load(path.read_text())

    # Merge over defaults
    defaults = _load_defaults()
    merged = _deep_merge(defaults, data)

    # Validate
    _VALIDATOR.validate(merged)

    # Env interpolation
    merged = _interp_env(merged)   # resolves password_env etc.

    return RegionConfig(**merged)
```

Env interpolation pattern: a value like `${ENV:VAR_NAME}` is replaced with the env var's value. Missing env → `ConfigError`.

### F.6 Framework defaults

`region_template/defaults.yaml` ships with the image and is overlaid by per-region config:

```yaml
schema_version: 1
role: "unnamed region"
llm:
  params: {temperature: 0.7, max_tokens: 2048}
  budgets:
    per_call_max_tokens: 2048
    per_hour_input_tokens: 500_000
    per_hour_output_tokens: 100_000
    per_day_cost_usd: 10
  retry: {max_attempts: 3, initial_backoff_s: 1, max_backoff_s: 10}
  caching: {strategy: system, ttl_hint_s: 300}

capabilities:
  self_modify: false
  tool_use: none
  vision: false
  audio: false
  stream: false
  can_spawn: false
  modalities: [text]

lifecycle:
  heartbeat_interval_s: 5
  sleep_quiet_window_s: 300
  sleep_max_wake_s: 3600
  sleep_max_queue_depth: 5
  sleep_abort_cortisol_threshold: 0.85
  shutdown_timeout_s: 30

memory:
  stm_max_bytes: 262144
  recent_events_max: 200
  ltm_query_default_k: 5
  index_rebuild_interval_sleeps: 10

dispatch:
  handler_concurrency_limit: 8
  handler_default_timeout_s: 30
  backpressure_warn_s: 10

mqtt:
  broker_host: broker
  broker_port: 1883
  keepalive_s: 30
  max_connect_attempts: 10
  reconnect_give_up_s: 120

logging:
  level: info
  structured: true
  include_envelope_ids: true
```

Defaults are **deny-by-default** for capabilities (P-X). A region must explicitly declare what it may do.

### F.7 Config self-edits during sleep

Regions do not directly edit `config.yaml`. Its fields are set at design time. If a region's logic requires a config change (e.g., raise `handler_concurrency_limit`), the region publishes `hive/system/codechange/proposed` with a `config.yaml` patch. This preserves the invariant that runtime capabilities are not self-promoted.

### F.8 `subscriptions.yaml`

```yaml
# regions/<name>/subscriptions.yaml
schema_version: 1
subscriptions:
  - topic: hive/cognitive/prefrontal_cortex/request
    qos: 1
    description: "Directed requests to me"
  - topic: hive/sensory/auditory/text
    qos: 1
    description: "Heard speech"
  - topic: hive/self/#
    qos: 1
    description: "Global identity state"
  - topic: hive/modulator/#
    qos: 0
    description: "Ambient chemical fields"
```

The runtime uses this at bootstrap step 6. The region MAY self-edit this file during sleep (A.7.2).

### F.9 Principles honored in Section F

- **P-X** (capability honesty): framework defaults are deny-by-default; config declares every capability.
- **P-VI** (DNA/expression): `config.yaml` is in `regions/<name>/` → gene expression; `defaults.yaml` ships with DNA.
- **P-VII** (one template): defaults + schema are shared; differentiation is per-region file.

### F.10 Failure modes catalog

| Mode | Detected | Handling |
|---|---|---|
| Schema violation | validator at bootstrap | Exit 2; metacog `region_config_error` |
| Env var missing | loader | Exit 2 |
| Registry name mismatch | glia at bootstrap | Refuse to launch region; metacog `unknown_region_type` |
| Singleton violation | glia launcher | Refuse second launch; metacog `singleton_violation` |
| Default/override deep-merge ambiguity | loader | `_deep_merge` recurses into nested dicts; region scalars/lists fully replace defaults at the leaf (see §F.5) |

---

## Section G — Bootstrap

### G.1 The `hive up` sequence

`hive up` (operator CLI, E.12) runs:

```
1. Validate .env file on host
   ├─ required keys present?
   └─ any malformed? → abort with errors

2. docker compose up -d broker
   ├─ pull mosquitto image if needed
   ├─ create hive_net network if missing
   └─ wait for broker healthcheck (max 60s)
      healthcheck: mosquitto_sub -t '$SYS/#' -C 1 -W 5

3. Generate bus/acl.conf from templates
   ├─ enumerate regions/ directory
   ├─ render _base.j2 + per-region templates
   ├─ consistency check (B.6.1)
   └─ write acl.conf; SIGHUP broker

4. Generate bus/passwd from host env
   ├─ read MQTT_PASSWORD_* env vars
   ├─ run mosquitto_passwd to create entries
   └─ atomic replace bus/passwd

5. docker compose up -d glia
   ├─ glia comes up; reads regions_registry.yaml
   ├─ glia connects to broker
   └─ wait for glia ready (publishes hive/system/metrics/region_health)

6. Launch regions in dependency order
   ├─ mPFC first (others need hive/self/* retained values)
   ├─ insula second (others want interoception)
   ├─ amygdala + vta (modulators needed by most regions)
   ├─ thalamus, ACC, hippocampus, basal_ganglia (central cognitive)
   ├─ PFC, association_cortex (depend on upstream)
   ├─ broca_area, motor_cortex
   └─ visual_cortex, auditory_cortex last (sensory; may be disabled)

7. Verify: wait for all regions to publish first wake heartbeat
   ├─ timeout per region: 60s
   └─ if any fails → report, leave Hive in partial state

8. Print status; return
```

Dependency order in step 6 is enforced by `launcher.py` reading `regions_registry.yaml` for `depends_on` (not shown above for brevity; present in the real registry). Step 7's "all up" is the bootstrap success condition.

### G.2 First-boot behavior

On the very first `hive up`:

- `regions/<name>/.git/` doesn't exist → each region runs `git init` and commits its starter files on its first bootstrap.
- `regions/<name>/memory/stm.json` doesn't exist → created as empty skeleton:
  ```json
  {"schema_version": 1, "region": "<name>", "updated_at": "<ts>", "slots": {}, "recent_events": []}
  ```
- `regions/<name>/memory/ltm/` empty → all queries return empty sets.
- mPFC publishes the initial retained self-state from its starter prompt (already covered in D.5 flow and in the mPFC starter prompt).
- Other regions read `hive/self/*` retained values during their own bootstrap step 7.

### G.3 Graceful shutdown

`hive down` is E.13's sequence. Takes ~30-60s.

```
1. hive down
   ├─ publish hive/broadcast/shutdown (30s grace)
   └─ observe heartbeats; wait for each to reach status=shutdown

2. After grace or all-shutdown-observed:
   ├─ docker stop each region (stagger; 1s apart)
   ├─ docker stop glia (last-among-Hive)
   └─ docker stop mosquitto

3. docker compose down
   └─ removes the hive_net network
```

Operator can `hive down --fast` to skip grace (for dev iteration); regions get SIGKILL.

### G.4 Restart semantics

`hive restart <region>`:

- Publish `hive/system/sleep/force` for the region (so it flushes STM).
- Wait up to 30s for it to reach sleep.
- `docker restart <container>`.
- Region bootstraps normally.

`hive restart --all` performs a rolling restart with health gates between regions.

### G.5 Development mode

`hive up --dev` differs from `hive up`:

| Aspect | Normal | `--dev` |
|---|---|---|
| ACL | Full ACLs applied | ACLs disabled (`allow_anonymous true`, no ACL file) |
| Regions launched | All 14 | Only those in `--regions <comma-list>` (or mPFC+ACC+thalamus by default) |
| Hot-reload | Off | On — `watchfiles` observer in each dev region restarts on handler edits |
| Logging | info, JSON | debug, human-readable colored |
| Broker persistence | On | On (retained state persists across restarts) |
| Tools | Same | Operator may `hive exec <region> python -i` to enter region's Python REPL with loaded runtime |

Dev mode requires `HIVE_ENV=dev`. If `HIVE_ENV=prod` is set on the host, `--dev` is rejected with an error.

### G.6 `--no-docker` escape hatch

For debugging the runtime itself without Docker:

```bash
hive up --no-docker --region prefrontal_cortex
```

- Starts a local mosquitto binary (if installed) on `127.0.0.1:1883`.
- Runs `python -m region_template.runtime --config regions/prefrontal_cortex/config.yaml` directly.
- ACLs disabled.
- Glia NOT started — the one region is on its own.

This is for runtime iteration. It does NOT exercise the Docker + glia + ACL paths. Integration tests (Section I) always run in full Docker mode.

### G.7 `docker-compose.yaml` shape

```yaml
# docker-compose.yaml
version: "3.9"
name: hive

networks:
  hive_net:
    driver: bridge

volumes:
  mosquitto_data:
  mosquitto_log:

services:
  broker:
    image: eclipse-mosquitto:2.0.20
    container_name: mosquitto
    ports:
      - "127.0.0.1:1883:1883"  # dev inspection only
    volumes:
      - ./bus/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - ./bus/acl.conf:/mosquitto/config/acl.conf:ro
      - ./bus/passwd:/mosquitto/config/passwd:ro
      - mosquitto_data:/mosquitto/data
      - mosquitto_log:/mosquitto/log
    networks: [hive_net]
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "mosquitto_sub", "-t", "$$SYS/#", "-C", "1", "-W", "5"]
      interval: 10s
      timeout: 5s
      retries: 3

  glia:
    build:
      context: .
      dockerfile: glia/Dockerfile
    image: hive-glia:v0
    container_name: glia
    depends_on:
      broker:
        condition: service_healthy
    environment:
      - HIVE_ENV=${HIVE_ENV:-dev}
      - MQTT_HOST=broker
      - MQTT_PORT=1883
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
    env_file:
      - .env
    volumes:
      - ./regions:/hive/regions:rw
      - ./region_template:/hive/region_template:ro
      - ./shared:/hive/shared:ro
      - ./bus:/hive/bus:rw
      - /var/run/docker.sock:/var/run/docker.sock
    networks: [hive_net]
    restart: unless-stopped

  # NOTE: region containers are launched by glia at runtime, NOT by compose.
  # Compose only provides the broker and the supervisor.
```

Region containers are created by `glia.launcher` with docker SDK calls equivalent to:

```bash
docker run -d \
  --name hive-region-<name> \
  --network hive_net \
  --restart unless-stopped \
  -e HIVE_REGION=<name> \
  -e MQTT_HOST=broker \
  -e MQTT_PASSWORD=${MQTT_PASSWORD_<NAME>} \
  -e ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY} \
  -v ./regions/<name>:/hive/region:rw \
  -v ./region_template:/hive/region_template:ro \
  -v ./shared:/hive/shared:ro \
  --cpus 1.0 \
  --memory 2g \
  --memory-swap 2g \
  --read-only --tmpfs /tmp \
  hive-region:v0
```

Resource caps (`--cpus`, `--memory`) are per-region defaults in the registry; larger cognitive regions may override (post-v0).

### G.8 Principles honored in Section G

- **P-XV** (bootstrap minimally, then let go): `hive up` is the only procedural orchestration; everything after is emergent.
- **P-VII** (one template): all region containers share image.
- **P-VI** (DNA vs expression): volume mounts enforce the boundary (`region_template` RO, `regions/<name>` RW).

### G.9 Failure modes catalog

| Mode | Detected | Handling |
|---|---|---|
| Broker fails to start | compose healthcheck | `hive up` aborts; operator inspects `docker logs mosquitto` |
| Glia fails to start | compose healthcheck / depends_on | Abort; operator inspects `docker logs glia` |
| Region fails first boot | bootstrap step 7 timeout | Report, continue (Hive in partial state); operator decides |
| Missing env var for required region | loader | Region fails exit 2; metacog as config_error |
| .env missing on host | cli validation | Abort with clear message |
| Port 1883 already bound | broker start | Abort; suggest `--broker-port` override |

---

## Section H — Observability

### H.1 Logging

Every region, and glia, use `structlog` configured to emit JSON lines to stdout. Docker collects stdout natively; the operator reads via `docker logs <container>` or aggregates via any standard log pipeline (Loki, Datadog, CloudWatch — out of scope for v0).

#### H.1.1 Canonical log shape

```json
{
  "ts": "2026-04-19T10:30:00.123Z",
  "level": "info",
  "region": "prefrontal_cortex",
  "event": "handler_complete",
  "topic": "hive/sensory/auditory/text",
  "envelope_id": "e7…",
  "correlation_id": "c1…",
  "phase": "wake",
  "handler": "on_speech",
  "elapsed_ms": 842,
  "llm_tokens_in": 1420,
  "llm_tokens_out": 230,
  "msg": "handler on_speech completed"
}
```

`region`, `phase`, `ts`, `level`, `event`, `msg` are always present. Additional context binds dynamically (via `log.bind(...)`).

#### H.1.2 Levels

- `debug` — verbose tracing; off in prod
- `info` — normal lifecycle; default
- `warn` — recoverable anomalies (ACL miss on non-critical topic, slow handler)
- `error` — handler crashes, poison messages, LLM failures

#### H.1.3 PII and secrets

`structlog` config includes a processor that redacts:

- Env var values (pattern match to common names)
- Full envelope payload IF payload `content_type` is `text/plain` and larger than 1 KB (logs `[payload:<len>B]` instead)
- Authorization headers (for any HTTP logs from LiteLLM)

A region's own LLM output goes to logs at `debug` level only. In `info` mode, only metadata (token counts, elapsed time) appears.

#### H.1.4 Log retention

Docker's json-file driver default is unbounded. Operators MUST configure `max-size`/`max-file`. Recommended for v0:

```yaml
# ~/.docker/daemon.json or per-service logging block
logging:
  driver: json-file
  options:
    max-size: "50m"
    max-file: "5"
```

Post-v0 will add a log shipper, but v0 is file-based.

### H.2 Metrics

Each region publishes `hive/system/region_stats/<region>` every 60s. Glia aggregates into `hive/system/metrics/*` (Section E.9).

#### H.2.1 Per-region stats payload

```json
{
  "region": "prefrontal_cortex",
  "ts": "2026-04-19T10:30:00.000Z",
  "uptime_s": 1234,
  "phase": "wake",
  "build_sha": "abc1234",
  "handlers": {"count": 5, "degraded": 0},
  "mqtt": {
    "messages_in_total": 4521,
    "messages_out_total": 2130,
    "subscribed_topics": 12,
    "reconnects": 0
  },
  "llm": {
    "calls_total": 42,
    "cache_hits_total": 35,
    "input_tokens_total": 102340,
    "output_tokens_total": 18200,
    "errors_total": 1,
    "over_budget_events": 0
  },
  "memory": {
    "stm_bytes": 1823,
    "ltm_files": 7,
    "index_terms": 218
  },
  "sleep": {
    "cycles_total": 3,
    "last_sleep_ts": "2026-04-19T09:45:00.000Z",
    "last_commit_sha": "def5678"
  }
}
```

#### H.2.2 Aggregation

Glia's `metrics.py` subscribes to `hive/system/region_stats/+` and rolls up:

- `hive/system/metrics/tokens` (C.12)
- `hive/system/metrics/compute` — augmented with Docker stats per container
- `hive/system/metrics/region_health` — derived from heartbeat liveness map

### H.3 Debug tooling

v0 provides CLI tools under `tools/dbg/`.

| Command | Purpose |
|---|---|
| `hive trace <correlation_id>` | Reconstruct a full message chain from broker logs + region logs. |
| `hive watch modulators` | Subscribes to `hive/modulator/#` and prints colored timeline. |
| `hive watch attention` | Retrieves retained `hive/attention/focus` and watches updates. |
| `hive dump self` | Retrieves all retained `hive/self/*` values. |
| `hive stm <region>` | Reads `regions/<region>/memory/stm.json` directly (via glia's read-only mount). |
| `hive sleep-history <region>` | Lists sleep commits with trigger + summary. |
| `hive inject <topic> <file.json>` | Publishes a crafted envelope (for debugging flow). |
| `hive mock <region>` | Launches a mock region container that subscribes and logs; useful for reproducing cross-region bugs. |

These tools are thin wrappers over `mosquitto_sub` / `mosquitto_pub` + file reads over a glia-provided read-only filesystem socket.

### H.4 Tracing via correlation_id

When a handler publishes a message triggered by another, it SHOULD propagate `correlation_id`. This lets `hive trace` reconstruct chains:

```
corr=c1  2026-04-19T10:30:00.000Z  (external) → hive/sensory/input/text "Hello Hive"
corr=c1  2026-04-19T10:30:00.023Z  thalamus      reads, publishes hive/cognitive/thalamus/attend
corr=c1  2026-04-19T10:30:00.110Z  prefrontal    reads, publishes hive/cognitive/hippocampus/query
corr=c1  2026-04-19T10:30:00.890Z  hippocampus   responds hive/cognitive/prefrontal/response
corr=c1  2026-04-19T10:30:01.210Z  prefrontal    publishes hive/motor/speech/intent
corr=c1  2026-04-19T10:30:01.420Z  broca_area    publishes hive/hardware/speaker (audio)
```

Handlers that forget to propagate lose the chain — tool warns on those gaps.

### H.5 Health endpoints

Regions do NOT expose HTTP health. Liveness is entirely MQTT-driven via heartbeat. Glia is the single "is Hive healthy" query endpoint (CLI `hive status`), which reads its own liveness map.

### H.6 Principles honored in Section H

- **P-XII** (every change committed): trace + log + git gives a fully auditable history.
- **P-XIII** (emergence): observability is read-only — tools never command regions, only observe.
- **P-III** (sovereignty): no health back-channel; a region's honest heartbeat is the only liveness signal.

### H.7 Failure modes catalog

| Mode | Detected | Handling |
|---|---|---|
| Logs flooding disk | Docker's `max-size` | Operator responsibility; v0 documents caps |
| `hive trace` misses events | broker not retaining message history | Tool explicitly states "best effort" |
| Metrics stale (region down) | aggregator timeout 2× stats interval | Aggregator marks region_health as `stale` |

---

## Section I — Testing strategy

v0 tests live in `tests/` at the repo root, plus per-region `regions/<name>/handlers/tests/` for handler-level unit tests.

### I.1 Test taxonomy

| Tier | Runs in | Depends on | Goal |
|---|---|---|---|
| Unit | host Python | mocks | Cover runtime modules in isolation |
| Component | host Python | mocks + an embedded broker | Cover interactions between two modules (e.g., runtime + mqtt_client) |
| Integration | Docker compose | real broker + 2–3 real regions | Cover realistic behavior end-to-end |
| Smoke | Docker compose | broker + full 14 regions | Verify Hive boots & heartbeats |
| Self-mod cycle | Docker compose | a single test region | Verify sleep → commit → restart round-trip |

No test requires byte-identical LLM output (P-XIV). Tests assert **behavior**, not text.

### I.2 Unit tests

Modules under `region_template/` each have unit tests that exercise:

- Contract methods with sample inputs.
- Failure paths (missing capability, phase violation, config error).
- Edge cases (empty STM, zero subscriptions, zero handlers).

LLM calls are mocked via a `FakeLlmAdapter` that returns scripted responses matching the `CompletionResult` shape. MQTT is mocked via a `FakeMqttClient` that records published envelopes and injects receive.

```python
# tests/unit/test_runtime.py
def test_bootstrap_with_missing_env_exits_2(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    runtime = RegionRuntime(_fixture_config(tmp_path))
    with pytest.raises(ConfigError):
        asyncio.run(runtime.bootstrap())
```

### I.3 Component tests

Two-module tests using `testcontainers` to spin up an actual `eclipse-mosquitto` broker on an ephemeral port, then exercise `MqttClient` against it. Each test:

- Starts broker container.
- Starts runtime against real broker.
- Publishes scripted envelopes.
- Asserts consumer observes them, handlers fire, publishes land on expected topics.

LLM still mocked.

### I.4 Integration tests

Composed scenarios with 2–3 real region containers. `tests/integration/compose.test.yaml` defines a minimal test Hive:

- `broker`
- `glia`
- `mpfc` (seeded with fake self-state)
- `prefrontal_cortex`
- `test_harness` — a tiny region type that publishes scripted inputs and asserts outputs

These tests DO use real LLM calls against a cheaper model (`claude-haiku`) unless `HIVE_TEST_OFFLINE=1`, in which case each region's LLM is replaced by a deterministic stub. CI runs offline mode by default; gated integration job runs with real LLM.

Assertions are on **message flow and structure**, not content. For example:

> "After injecting `hive/sensory/input/text` with a greeting, a `hive/motor/speech/intent` message MUST appear within 10s. Its payload MUST validate against `application/hive+motor-intent`."

### I.5 Smoke test

`tests/smoke/boot_all.py` runs `hive up`, waits 120s, asserts:

- All 14 regions report `status=wake`
- Retained `hive/self/*` values present
- At least one message flows (e.g., inject input, observe speech intent)
- `hive down` completes within 60s

Smoke is the canary for wholescale breakage.

### I.6 Self-modification cycle test

`tests/integration/test_self_mod_cycle.py`:

1. Launch one test region with `self_modify: true` and a starter prompt that instructs it to append an appendix entry (and optionally add a handler) during first sleep.
2. Force a sleep via `hive/system/sleep/force`.
3. Wait for `hive/system/restart/request` from that region.
4. Verify:
   - Git log shows new commit with expected message pattern.
   - `memory/appendices/rolling.md` has grown by at least one dated H2 section.
   - `prompt.md` is byte-identical to its post-spawn initial commit (immutable-DNA invariant; any diff here is a regression — see A.7.1).
   - Container restarts cleanly.
   - New `hive/system/heartbeat` arrives with `status=wake`.

This is the canary for the sleep → append-appendix → commit → restart pipeline.

### I.7 What to mock vs. run real

| Layer | Mock in unit/component? | Mock in integration? |
|---|---|---|
| LLM | Yes (`FakeLlmAdapter`) | Real in gated job; stub in default CI |
| MQTT broker | Yes in unit; real in component | Real |
| Docker | Yes in unit; real in integration | Real |
| Git | Real (local tmp dir); cheap | Real |
| Filesystem | Real (tmp dirs) | Real |
| Time / clocks | Real (with short windows) | Real |

Clocks are NEVER mocked. Tests use short windows (e.g., 5s quiet-window) to stay fast, not fake time.

### I.8 Test dependencies

```
tests/
├── conftest.py             # Fixtures (tmp region config, fake adapters)
├── unit/
│   ├── test_runtime.py
│   ├── test_mqtt_client.py
│   ├── test_memory.py
│   ├── test_llm_adapter.py
│   ├── test_sleep.py
│   ├── test_capability.py
│   └── test_envelope.py
├── component/
│   ├── test_mqtt_real_broker.py
│   └── test_sleep_with_broker.py
├── integration/
│   ├── compose.test.yaml
│   ├── test_cross_region_flow.py
│   ├── test_self_mod_cycle.py
│   └── test_acl_enforcement.py
├── smoke/
│   └── boot_all.py
└── fakes/
    ├── llm.py              # FakeLlmAdapter with scripted responses
    └── mqtt.py             # FakeMqttClient with envelope recorder
```

### I.9 CI posture

- Unit + component run on every commit (< 5 min).
- Integration (LLM stubbed) on every PR (< 15 min).
- Integration (real LLM) nightly and on labeled PRs only (cost reasons).
- Smoke nightly.

All use `pytest` + `pytest-asyncio`.

### I.10 Principles honored in Section I

- **P-XIV** (chaos): no determinism-asserting tests; assert structure, not content.
- **P-XIII** (emergence): integration tests exercise multi-region flows, not mocked pipelines.
- **P-I** (biology): self-mod cycle test preserves the wake/sleep/commit/restart rhythm.

### I.11 Failure modes catalog

| Mode | Detected | Handling |
|---|---|---|
| Flaky integration due to LLM nondeterminism | test writes asserting content | Rewrite to assert structure/envelope, not words |
| Broker port conflict in parallel CI | testcontainers ephemeral | Built-in handling |
| LLM rate limits in CI | gated integration | Retry or skip; never commit mocks |
| Test region leaks containers | docker-cleanup hook | Pytest fixture always invokes `docker compose down -v` |

---

## Section J — Safety & recovery

This section consolidates recovery behaviors from Sections A–G, plus adds the cross-cutting cases.

### J.1 Layered defense (from architecture.md §12)

1. **Capability enforcer** — `@requires_capability` in runtime
2. **Filesystem sandbox** — Docker volume mounts
3. **Sleep-only gate** — `@sleep_only` decorator
4. **Git commit** — `commit_changes` before `request_restart`
5. **Glia mechanism check** — schema + capability match, image build on code-change
6. **MQTT ACL** — broker rejects unauthorized pub/sub
7. **Git rollback** — glia reverts on boot failure

Each layer applies to every self-modification. Failure at any layer aborts without reaching the next.

### J.2 Crash scenarios and recovery

| Scenario | Detection | Recovery |
|---|---|---|
| Handler raises | `_dispatch` catches | Log + metacog error; other handlers unaffected |
| Runtime unhandled exception | process dies, non-zero exit | LWT fires; glia restarts per E.4 |
| Container killed (OOM) | exit 137 | Glia restarts with backoff; metacog `oom_kill` note |
| Region can't reach broker | bootstrap step 4 retries | Eventually exit 4; glia backoff |
| Broker down | all regions lose connection | Each retries; glia restarts broker container if exited |
| Host Docker daemon down | glia can't manage containers | Glia's own container exits; host responsibility to restart Docker |
| Power loss mid-sleep | journal lost | On reboot, `hive up` runs; each region finds uncommitted files, `git status` shows dirty; region's bootstrap step 3 runs `git checkout -- .` to clean up |
| Corrupted STM | JSON parse error | Rename to `stm.json.corrupt.<ts>`, start empty (A.4.2 step 9) |
| Corrupted LTM file | index rebuild catches | Skip file; log WARN; region may delete in next sleep |
| Corrupted git repo | `git status` fails | Region exits 3; glia does NOT restart; operator repairs manually |

### J.3 Restart loops

Covered in E.4. Summary:

- ≤ 5 restarts in 10 min → auto-recover with backoff.
- > 5 → stop, metacog `crash_loop`, wait for human.
- Crash-loop specifically **after a sleep self-mod restart** → automatic rollback via E.5.

### J.4 mPFC unreachable

mPFC is a single point of global identity. If it's down:

- Retained `hive/self/*` values persist in broker (if broker is up).
- New regions that boot while mPFC is down read the retained values; they operate with last-known self-state.
- If broker ALSO died and was restarted, retained values are lost until mPFC re-publishes.

Mitigation: every region's framework default includes a **fallback self-state** baked into `region_template/defaults.yaml`:

```yaml
self_fallback:
  identity: "I am Hive. Details unavailable until mPFC reconnects."
  values: ["honest", "careful"]
  personality: "unknown (awaiting mPFC)"
```

Regions use this only if `hive/self/*` is entirely absent after 30s of wake time.

### J.5 Poison-message handling

Covered in B.2.2 and B.14. Summary:

- Envelope JSON parse failure → drop + publish metacog `poison_message`
- Schema violation → drop + metacog
- `source_region` spoof (mismatch with broker-auth username) → drop + metacog `source_spoof`
- Oversized payload → broker rejects at publish

The runtime will NOT throw in the consumer loop on a poison message. Recovery is local to the handler.

### J.6 Rate limiting / cost caps

Covered in C.11 and C.12. Summary:

- Per-region hourly/daily budgets in `config.yaml`
- Soft warning at 80%, hard failure at 100%
- Insula + metacog notify the rest of Hive; behavior should change under load
- Global aggregation in glia allows a future global cap (post-v0 open question)

### J.7 Pre-restart verification

Covered in D.5.5. Summary:

- After sleep edits handlers, before requesting restart, runtime does a dry import of the new runtime
- If the import throws, revert the commit and DO NOT restart
- Glia's rollback (E.5) catches post-restart failures that pre-verify missed

### J.8 Safety of self-spawn

Spawn path (E.11) is mechanical once approved. Approval path (by ACC) is cognitive. Defense against accidental or malicious self-spawn:

- Only `anterior_cingulate` has `can_spawn: true`.
- ACC's starter prompt embeds constraints: duplicate-check, capacity-check, rationale-required.
- Glia checks name uniqueness and reserved-list.
- Spawn failure for any reason publishes `spawn/failed` and leaves no partial state.
- A spawn creates an initial git commit; the new region is auditable from birth.

At v0, ACC's first-year spawns SHOULD be rare (biology anchor: adult neurogenesis is rare). Spec imposes no hard quota but metrics track count.

### J.9 Safety of self-code-change

Code change (DNA edit) at v0 requires a human cosignature (E.10). This is **the** non-negotiable in v0 safety posture (P-XV: bootstrap minimally, then let go — and DNA is the last we let go).

Attack surface:

- Compromise of ACC could approve a malicious patch. Cosign defends against this.
- Compromise of the cosign key is out-of-scope for v0 (standard key hygiene).

### J.10 Resource safety

Per-container resource caps (G.7):

- `--cpus 1.0` default (cognitive regions: 2.0)
- `--memory 2g` default
- `--read-only` on container FS; `/tmp` tmpfs for scratch
- Writable volume limited to `/hive/region/`

A runaway region cannot consume more than its caps, cannot write beyond its volume, cannot spawn child processes in the parent namespace, cannot reach other containers except via broker.

### J.11 Graceful degradation

The system degrades when components are missing:

- Broker down → all regions quiet but internal state preserved; resume on broker restart
- mPFC down → fallback self-state (J.4)
- Hippocampus down → memory queries time out; regions proceed without context; metacog records the outage
- ACC down → no new spawns, no approved code changes; Hive runs otherwise
- Sensory region down → no new perceptions in that modality; cognition continues
- Motor/Broca down → Hive cannot act externally in that modality; internal reasoning continues

No single region crash halts Hive. Broker crash pauses Hive; glia's auto-restart limits paused duration.

### J.12 Principles honored in Section J

- **P-III** (sovereignty): regions crash individually; others keep running.
- **P-XII** (every change committed): rollback is always possible.
- **P-XIV** (chaos): degraded states are acceptable; not every failure is auto-recovered.
- **P-XV** (bootstrap then let go): DNA change requires human cosign.

---

## Section K — Developer ergonomics

### K.1 Running one region locally

For rapid iteration on a single region's handlers:

```bash
# Start broker + glia
hive up --dev --regions mpfc,test_region

# Or, with no Docker at all:
hive up --no-docker --region test_region
```

In dev mode, handler files are watched by `watchfiles`; a save triggers a controlled reload (region publishes `hive/system/sleep/request`, completes a no-commit sleep, resumes wake with the new handler). No container restart required.

### K.2 Inspecting MQTT traffic

Built-in tools via the `hive` CLI:

```bash
hive watch hive/cognitive/#        # tail a topic
hive watch hive/modulator/#        # all modulators
hive watch --retained hive/self/#  # one-shot dump of retained
hive inject hive/sensory/input/text '{"data":"hello","content_type":"text/plain"}'
hive trace <correlation_id>
```

External tools that also work:

- **MQTT Explorer** (GUI): connect to `localhost:1883` with a dev-mode credential.
- **mosquitto_sub**: `mosquitto_sub -t 'hive/#' -v` for raw tailing.
- **Wireshark**: MQTT dissector works on loopback capture.

### K.3 Testing a self-modification cycle

```bash
# 1. Start Hive in dev mode
hive up --dev --regions mpfc,test_region

# 2. Force sleep with a specific intent in STM
hive stm test_region write-slot sleep_instruction \
  '"please add a new handler that responds to hive/sensory/input/text with 'hi'"'

hive inject hive/system/sleep/force '{"region":"test_region"}'

# 3. Watch what happens
hive watch hive/metacognition/#  # see proposals/reflections
hive sleep-history test_region   # see commits

# 4. After restart, test
hive inject hive/sensory/input/text '{"data":"yo","content_type":"text/plain"}'
hive watch hive/motor/speech/intent
```

### K.4 IDE setup

- **VSCode**: workspace in repo root; Python extension detects `region_template/pyproject.toml` and each `regions/*/handlers/*.py`.
- Recommended settings (`.vscode/settings.json`):
  ```json
  {
    "python.analysis.extraPaths": ["region_template", "shared"],
    "python.formatting.provider": "black",
    "ruff.enable": true,
    "[python]": {"editor.formatOnSave": true},
    "files.watcherExclude": {"**/regions/*/memory/**": true}
  }
  ```
- Region handlers import from `region_template` and `shared`; pyright/mypy pick these up via the `extraPaths`.

### K.5 Hot-reload semantics (dev)

`watchfiles` observes `regions/<name>/handlers/` during `--dev`. On file save:

1. Region publishes `hive/system/sleep/request reason=hot_reload`.
2. Glia grants immediately.
3. Region enters SLEEP, skips consolidation, reloads handlers, exits SLEEP back to WAKE.
4. No git commit (dev mode explicitly skips commits for hot-reload sleeps).

This is a purely in-process reload. If the change requires a `region_template` edit, dev must `docker-compose restart <container>`.

### K.6 Starter prompt iteration

Starter prompts are the source of truth at `docs/starter_prompts/<region>.md`. At region birth, glia's `spawn_executor` copies the starter to `regions/<name>/prompt.md` as immutable constitutional DNA (see A.7.1). In production, iterating on a starter after a region is running requires either re-spawning the region (destroy + recreate so glia copies the fresh starter — accumulated appendix and memory are lost) or submitting the change through the code-change review path.

In dev, the faster loop is to bypass the immutability contract directly:

```bash
$EDITOR docs/starter_prompts/test_region.md
cp docs/starter_prompts/test_region.md regions/test_region/prompt.md
hive restart test_region
```

This is appropriate only for test regions where losing appendix / memory history is acceptable. No sleep cycle is involved; prompt changes take effect on next bootstrap.

### K.7 Debugging Python internals

`hive shell <region>` opens bash inside the region container with the runtime loaded. `hive exec <region> python -i -m region_template.debug` opens an interactive REPL with the runtime's globals bound. Useful for prodding memory, checking capabilities, etc.

### K.8 Documentation conventions

- Every module in `region_template/` has a module-level docstring.
- Every public class has a class docstring that cites the relevant principle(s) and spec section.
- Handlers follow the handler contract (A.6.1) — the contract constants double as self-documentation.
- `docs/` holds the principles/architecture/starter-prompts; any new doc lives here.
- No READMEs inside `regions/<name>` — the prompt IS the README from the region's own POV.

### K.9 Linting & formatting

- `ruff` with a curated rule set in `pyproject.toml`.
- `black` for formatting.
- `mypy --strict` on `region_template/` and `shared/`; regions' handlers use looser settings.
- Pre-commit hooks invoke all three.

### K.10 Principles honored in Section K

- **P-XV** (bootstrap then let go): dev-mode tools help the human author the DNA; runtime tools (sleep cycles, git, self-modify) let Hive author its own gene expression.
- **P-XIV** (chaos): dev tools let you inject and observe; they don't pretend to give deterministic repros.

---

## Section L — Open questions

Gaps and tensions surfaced during spec writing. Each requires resolution before or during Phase 4 implementation. None changes the approved design; they are open questions within it.

### L.1 Bootstrapping mPFC's self-state — RESOLVED

**Resolution:** glia does NOT pre-seed `hive/self/*`. The mPFC-owned topics are populated exclusively by mPFC (Principle III, sovereignty). During bootstrap, regions SHOULD subscribe to `hive/self/#` before their WAKE transition but MUST NOT block waiting for values. After 30s of WAKE time without a retained `hive/self/identity`, the region uses `region_template/defaults.yaml`'s `self_fallback` block (J.4) as working context. When mPFC eventually publishes, the retained-value update arrives and overrides the fallback transparently.

This preserves the P-III boundary (mPFC owns self-state) without creating a hard dependency that would cascade into "all 14 regions wait on mPFC's first successful publish." Phase 4 implementation MUST surface a metacog `self_state_fallback_active` at 30s so ACC can observe if mPFC is chronically failing.

### L.2 Glia's privilege escalation

Glia mounts `/var/run/docker.sock`, which gives it host-level privileges. Any compromise of glia compromises the host. At v0 we accept this (local-host dev). Post-v0 options: rootless Docker, sidecar containers with narrower socket proxies, Kubernetes (operator pattern). Call this out; do not "solve" in v0.

### L.3 Retained-topic fan-out cost

`hive/self/*` has 4 retained topics at v0 (identity, values, personality, autobiographical_index — the original 6 minus developmental_stage and age, both dropped on 2026-04-22), all fan-out to 14 regions on every (re)connect. Retained messages are persistent in mosquitto, so a region restarting within 5s sees them instantly. Cost is negligible at 14 regions. At post-v0 counts (50+ regions or fast-cycling spawn) this needs measurement. Not a v0 issue.

### L.4 Sleep starvation

A region with a busy inbound stream may never satisfy `queue_depth < threshold` to earn a sleep grant. Proposed `sleep_max_wake_s` forces sleep, but mid-conversation force-sleep might corrupt user experience. Phase 4 MUST tune defaults per-region type; modulatory regions probably need a lower `sleep_max_wake_s` than PFC.

### L.5 Cross-region memory query load

Hippocampus is a query bottleneck. At v0 volume (one-user, low QPS), this is fine. If PFC queries during every wake cycle, hippocampus's LLM spend becomes dominant. Phase 4 MAY add a per-region query cache with short TTL; spec does not preclude.

### L.6 Modulator "publish storm"

Amygdala under sustained threat could publish cortisol updates every 100ms. Retained topic churn at high cadence. No consumer debounce is specified. Should amygdala rate-limit? Should consumers subsample? Phase 4 decision; default in the starter prompts (≥1s between modulator updates) is a convention, not enforcement.

### L.7 Operator shell security

`hive shell <region>` gives bash inside the container. A compromised operator workstation can do anything to Hive. v0 accepts this. Post-v0 may require role-based operator auth.

### L.8 Metrics persistence

Glia's metrics are in-memory. On glia restart, aggregated counters reset. Retained topic snapshots survive broker restart but don't carry series history. Observability beyond 5 minutes requires an external store — deferred to post-v0 integration with Prometheus/Grafana.

### L.9 Handler hot-reload safety

Dev hot-reload (K.5) does NOT commit and does NOT rebuild docker images. A handler that imports a new top-level dependency will fail because the dependency isn't in the image. Docs MUST call this out: "if you add imports, restart the container."

### L.10 Spawn race with human edit

A human editing `regions/<name>/` while a spawn is mid-flight may create a conflict. Glia's spawn is atomic in the sense that it uses mkdir/mktemp, but the file watcher in dev mode might pick up half-written state. Phase 4 MUST make spawn atomic (stage to `regions/.staging/<name>/` then `mv`).

### L.11 Reserved region slots and ACLs

F.3 lists reserved regions with ACL publisher slots pre-authorized in B.6. If the reserved region name is later disapproved (human decides not to build `raphe_nuclei`), the ACL allows publishes from a region-name that may be taken by a different region. Phase 4 MUST either drop reserved slots on a codechange, or keep them permanently reserved.

### L.12 Principle XIV vs automation

Some automation (exp-backoff retry, auto-rollback) encodes "expected" behavior. At scale, this suppresses learning signal. Phase 4 SHOULD add a `chaos_mode` flag that randomly disables some auto-recoveries in non-prod to surface bugs.

### L.13 Streaming and sleep

A region using streaming LLM (broca) might be mid-stream when a sleep trigger fires. Current spec would interrupt. Phase 4 MUST decide: drain stream before sleep, or abort stream?

### L.14 Sleep abort semantics

D.5.2's `SleepCoordinator.abort()` reverts in-progress changes. If handler edits were partially committed (staged but not committed), git status is dirty after abort. Phase 4 implementation MUST ensure abort leaves git clean (use a checkpoint before edits).

### L.15 The rhythm generator as SPOF

Gamma/beta/theta come from a single coroutine in glia. If glia restarts, rhythms pause for a few seconds. Regions that phase-lock get jitter. Acceptable at v0 but post-v0 may need rhythm-generator high availability.

### L.16 First-boot test region

Testing the self-modification cycle requires a "test_region" that is NOT in `regions_registry.yaml`. Should tests add a temporary registry entry? Should v0 ship a `test_fixtures/` registry? Phase 4 decision.

### L.17 Auto-discovery vs explicit registry

`regions_registry.yaml` is hand-maintained. A spawn must update it; a delete must remove the entry. Phase 4 MUST automate this as part of the spawn/delete codepath — or document that reloading the registry is a manual step.

---

## Appendix 1 — Full file layout

```
hive/
├── README.md
├── CLAUDE.md
├── .env.example
├── docker-compose.yaml
├── docs/
│   ├── HANDOFF.md
│   ├── principles.md
│   ├── architecture.md
│   ├── starter_prompts/
│   │   ├── README.md
│   │   └── <14 starter prompts>
│   └── superpowers/
│       ├── specs/
│       │   └── 2026-04-19-hive-v0-design.md    ← this spec
│       └── plans/
│           └── 2026-04-19-hive-v0-plan.md      (Phase 3)
│
├── region_template/                              ← DNA (P-VI)
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── __init__.py
│   ├── __main__.py
│   ├── runtime.py
│   ├── mqtt_client.py
│   ├── llm_adapter.py
│   ├── llm_providers.py
│   ├── llm_cache.py
│   ├── llm_errors.py
│   ├── token_ledger.py
│   ├── memory.py
│   ├── self_modify.py
│   ├── sleep.py
│   ├── capability.py
│   ├── config_loader.py
│   ├── handlers_loader.py
│   ├── git_tools.py
│   ├── logging_setup.py
│   ├── heartbeat.py
│   ├── errors.py
│   ├── types.py
│   ├── defaults.yaml
│   ├── litellm.config.yaml
│   └── sleep_prompts/
│       └── default_review.md
│
├── regions/                                      ← Gene expression (P-VI)
│   ├── medial_prefrontal_cortex/
│   │   ├── config.yaml
│   │   ├── prompt.md
│   │   ├── subscriptions.yaml
│   │   ├── handlers/
│   │   │   └── __init__.py
│   │   ├── memory/
│   │   │   ├── stm.json
│   │   │   └── ltm/
│   │   └── .git/
│   ├── prefrontal_cortex/           # same shape
│   ├── anterior_cingulate/
│   ├── hippocampus/
│   ├── thalamus/
│   ├── association_cortex/
│   ├── insula/
│   ├── basal_ganglia/
│   ├── visual_cortex/
│   ├── auditory_cortex/
│   ├── motor_cortex/
│   ├── broca_area/
│   ├── amygdala/
│   └── vta/
│
├── glia/                                         ← Infrastructure
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── __main__.py
│   ├── supervisor.py
│   ├── launcher.py
│   ├── heartbeat_monitor.py
│   ├── acl_manager.py
│   ├── rollback.py
│   ├── registry.py
│   ├── metrics.py
│   ├── codechange_executor.py
│   ├── regions_registry.yaml
│   └── bridges/
│       ├── __init__.py
│       ├── mic_bridge.py
│       ├── camera_bridge.py
│       ├── speaker_bridge.py
│       ├── motor_bridge.py
│       ├── input_text_bridge.py
│       └── rhythm_generator.py
│
├── bus/                                          ← Broker
│   ├── mosquitto.conf
│   ├── acl.conf                                  (generated)
│   ├── passwd                                    (generated)
│   ├── acl_templates/
│   │   ├── _base.j2
│   │   └── <region>.j2 × 14
│   └── topic_schema.md
│
├── shared/                                       ← Cross-component utilities
│   ├── pyproject.toml
│   ├── message_envelope.py
│   ├── envelope_schema.json
│   ├── topics.py
│   └── metric_schemas.json
│
├── tests/
│   ├── conftest.py
│   ├── fakes/
│   ├── unit/
│   ├── component/
│   ├── integration/
│   └── smoke/
│
├── tools/
│   ├── dbg/
│   │   ├── hive_trace.py
│   │   ├── hive_watch.py
│   │   ├── hive_stm.py
│   │   └── hive_inject.py
│   └── hive_cli.py                               ← main `hive` CLI
│
└── scripts/
    ├── bootstrap_env.sh                          ← generate .env skeleton
    └── make_passwd.sh                            ← regenerate bus/passwd
```

---

## Appendix 2 — Principles traceability matrix

Each principle mapped to the spec sections and components that enforce it.

| Principle | Enforced by |
|---|---|
| I. Biology is the Tiebreaker | Architecture of glia (E), signal types (B), sleep cycle (A.4), modulator semantics (B.5) |
| II. MQTT is the Nervous System | Section B entire; no non-MQTT cross-region calls anywhere |
| III. Regions are Sovereign | RegionRuntime independence (A), no master controller, handlers may refuse (A.6) |
| IV. Modality Isolation | ACLs (B.6), hardware bridges restricted (E.8), sensory topics broadcast-safe only |
| V. Private Memory | Docker volume isolation (0.5), query protocol (D.6), no cross-region FS reads |
| VI. DNA vs. Gene Expression | Volume mounts RO/RW split (0.5, G.7), self-modify tools scoped (A.7), sleep-only gate |
| VII. One Template, Many Regions | Single image (0.5), single RegionRuntime (A.3), differentiation via config (F) |
| VIII. Always-On, Always-Thinking | Heartbeat tick hook (A.5), ON_HEARTBEAT handlers (A.6.1) |
| IX. Wake and Sleep Cycles | Phase FSM (A.4), sleep-only decorator (A.7.8), consolidation protocol (D.5) |
| X. Capability Honesty | Capability profile schema (F), decorators (A.7.8), LLM adapter gates (C.5.1) |
| XI. LLM-Agnostic Substrate | LiteLLM integration (C), per-region provider choice (F.1) |
| XII. Every Change is Committed | Per-region git (D.5.7), mandatory commit before restart (A.7.6), sleep commit template (D.5.6) |
| XIII. Emergence Over Orchestration | No region commands another (runtime-level); ACC deliberates but doesn't execute; glia executes but doesn't deliberate |
| XIV. Chaos is a Feature | No determinism-asserting tests (I.1), surface failures (C.8), no silent fallbacks |
| XV. Bootstrap Minimally, Then Let Go | `hive up` is only orchestration; DNA change requires human cosign (E.10); regions self-evolve |
| XVI. Signal Types Match Biology | Three topic branches with distinct retained/broadcast rules (B.4, B.5), separate content types (B.3) |

---

*End of spec.*
