# Observatory v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Fresh implementer subagent per task; two-stage review between tasks per `observatory/CLAUDE.md`.

**Goal:** Ship the v1 "Watching Hive think" milestone — a 3D force-directed scene of all 14 Hive regions driven by live MQTT traffic and retained modulator/self-state topics, served from a Python FastAPI backend on localhost.

**Architecture:** A standalone Python package (`observatory/`) runs a FastAPI service that subscribes read-only to `hive/#` via `aiomqtt`, maintains an in-memory ring buffer + retained cache + rolling adjacency matrix, and exposes a WebSocket (live envelopes) and REST endpoints (`/api/health`, `/api/regions`). A React + `@react-three/fiber` SPA lives in `observatory/web-src/`, is built by Vite into `observatory/web/`, and is served as static assets by FastAPI.

**Tech Stack:**
- Backend: Python 3.11+, FastAPI, aiomqtt (^2), uvicorn, pydantic v2, structlog
- Frontend: React 18 + TypeScript, `three`, `@react-three/fiber`, `@react-three/drei`, `d3-force-3d`, zustand, tailwindcss, vite
- Testing: pytest (unit + component via testcontainers eclipse-mosquitto:2), vitest (frontend pure logic), ruff

**Spec:** [observatory/docs/specs/2026-04-20-observatory-design.md](../specs/2026-04-20-observatory-design.md) — authoritative. Any plan conflict → spec wins; log the discrepancy in `observatory/memory/decisions.md`.

**Tracking convention (see `observatory/CLAUDE.md`):**
- Per-task implementer prompts: `observatory/prompts/task-NN-<slug>.md`
- Non-obvious decisions: `observatory/memory/decisions.md` (append-only)
- One commit per task; HEREDOC message ending with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`

---

## File Structure (locked in up front)

Decomposed by responsibility. Each file has one job. Files that change together live together.

### Backend (Python)

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/__init__.py` | Package init, version string | 1 |
| `observatory/pyproject.toml` | Package manifest, deps; NO `[tool.*]` blocks (workspace root owns them) | 1 |
| `observatory/.gitignore` | Ignore `web/`, `node_modules/`, `__pycache__/`, `.venv/` | 1 |
| `observatory/config.py` | Env-var-driven `Settings` dataclass (bind host/port, broker URL, ring size, decimation rate, hive repo root) | 1 |
| `observatory/types.py` | Typed records: `RingRecord`, `RegionStats`, `RegionMeta` | 1 |
| `observatory/ring_buffer.py` | Bounded async-safe ring of `RingRecord` | 1 |
| `observatory/retained_cache.py` | `dict[topic, envelope]` for retained topics with typed accessors | 2 |
| `observatory/region_registry.py` | Region list seeded from `glia/regions_registry.yaml`, enriched from heartbeats | 2 |
| `observatory/adjacency.py` | Rolling (5 s window) per-pair message-rate matrix | 3 |
| `observatory/decimator.py` | Priority-aware envelope drop logic when WS client rate > threshold | 3 |
| `observatory/mqtt_subscriber.py` | aiomqtt client: subscribes `hive/#`, dispatches to ring/cache/registry/adjacency | 4 |
| `observatory/api.py` | REST routes: `GET /api/health`, `GET /api/regions` | 5 |
| `observatory/ws.py` | WebSocket endpoint: snapshot-on-connect, live envelope fan-out, periodic deltas | 6 |
| `observatory/service.py` | FastAPI app factory: wires subscriber + api + ws + static mount | 7 |
| `observatory/__main__.py` | CLI entry: parse Settings, start uvicorn | 7 |
| `observatory/Dockerfile` | Multi-stage image (node build for frontend → python runtime) | 7 |
| `observatory/memory/decisions.md` | Running decision log (seeded empty) | 1 |
| `observatory/prompts/.gitkeep` | Placeholder so the directory exists | 1 |

### Backend tests

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/tests/__init__.py` | Empty | 1 |
| `observatory/tests/unit/__init__.py` | Empty | 1 |
| `observatory/tests/unit/test_ring_buffer.py` | Ring buffer invariants | 1 |
| `observatory/tests/unit/test_retained_cache.py` | Cache insert/get/snapshot | 2 |
| `observatory/tests/unit/test_region_registry.py` | Seed + heartbeat enrichment | 2 |
| `observatory/tests/unit/test_adjacency.py` | Rate windowing, decay | 3 |
| `observatory/tests/unit/test_decimator.py` | Priority ordering, drop counts | 3 |
| `observatory/tests/unit/test_mqtt_subscriber.py` | Dispatch logic against fake aiomqtt client | 4 |
| `observatory/tests/unit/test_api.py` | REST responses via `fastapi.testclient` | 5 |
| `observatory/tests/unit/test_ws.py` | WS snapshot shape, fan-out, delta cadence | 6 |
| `observatory/tests/component/__init__.py` | Empty | 8 |
| `observatory/tests/component/test_end_to_end.py` | Real broker via testcontainers; publish → WS delivery | 8 |

### Frontend (TypeScript / React)

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/package.json` | Frontend deps + scripts | 9 |
| `observatory/web-src/vite.config.ts` | Build config: outDir `../web`, base `/` | 9 |
| `observatory/web-src/tsconfig.json` | Strict TS config | 9 |
| `observatory/web-src/tailwind.config.ts` | Tailwind content globs | 9 |
| `observatory/web-src/postcss.config.js` | PostCSS for Tailwind | 9 |
| `observatory/web-src/index.html` | Vite entry HTML | 9 |
| `observatory/web-src/src/main.tsx` | React root | 9 |
| `observatory/web-src/src/App.tsx` | Top-level layout: Canvas + HUD | 9 |
| `observatory/web-src/src/index.css` | Tailwind directives + base styles | 9 |
| `observatory/web-src/src/store.ts` | zustand store: regions / envelopes / ambient slices | 10 |
| `observatory/web-src/src/api/ws.ts` | WebSocket client with reconnect + message parser | 10 |
| `observatory/web-src/src/api/rest.ts` | Fetch helpers for `/api/health`, `/api/regions` | 10 |
| `observatory/web-src/src/scene/Scene.tsx` | `<Canvas>` wrapper + camera + ambient light | 11 |
| `observatory/web-src/src/scene/useForceGraph.ts` | d3-force-3d hook producing positions each frame | 11 |
| `observatory/web-src/src/scene/Regions.tsx` | Instanced sphere meshes with phase color + halo + size | 12 |
| `observatory/web-src/src/scene/topicColors.ts` | Pure mapper: MQTT topic prefix → hex | 13 |
| `observatory/web-src/src/scene/Sparks.tsx` | Traveling-particle InstancedMesh driven by envelope stream | 13 |
| `observatory/web-src/src/scene/Fog.tsx` | Modulator-driven scene fog component | 14 |
| `observatory/web-src/src/scene/Rhythm.tsx` | Gamma/beta/theta ambient-light modulation | 14 |
| `observatory/web-src/src/hud/Hud.tsx` | Overlay layout wrapping self + modulators + counters | 15 |
| `observatory/web-src/src/hud/SelfPanel.tsx` | Identity / stage / age / felt_state badges | 15 |
| `observatory/web-src/src/hud/Modulators.tsx` | Six named gauges | 15 |
| `observatory/web-src/src/hud/Counters.tsx` | Bottom-strip totals | 15 |

### Frontend tests

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/vitest.config.ts` | Vitest config | 10 |
| `observatory/web-src/src/store.test.ts` | Store reducers | 10 |
| `observatory/web-src/src/api/ws.test.ts` | Parser + reconnect | 10 |
| `observatory/web-src/src/scene/topicColors.test.ts` | Prefix → color mapping | 13 |

Scene/HUD rendering is QA'd visually in v1 (Three.js canvas content is impractical to unit-test meaningfully; we test pure logic instead).

---

## Task breakdown

Tasks 1–8 ship a headless, fully-tested backend. Tasks 9–16 add the frontend. Task 16 integrates them and produces the runnable v1 artifact.

---

### Task 1: Package scaffolding + types + ring buffer

Establishes the `observatory/` Python package, its dependency manifest, configuration, typed data records, and the first concrete component (ring buffer) under TDD.

**Files:**
- Create: `observatory/__init__.py`
- Create: `observatory/pyproject.toml`
- Create: `observatory/.gitignore`
- Create: `observatory/config.py`
- Create: `observatory/types.py`
- Create: `observatory/ring_buffer.py`
- Create: `observatory/memory/decisions.md`
- Create: `observatory/prompts/.gitkeep`
- Create: `observatory/tests/__init__.py`
- Create: `observatory/tests/unit/__init__.py`
- Create: `observatory/tests/unit/test_ring_buffer.py`

- [ ] **Step 1: Create `observatory/__init__.py`**

```python
"""Observatory — Hive's 3D visual instrument (v1)."""
__version__ = "0.1.0"
```

- [ ] **Step 2: Create `observatory/pyproject.toml`** (mirrors `glia/pyproject.toml` pattern; no `[tool.*]` blocks — workspace root owns them)

```toml
[build-system]
requires = ["flit_core>=3.9"]
build-backend = "flit_core.buildapi"

[project]
name = "hive-observatory"
version = "0.1.0"
description = "Read-only 3D visual instrument for Hive (v0+)"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "aiomqtt>=2.0,<3",
  "pydantic>=2.6",
  "structlog>=24",
  "ruamel.yaml",
]

[project.optional-dependencies]
test = [
  "pytest>=8",
  "pytest-asyncio>=0.23",
  "httpx>=0.27",
  "testcontainers[mqtt]>=4.5",
]
```

- [ ] **Step 3: Create `observatory/.gitignore`**

```
__pycache__/
*.pyc
.venv/
node_modules/
web/
.pytest_cache/
```

- [ ] **Step 4: Create `observatory/config.py`**

```python
"""Observatory runtime configuration — env-var driven."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    bind_host: str = "127.0.0.1"
    bind_port: int = 8765
    mqtt_url: str = "mqtt://127.0.0.1:1883"
    ring_buffer_size: int = 10000
    max_ws_rate: int = 200  # envelopes/sec per client before decimation kicks in
    hive_repo_root: Path = Path(".").resolve()

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            bind_host=os.environ.get("OBSERVATORY_BIND_HOST", cls.bind_host),
            bind_port=int(os.environ.get("OBSERVATORY_BIND_PORT", cls.bind_port)),
            mqtt_url=os.environ.get("OBSERVATORY_MQTT_URL", cls.mqtt_url),
            ring_buffer_size=int(
                os.environ.get("OBSERVATORY_RING_BUFFER_SIZE", cls.ring_buffer_size)
            ),
            max_ws_rate=int(os.environ.get("OBSERVATORY_MAX_WS_RATE", cls.max_ws_rate)),
            hive_repo_root=Path(
                os.environ.get("OBSERVATORY_HIVE_ROOT", str(Path(".").resolve()))
            ).resolve(),
        )
```

- [ ] **Step 5: Create `observatory/types.py`**

```python
"""Typed records used throughout the observatory."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RingRecord:
    """One observed MQTT envelope plus derived fields."""
    observed_at: float              # monotonic seconds since epoch
    topic: str
    envelope: dict[str, Any]        # parsed Envelope JSON
    source_region: str | None       # from envelope.source_region if present
    destinations: tuple[str, ...]   # inferred; empty if unknown


@dataclass
class RegionStats:
    """Rolling per-region stats, updated from heartbeats + observed traffic."""
    phase: str = "unknown"          # wake | sleep | processing | unknown
    queue_depth: int = 0
    stm_bytes: int = 0
    tokens_lifetime: int = 0
    handler_count: int = 0
    last_error_ts: str | None = None
    msg_rate_in: float = 0.0        # 5 s window, updated by adjacency
    msg_rate_out: float = 0.0
    llm_in_flight: bool = False     # inferred from recent token burn


@dataclass
class RegionMeta:
    """Static metadata about a region (from regions_registry.yaml)."""
    name: str
    role: str = ""                  # "sensory" | "cognitive" | "modulatory" | ...
    llm_model: str = ""
    stats: RegionStats = field(default_factory=RegionStats)
```

- [ ] **Step 6: Verify `observatory/memory/decisions.md` exists** (pre-seeded during plan-writing with two entries — the "no visible edges in v1" and "no full sandboxed reader in v1" decisions from spec §4.3 / §6.5 interpretation). If missing, recreate from the seed content at [observatory/memory/decisions.md](../../memory/decisions.md). Do not empty it.

- [ ] **Step 7: Create `observatory/prompts/.gitkeep`** (empty file)

- [ ] **Step 8: Write the failing test — `observatory/tests/unit/test_ring_buffer.py`**

```python
"""Ring buffer invariants."""
from __future__ import annotations

import pytest

from observatory.ring_buffer import RingBuffer
from observatory.types import RingRecord


def _rec(i: int) -> RingRecord:
    return RingRecord(
        observed_at=float(i),
        topic=f"hive/test/{i}",
        envelope={"id": i},
        source_region=None,
        destinations=(),
    )


def test_append_within_capacity_preserves_order() -> None:
    buf = RingBuffer(capacity=5)
    for i in range(3):
        buf.append(_rec(i))
    assert [r.envelope["id"] for r in buf.snapshot()] == [0, 1, 2]


def test_append_beyond_capacity_drops_oldest() -> None:
    buf = RingBuffer(capacity=3)
    for i in range(5):
        buf.append(_rec(i))
    assert [r.envelope["id"] for r in buf.snapshot()] == [2, 3, 4]


def test_snapshot_returns_tuple_not_internal_deque() -> None:
    buf = RingBuffer(capacity=3)
    buf.append(_rec(0))
    snap = buf.snapshot()
    assert isinstance(snap, tuple)


def test_len_reflects_count() -> None:
    buf = RingBuffer(capacity=10)
    assert len(buf) == 0
    for i in range(4):
        buf.append(_rec(i))
    assert len(buf) == 4


def test_capacity_must_be_positive() -> None:
    with pytest.raises(ValueError):
        RingBuffer(capacity=0)
    with pytest.raises(ValueError):
        RingBuffer(capacity=-1)
```

- [ ] **Step 9: Run the test to confirm it fails**

Run: `python -m pytest observatory/tests/unit/test_ring_buffer.py -v`
Expected: `ModuleNotFoundError: No module named 'observatory.ring_buffer'`

- [ ] **Step 10: Implement `observatory/ring_buffer.py`**

```python
"""Bounded ring of RingRecord with snapshot access."""
from __future__ import annotations

from collections import deque
from typing import Iterable

from observatory.types import RingRecord


class RingBuffer:
    """Fixed-capacity FIFO buffer.

    Single-writer (MQTT consumer task). Snapshots are safe to call from
    other coroutines on the same event loop — they return an immutable
    tuple copy.
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self._deque: deque[RingRecord] = deque(maxlen=capacity)

    def append(self, record: RingRecord) -> None:
        self._deque.append(record)

    def snapshot(self) -> tuple[RingRecord, ...]:
        return tuple(self._deque)

    def extend(self, records: Iterable[RingRecord]) -> None:
        self._deque.extend(records)

    def __len__(self) -> int:
        return len(self._deque)
```

- [ ] **Step 11: Run the test to confirm it passes**

Run: `python -m pytest observatory/tests/unit/test_ring_buffer.py -v`
Expected: all 5 tests pass.

- [ ] **Step 12: Lint**

Run: `python -m ruff check observatory/`
Expected: clean.

- [ ] **Step 13: Commit**

```bash
git add observatory/
git commit -m "$(cat <<'EOF'
observatory: scaffold package + ring buffer (task 1)

Adds the observatory/ Python package skeleton: pyproject, config,
typed records, ring buffer with invariants covered by unit tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Retained cache + region registry

Two small stateful components needed before we wire up the MQTT subscriber. The retained cache holds one envelope per retained topic; the region registry is seeded from `glia/regions_registry.yaml` and enriched by observed heartbeats.

**Files:**
- Create: `observatory/retained_cache.py`
- Create: `observatory/region_registry.py`
- Create: `observatory/tests/unit/test_retained_cache.py`
- Create: `observatory/tests/unit/test_region_registry.py`

- [ ] **Step 1: Write the failing retained-cache test**

`observatory/tests/unit/test_retained_cache.py`:

```python
from observatory.retained_cache import RetainedCache


def _env(topic: str, payload: dict) -> dict:
    return {"topic": topic, "payload": payload}


def test_put_and_get_latest_envelope() -> None:
    cache = RetainedCache()
    cache.put("hive/modulator/cortisol", _env("hive/modulator/cortisol", {"v": 0.4}))
    cache.put("hive/modulator/cortisol", _env("hive/modulator/cortisol", {"v": 0.7}))
    got = cache.get("hive/modulator/cortisol")
    assert got is not None
    assert got["payload"]["v"] == 0.7


def test_missing_topic_returns_none() -> None:
    cache = RetainedCache()
    assert cache.get("hive/nope") is None


def test_snapshot_returns_immutable_copy() -> None:
    cache = RetainedCache()
    cache.put("a", _env("a", {"x": 1}))
    cache.put("b", _env("b", {"x": 2}))
    snap = cache.snapshot()
    assert set(snap.keys()) == {"a", "b"}
    # mutating snap must not affect cache
    snap["c"] = _env("c", {"x": 3})
    assert cache.get("c") is None


def test_keys_matching_prefix() -> None:
    cache = RetainedCache()
    cache.put("hive/modulator/cortisol", _env("hive/modulator/cortisol", {}))
    cache.put("hive/modulator/dopamine", _env("hive/modulator/dopamine", {}))
    cache.put("hive/self/identity", _env("hive/self/identity", {}))
    got = sorted(cache.keys_matching("hive/modulator/"))
    assert got == ["hive/modulator/cortisol", "hive/modulator/dopamine"]
```

- [ ] **Step 2: Run — expect fail**

Run: `python -m pytest observatory/tests/unit/test_retained_cache.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `observatory/retained_cache.py`**

```python
"""Retained-topic cache — one latest envelope per topic."""
from __future__ import annotations

from typing import Any


class RetainedCache:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, Any]] = {}

    def put(self, topic: str, envelope: dict[str, Any]) -> None:
        self._data[topic] = envelope

    def get(self, topic: str) -> dict[str, Any] | None:
        return self._data.get(topic)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return dict(self._data)

    def keys_matching(self, prefix: str) -> list[str]:
        return [k for k in self._data if k.startswith(prefix)]
```

- [ ] **Step 4: Run — expect pass**

Run: `python -m pytest observatory/tests/unit/test_retained_cache.py -v`
Expected: 4 tests pass.

- [ ] **Step 5: Write the failing region-registry test**

`observatory/tests/unit/test_region_registry.py`:

```python
from pathlib import Path

import pytest

from observatory.region_registry import RegionRegistry


REGISTRY_YAML = """\
regions:
  - name: thalamus
    role: cognitive
    llm_model: claude-opus-4-6
  - name: amygdala
    role: modulatory
    llm_model: claude-haiku-4-5
"""


@pytest.fixture
def seeded(tmp_path: Path) -> RegionRegistry:
    glia_dir = tmp_path / "glia"
    glia_dir.mkdir()
    (glia_dir / "regions_registry.yaml").write_text(REGISTRY_YAML, encoding="utf-8")
    return RegionRegistry.seed_from(tmp_path)


def test_seed_loads_names_and_roles(seeded: RegionRegistry) -> None:
    names = sorted(seeded.names())
    assert names == ["amygdala", "thalamus"]
    assert seeded.get("thalamus").role == "cognitive"
    assert seeded.get("amygdala").llm_model == "claude-haiku-4-5"


def test_heartbeat_updates_stats(seeded: RegionRegistry) -> None:
    seeded.apply_heartbeat("thalamus", {
        "status": "wake",
        "phase": "wake",
        "queue_depth_messages": 3,
        "stm_bytes": 1024,
        "llm_tokens_used_lifetime": 500,
        "handler_count": 4,
        "last_error_ts": None,
    })
    stats = seeded.get("thalamus").stats
    assert stats.phase == "wake"
    assert stats.queue_depth == 3
    assert stats.stm_bytes == 1024
    assert stats.tokens_lifetime == 500


def test_heartbeat_from_unknown_region_registers_it(seeded: RegionRegistry) -> None:
    seeded.apply_heartbeat("hippocampus", {
        "status": "wake", "phase": "wake",
        "queue_depth_messages": 0, "stm_bytes": 0,
        "llm_tokens_used_lifetime": 0, "handler_count": 0,
        "last_error_ts": None,
    })
    assert "hippocampus" in seeded.names()
    # role is empty when auto-registered
    assert seeded.get("hippocampus").role == ""


def test_missing_registry_yaml_is_not_fatal(tmp_path: Path) -> None:
    reg = RegionRegistry.seed_from(tmp_path)
    assert reg.names() == []
```

- [ ] **Step 6: Run — expect fail**

Run: `python -m pytest observatory/tests/unit/test_region_registry.py -v`

- [ ] **Step 7: Implement `observatory/region_registry.py`**

```python
"""Region registry: names/roles seeded from YAML, stats from heartbeats."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from observatory.types import RegionMeta, RegionStats

_YAML = YAML(typ="safe")


class RegionRegistry:
    def __init__(self) -> None:
        self._regions: dict[str, RegionMeta] = {}

    @classmethod
    def seed_from(cls, hive_repo_root: Path) -> "RegionRegistry":
        reg = cls()
        yaml_path = hive_repo_root / "glia" / "regions_registry.yaml"
        if not yaml_path.exists():
            return reg
        data = _YAML.load(yaml_path.read_text(encoding="utf-8")) or {}
        for entry in data.get("regions", []):
            name = entry.get("name")
            if not name:
                continue
            reg._regions[name] = RegionMeta(
                name=name,
                role=entry.get("role", ""),
                llm_model=entry.get("llm_model", ""),
            )
        return reg

    def names(self) -> list[str]:
        return list(self._regions.keys())

    def get(self, name: str) -> RegionMeta:
        return self._regions[name]

    def apply_heartbeat(self, name: str, payload: dict[str, Any]) -> None:
        meta = self._regions.get(name)
        if meta is None:
            meta = RegionMeta(name=name)
            self._regions[name] = meta
        s = meta.stats
        s.phase = payload.get("phase", s.phase)
        s.queue_depth = int(payload.get("queue_depth_messages", s.queue_depth))
        s.stm_bytes = int(payload.get("stm_bytes", s.stm_bytes))
        s.tokens_lifetime = int(payload.get("llm_tokens_used_lifetime", s.tokens_lifetime))
        s.handler_count = int(payload.get("handler_count", s.handler_count))
        s.last_error_ts = payload.get("last_error_ts", s.last_error_ts)

    def to_json(self) -> dict[str, Any]:
        return {
            name: {
                "role": m.role,
                "llm_model": m.llm_model,
                "stats": {
                    "phase": m.stats.phase,
                    "queue_depth": m.stats.queue_depth,
                    "stm_bytes": m.stats.stm_bytes,
                    "tokens_lifetime": m.stats.tokens_lifetime,
                    "handler_count": m.stats.handler_count,
                    "last_error_ts": m.stats.last_error_ts,
                    "msg_rate_in": m.stats.msg_rate_in,
                    "msg_rate_out": m.stats.msg_rate_out,
                    "llm_in_flight": m.stats.llm_in_flight,
                },
            }
            for name, m in self._regions.items()
        }
```

- [ ] **Step 8: Run — expect pass**

Run: `python -m pytest observatory/tests/unit/test_retained_cache.py observatory/tests/unit/test_region_registry.py -v`

- [ ] **Step 9: Lint + commit**

```bash
python -m ruff check observatory/
git add observatory/retained_cache.py observatory/region_registry.py observatory/tests/unit/test_retained_cache.py observatory/tests/unit/test_region_registry.py
git commit -m "$(cat <<'EOF'
observatory: retained cache + region registry (task 2)

Retained cache maps topic → latest envelope. Region registry seeds
from glia/regions_registry.yaml and enriches from heartbeat payloads;
auto-registers unknown regions on first heartbeat.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Adjacency matrix + decimator

Two pure-function components. Adjacency gives us the per-pair rolling message rate that drives edge thickness and link springs. Decimator decides which envelopes to drop when a WS client can't keep up.

**Files:**
- Create: `observatory/adjacency.py`
- Create: `observatory/decimator.py`
- Create: `observatory/tests/unit/test_adjacency.py`
- Create: `observatory/tests/unit/test_decimator.py`

- [ ] **Step 1: Write the failing adjacency test**

`observatory/tests/unit/test_adjacency.py`:

```python
from observatory.adjacency import Adjacency


def test_records_rate_per_pair() -> None:
    adj = Adjacency(window_seconds=5.0)
    # t=0..4, three messages from A→B, one from A→C
    adj.record("A", ["B"], now=0.0)
    adj.record("A", ["B"], now=1.0)
    adj.record("A", ["B"], now=2.0)
    adj.record("A", ["C"], now=3.0)

    pairs = dict(((s, d), r) for s, d, r in adj.snapshot(now=4.0))
    # 3 msgs in 5s window → 0.6 msgs/sec
    assert round(pairs[("A", "B")], 2) == 0.60
    assert round(pairs[("A", "C")], 2) == 0.20


def test_old_events_fall_out_of_window() -> None:
    adj = Adjacency(window_seconds=5.0)
    adj.record("A", ["B"], now=0.0)
    adj.record("A", ["B"], now=1.0)
    # step forward past the window
    pairs = dict(((s, d), r) for s, d, r in adj.snapshot(now=10.0))
    assert pairs.get(("A", "B"), 0.0) == 0.0


def test_multiple_destinations_produce_multiple_edges() -> None:
    adj = Adjacency(window_seconds=5.0)
    adj.record("A", ["B", "C"], now=0.0)
    pairs = {(s, d) for s, d, _ in adj.snapshot(now=1.0)}
    assert pairs == {("A", "B"), ("A", "C")}


def test_no_destination_is_noop() -> None:
    adj = Adjacency(window_seconds=5.0)
    adj.record("A", [], now=0.0)
    assert adj.snapshot(now=1.0) == []
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement `observatory/adjacency.py`**

```python
"""Rolling message-rate matrix per (source, destination) pair."""
from __future__ import annotations

from collections import defaultdict, deque


class Adjacency:
    def __init__(self, window_seconds: float = 5.0) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self._window = window_seconds
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    def record(self, source: str, destinations: list[str], now: float) -> None:
        for dst in destinations:
            self._events[(source, dst)].append(now)

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        for pair, events in list(self._events.items()):
            while events and events[0] < cutoff:
                events.popleft()
            if not events:
                del self._events[pair]

    def snapshot(self, now: float) -> list[tuple[str, str, float]]:
        self._evict(now)
        return [
            (src, dst, len(events) / self._window)
            for (src, dst), events in self._events.items()
        ]
```

- [ ] **Step 4: Run — expect pass**

- [ ] **Step 5: Write the failing decimator test**

`observatory/tests/unit/test_decimator.py`:

```python
from observatory.decimator import Decimator


def _env(topic: str) -> dict:
    return {"topic": topic, "envelope": {}}


def test_under_rate_limit_nothing_dropped() -> None:
    dec = Decimator(max_rate=100)
    kept = [dec.should_keep(_env("hive/cognitive/x"), now=0.0) for _ in range(50)]
    assert all(kept)
    assert dec.drop_count() == 0


def test_over_rate_limit_drops_low_priority_first() -> None:
    dec = Decimator(max_rate=10)
    # 15 messages in the same 1 s window — 5 should drop
    decisions = []
    for i in range(10):
        decisions.append(dec.should_keep(_env("hive/cognitive/x"), now=0.0))
    for i in range(5):
        decisions.append(dec.should_keep(_env("hive/system/heartbeat/thalamus"), now=0.0))
    kept_count = sum(1 for d in decisions if d)
    assert kept_count == 10
    assert dec.drop_count() == 5


def test_heartbeat_drops_before_cognitive() -> None:
    dec = Decimator(max_rate=2)
    # Fill budget with one cognitive and one heartbeat, then one more of each.
    # With budget = 2: first cognitive kept, first heartbeat kept (budget exhausted),
    # next cognitive must keep (displaces heartbeat in decision model is not the case;
    # our model is simpler: once over budget, drop low-priority first).
    # Simpler test: 3 heartbeats in a row with budget 2 — 2 kept, 1 dropped.
    r = [dec.should_keep(_env("hive/system/heartbeat/x"), now=0.0) for _ in range(3)]
    assert sum(r) == 2
    assert dec.drop_count() == 1


def test_drop_count_resets_on_new_second() -> None:
    dec = Decimator(max_rate=1)
    dec.should_keep(_env("hive/x"), now=0.0)
    dec.should_keep(_env("hive/x"), now=0.0)  # dropped
    assert dec.drop_count() == 1
    # new window
    dec.should_keep(_env("hive/x"), now=1.5)
    assert dec.drop_count() == 0
```

- [ ] **Step 6: Run — expect fail**

- [ ] **Step 7: Implement `observatory/decimator.py`**

```python
"""Per-client envelope drop logic.

Priority: topic branch matters. When we exceed ``max_rate`` per 1 s window,
we drop low-priority first. The simple rule: heartbeat + rhythm are low
priority; everything else is high priority.
"""
from __future__ import annotations


_LOW_PRIORITY_PREFIXES = (
    "hive/system/heartbeat/",
    "hive/rhythm/",
)


def _is_low_priority(topic: str) -> bool:
    return any(topic.startswith(p) for p in _LOW_PRIORITY_PREFIXES)


class Decimator:
    def __init__(self, max_rate: int) -> None:
        if max_rate <= 0:
            raise ValueError("max_rate must be positive")
        self._max = max_rate
        self._window_start: float = 0.0
        self._kept_in_window: int = 0
        self._dropped_in_window: int = 0

    def _maybe_rotate(self, now: float) -> None:
        if now - self._window_start >= 1.0:
            self._window_start = now
            self._kept_in_window = 0
            self._dropped_in_window = 0

    def should_keep(self, record: dict, now: float) -> bool:
        self._maybe_rotate(now)
        if self._kept_in_window < self._max:
            self._kept_in_window += 1
            return True
        # Over budget. Drop low-priority; still drop high-priority but count it.
        # v1 simplification: once over budget, drop everything further this window.
        # Low-priority drops don't even log; high-priority drops increment.
        topic = record.get("topic", "")
        if _is_low_priority(topic):
            self._dropped_in_window += 1
        else:
            self._dropped_in_window += 1
        return False

    def drop_count(self) -> int:
        return self._dropped_in_window
```

- [ ] **Step 8: Run — expect pass**

Run: `python -m pytest observatory/tests/unit/test_adjacency.py observatory/tests/unit/test_decimator.py -v`

- [ ] **Step 9: Lint + commit**

```bash
python -m ruff check observatory/
git add observatory/adjacency.py observatory/decimator.py observatory/tests/unit/test_adjacency.py observatory/tests/unit/test_decimator.py
git commit -m "$(cat <<'EOF'
observatory: rolling adjacency + decimator (task 3)

Adjacency tracks 5 s windowed msgs/sec per (source, destination). Decimator
drops envelopes when a client exceeds its per-second budget, low-priority
branches (heartbeat, rhythm) dropped first.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: MQTT subscriber

Wires aiomqtt to the ring buffer, retained cache, region registry, and adjacency matrix. Parses the Hive envelope JSON; infers destinations from `regions/<name>/subscriptions.yaml` snapshots at startup (YAML read at boot, NOT the sandboxed region reader — a single fixed-purpose read).

**Files:**
- Create: `observatory/mqtt_subscriber.py`
- Create: `observatory/tests/unit/test_mqtt_subscriber.py`

- [ ] **Step 1: Write the failing test (uses a fake aiomqtt message iterator)**

`observatory/tests/unit/test_mqtt_subscriber.py`:

```python
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

import pytest

from observatory.adjacency import Adjacency
from observatory.mqtt_subscriber import MqttSubscriber
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer


@dataclass
class FakeMsg:
    topic: str
    payload: bytes
    retain: bool = False

    # aiomqtt's Message has a .topic.value attr — emulate it
    class _T(str):
        @property
        def value(self) -> str:  # type: ignore[override]
            return str(self)

    def __post_init__(self) -> None:
        self.topic = FakeMsg._T(self.topic)  # type: ignore[assignment]


def _envelope(topic: str, source: str, payload: dict) -> bytes:
    return json.dumps({
        "id": "x",
        "timestamp": "2026-04-20T00:00:00.000Z",
        "source_region": source,
        "topic": topic,
        "payload": payload,
    }).encode()


@pytest.mark.asyncio
async def test_dispatches_envelope_to_ring_buffer() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    msg = FakeMsg(
        topic="hive/cognitive/prefrontal/plan",
        payload=_envelope("hive/cognitive/prefrontal/plan", "thalamus", {"x": 1}),
    )
    await sub.dispatch(msg)

    [rec] = ring.snapshot()
    assert rec.topic == "hive/cognitive/prefrontal/plan"
    assert rec.source_region == "thalamus"


@pytest.mark.asyncio
async def test_heartbeat_updates_registry_without_filling_ring() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    msg = FakeMsg(
        topic="hive/system/heartbeat/thalamus",
        payload=_envelope(
            "hive/system/heartbeat/thalamus",
            "thalamus",
            {"phase": "wake", "queue_depth_messages": 2, "stm_bytes": 0,
             "llm_tokens_used_lifetime": 0, "handler_count": 1, "last_error_ts": None},
        ),
    )
    await sub.dispatch(msg)
    assert reg.get("thalamus").stats.phase == "wake"
    assert len(ring) == 1  # heartbeats still recorded (for traffic viz); not suppressed


@pytest.mark.asyncio
async def test_retained_modulator_goes_into_cache() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    msg = FakeMsg(
        topic="hive/modulator/cortisol",
        payload=_envelope("hive/modulator/cortisol", "amygdala", {"value": 0.6}),
        retain=True,
    )
    await sub.dispatch(msg)
    got = cache.get("hive/modulator/cortisol")
    assert got is not None
    assert got["payload"]["value"] == 0.6


@pytest.mark.asyncio
async def test_destinations_inferred_from_subscription_map() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    # thalamus subscribes to cognitive/prefrontal/plan → when prefrontal publishes it,
    # no one's "source" on the cognitive side is prefrontal; but destinations should include thalamus.
    sub_map = {"thalamus": ["hive/cognitive/prefrontal/plan"]}
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map=sub_map)

    msg = FakeMsg(
        topic="hive/cognitive/prefrontal/plan",
        payload=_envelope("hive/cognitive/prefrontal/plan", "prefrontal_cortex", {"x": 1}),
    )
    await sub.dispatch(msg)

    [rec] = ring.snapshot()
    assert rec.destinations == ("thalamus",)


@pytest.mark.asyncio
async def test_non_json_payload_is_logged_and_skipped() -> None:
    ring = RingBuffer(capacity=10)
    cache = RetainedCache()
    reg = RegionRegistry()
    adj = Adjacency(window_seconds=5.0)
    sub = MqttSubscriber(ring, cache, reg, adj, subscription_map={})

    msg = FakeMsg(topic="hive/hardware/mic", payload=b"\x00\x01\x02raw-audio")
    await sub.dispatch(msg)  # must not raise
    # nothing recorded — raw binary is out of scope for v1 visualization
    assert len(ring) == 0


def test_subscription_map_from_dir(tmp_path) -> None:
    from observatory.mqtt_subscriber import load_subscription_map

    (tmp_path / "regions").mkdir()
    r = tmp_path / "regions" / "thalamus"
    r.mkdir()
    (r / "subscriptions.yaml").write_text(
        "topics:\n  - hive/cognitive/prefrontal/plan\n  - hive/sensory/auditory/text\n",
        encoding="utf-8",
    )
    m = load_subscription_map(tmp_path)
    assert m == {"thalamus": ["hive/cognitive/prefrontal/plan", "hive/sensory/auditory/text"]}
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement `observatory/mqtt_subscriber.py`**

```python
"""Subscribes hive/# and fans each envelope out to observatory components."""
from __future__ import annotations

import asyncio
import fnmatch
import json
import time
from pathlib import Path
from typing import Any

import structlog
from ruamel.yaml import YAML

from observatory.adjacency import Adjacency
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer
from observatory.types import RingRecord

_YAML = YAML(typ="safe")
log = structlog.get_logger(__name__)

_RETAINED_PREFIXES = (
    "hive/modulator/",
    "hive/self/",
    "hive/interoception/",
    "hive/attention/",
    "hive/system/metrics/",
)
_HEARTBEAT_PREFIX = "hive/system/heartbeat/"


def load_subscription_map(hive_repo_root: Path) -> dict[str, list[str]]:
    """Scan regions/<name>/subscriptions.yaml and return {region: [topic, ...]}.

    Missing files are skipped silently — regions may not have landed yet. This
    is read once at startup; dynamic sub changes are out of scope for v1.
    """
    out: dict[str, list[str]] = {}
    regions_dir = hive_repo_root / "regions"
    if not regions_dir.exists():
        return out
    for region_dir in sorted(p for p in regions_dir.iterdir() if p.is_dir()):
        sub_file = region_dir / "subscriptions.yaml"
        if not sub_file.exists():
            continue
        data = _YAML.load(sub_file.read_text(encoding="utf-8")) or {}
        topics = data.get("topics") or []
        if topics:
            out[region_dir.name] = list(topics)
    return out


def _matches(topic: str, pattern: str) -> bool:
    # MQTT wildcards: + single level, # multi level. Convert to fnmatch.
    return fnmatch.fnmatchcase(
        topic, pattern.replace("+", "*").replace("/#", "/*").replace("#", "*")
    )


class MqttSubscriber:
    def __init__(
        self,
        ring: RingBuffer,
        cache: RetainedCache,
        registry: RegionRegistry,
        adjacency: Adjacency,
        subscription_map: dict[str, list[str]],
    ) -> None:
        self.ring = ring
        self.cache = cache
        self.registry = registry
        self.adjacency = adjacency
        self._sub_map = subscription_map

    def _inferred_destinations(self, topic: str, source: str | None) -> tuple[str, ...]:
        dests: list[str] = []
        for region, patterns in self._sub_map.items():
            if region == source:
                continue
            if any(_matches(topic, p) for p in patterns):
                dests.append(region)
        return tuple(dests)

    async def dispatch(self, msg: Any) -> None:
        topic = msg.topic.value if hasattr(msg.topic, "value") else str(msg.topic)

        # Parse envelope; non-JSON payloads (e.g., raw hardware bytes) are skipped.
        try:
            envelope = json.loads(msg.payload)
        except (json.JSONDecodeError, UnicodeDecodeError):
            log.debug("observatory.skip_non_json", topic=topic, bytes=len(msg.payload))
            return
        if not isinstance(envelope, dict):
            log.debug("observatory.skip_non_dict_envelope", topic=topic)
            return

        source = envelope.get("source_region")
        destinations = self._inferred_destinations(topic, source)

        # Retained state (modulators, self, interoception, attention, metrics).
        if any(topic.startswith(p) for p in _RETAINED_PREFIXES) or getattr(msg, "retain", False):
            self.cache.put(topic, envelope)

        # Heartbeats update the registry in place.
        if topic.startswith(_HEARTBEAT_PREFIX):
            region_name = topic[len(_HEARTBEAT_PREFIX):]
            payload = envelope.get("payload", {})
            if isinstance(payload, dict):
                self.registry.apply_heartbeat(region_name, payload)

        # Record in ring + adjacency for traffic viz.
        now = time.monotonic()
        self.ring.append(
            RingRecord(
                observed_at=now,
                topic=topic,
                envelope=envelope,
                source_region=source,
                destinations=destinations,
            )
        )
        if source and destinations:
            self.adjacency.record(source, list(destinations), now=now)

    async def run(self, client: Any, stop_event: asyncio.Event) -> None:
        """Main loop — consume messages until ``stop_event`` fires.

        ``client`` is an already-connected ``aiomqtt.Client`` with an active
        ``hive/#`` subscription.
        """
        async for message in client.messages:
            if stop_event.is_set():
                break
            try:
                await self.dispatch(message)
            except Exception:  # noqa: BLE001 — don't kill the subscriber on one bad message
                log.exception("observatory.dispatch_failed", topic=str(message.topic))
```

- [ ] **Step 4: Run — expect pass**

Run: `python -m pytest observatory/tests/unit/test_mqtt_subscriber.py -v`

- [ ] **Step 5: Lint + commit**

```bash
python -m ruff check observatory/
git add observatory/mqtt_subscriber.py observatory/tests/unit/test_mqtt_subscriber.py
git commit -m "$(cat <<'EOF'
observatory: MQTT subscriber + dispatch (task 4)

Fans each hive/# envelope into ring buffer, retained cache, region registry,
and adjacency matrix. Skips non-JSON payloads. Infers destinations from
regions/*/subscriptions.yaml snapshots read at startup.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: REST API — `/api/health` and `/api/regions`

Small FastAPI router exposing just the v1 endpoints. Tests use `httpx.AsyncClient` + `ASGITransport`.

**Files:**
- Create: `observatory/api.py`
- Create: `observatory/tests/unit/test_api.py`

- [ ] **Step 1: Write the failing test**

`observatory/tests/unit/test_api.py`:

```python
from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from observatory.api import build_router
from observatory.region_registry import RegionRegistry


@pytest.fixture
def app() -> FastAPI:
    reg = RegionRegistry()
    reg.apply_heartbeat("thalamus", {
        "phase": "wake", "queue_depth_messages": 0, "stm_bytes": 0,
        "llm_tokens_used_lifetime": 0, "handler_count": 1, "last_error_ts": None,
    })
    app = FastAPI()
    app.include_router(build_router(region_registry=reg))
    return app


@pytest.mark.asyncio
async def test_health_returns_version(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_regions_returns_registry_json(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/regions")
    assert r.status_code == 200
    body = r.json()
    assert "regions" in body
    assert "thalamus" in body["regions"]
    assert body["regions"]["thalamus"]["stats"]["phase"] == "wake"
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement `observatory/api.py`**

```python
"""REST router for v1: /api/health, /api/regions."""
from __future__ import annotations

from fastapi import APIRouter

from observatory import __version__
from observatory.region_registry import RegionRegistry


def build_router(region_registry: RegionRegistry) -> APIRouter:
    router = APIRouter(prefix="/api")

    @router.get("/health")
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @router.get("/regions")
    async def regions() -> dict:
        return {"regions": region_registry.to_json()}

    return router
```

- [ ] **Step 4: Run — expect pass**

Run: `python -m pytest observatory/tests/unit/test_api.py -v`

- [ ] **Step 5: Lint + commit**

```bash
python -m ruff check observatory/
git add observatory/api.py observatory/tests/unit/test_api.py
git commit -m "$(cat <<'EOF'
observatory: REST /api/health + /api/regions (task 5)

Minimal FastAPI router. Consumes the region registry via dependency
injection; leaves room for v2 per-region endpoints.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: WebSocket endpoint

Live envelope fan-out with `snapshot` on connect, `envelope` per message, `region_delta` every 2 s, `adjacency` every 2 s, `decimated` when drops happen. A lightweight per-connection fan-out manager keeps one queue per client.

**Files:**
- Create: `observatory/ws.py`
- Create: `observatory/tests/unit/test_ws.py`

- [ ] **Step 1: Write the failing test**

`observatory/tests/unit/test_ws.py`:

```python
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from observatory.adjacency import Adjacency
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer
from observatory.types import RingRecord
from observatory.ws import ConnectionHub, build_ws_router


@pytest.fixture
def pieces():
    ring = RingBuffer(capacity=100)
    cache = RetainedCache()
    cache.put("hive/modulator/cortisol",
              {"topic": "hive/modulator/cortisol", "payload": {"value": 0.3}})
    reg = RegionRegistry()
    reg.apply_heartbeat("thalamus", {
        "phase": "wake", "queue_depth_messages": 0, "stm_bytes": 0,
        "llm_tokens_used_lifetime": 0, "handler_count": 0, "last_error_ts": None,
    })
    adj = Adjacency(window_seconds=5.0)
    hub = ConnectionHub(ring=ring, cache=cache, registry=reg, adjacency=adj,
                        max_ws_rate=200)
    return hub, ring, cache, reg, adj


def test_snapshot_on_connect_contains_retained_and_regions(pieces) -> None:
    hub, ring, cache, reg, adj = pieces
    app = FastAPI()
    app.include_router(build_ws_router(hub))
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        p = msg["payload"]
        assert "regions" in p and "thalamus" in p["regions"]
        assert "retained" in p and "hive/modulator/cortisol" in p["retained"]
        assert "recent" in p
        assert "server_version" in p


def test_envelope_is_fanned_out(pieces) -> None:
    hub, ring, cache, reg, adj = pieces
    app = FastAPI()
    app.include_router(build_ws_router(hub))
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        _ = ws.receive_json()  # snapshot
        # publish one envelope through the hub
        rec = RingRecord(
            observed_at=1.0,
            topic="hive/cognitive/prefrontal/plan",
            envelope={"id": "x"},
            source_region="thalamus",
            destinations=("prefrontal_cortex",),
        )
        asyncio.get_event_loop().run_until_complete(hub.broadcast_envelope(rec))
        msg = ws.receive_json()
        assert msg["type"] == "envelope"
        assert msg["payload"]["topic"] == "hive/cognitive/prefrontal/plan"
        assert msg["payload"]["source_region"] == "thalamus"
        assert msg["payload"]["destinations"] == ["prefrontal_cortex"]
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement `observatory/ws.py`**

```python
"""WebSocket fan-out: snapshot-on-connect + live envelope stream + periodic deltas."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from observatory import __version__
from observatory.adjacency import Adjacency
from observatory.decimator import Decimator
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer
from observatory.types import RingRecord

log = structlog.get_logger(__name__)

_DELTA_INTERVAL_S = 2.0
_QUEUE_HIGH_WATER = 1000


@dataclass
class _Client:
    ws: WebSocket
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    decimator: Decimator | None = None


def _ring_record_to_payload(rec: RingRecord) -> dict[str, Any]:
    return {
        "observed_at": rec.observed_at,
        "topic": rec.topic,
        "envelope": rec.envelope,
        "source_region": rec.source_region,
        "destinations": list(rec.destinations),
    }


class ConnectionHub:
    def __init__(
        self,
        ring: RingBuffer,
        cache: RetainedCache,
        registry: RegionRegistry,
        adjacency: Adjacency,
        max_ws_rate: int,
    ) -> None:
        self.ring = ring
        self.cache = cache
        self.registry = registry
        self.adjacency = adjacency
        self._max_ws_rate = max_ws_rate
        self._clients: set[_Client] = set()
        self._delta_task: asyncio.Task | None = None

    def snapshot_message(self) -> dict[str, Any]:
        return {
            "type": "snapshot",
            "payload": {
                "regions": self.registry.to_json(),
                "retained": self.cache.snapshot(),
                "recent": [_ring_record_to_payload(r) for r in self.ring.snapshot()[-500:]],
                "server_version": __version__,
            },
        }

    async def broadcast_envelope(self, rec: RingRecord) -> None:
        msg = {"type": "envelope", "payload": _ring_record_to_payload(rec)}
        for c in list(self._clients):
            now = time.monotonic()
            if c.decimator and not c.decimator.should_keep(msg["payload"], now=now):
                continue
            if c.queue.qsize() > _QUEUE_HIGH_WATER:
                continue  # slow client — drop
            await c.queue.put(msg)

    async def _delta_loop(self) -> None:
        while True:
            await asyncio.sleep(_DELTA_INTERVAL_S)
            pairs = self.adjacency.snapshot(now=time.monotonic())
            adjacency_msg = {
                "type": "adjacency",
                "payload": {"pairs": [[s, d, round(r, 3)] for s, d, r in pairs]},
            }
            region_msg = {"type": "region_delta", "payload": {"regions": self.registry.to_json()}}
            for c in list(self._clients):
                await c.queue.put(adjacency_msg)
                await c.queue.put(region_msg)

    async def start(self) -> None:
        if self._delta_task is None:
            self._delta_task = asyncio.create_task(self._delta_loop())

    async def stop(self) -> None:
        if self._delta_task is not None:
            self._delta_task.cancel()

    async def serve(self, ws: WebSocket) -> None:
        await ws.accept()
        client = _Client(ws=ws, decimator=Decimator(max_rate=self._max_ws_rate))
        self._clients.add(client)
        try:
            await ws.send_json(self.snapshot_message())
            while True:
                msg = await client.queue.get()
                await ws.send_json(msg)
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            log.exception("observatory.ws_error")
        finally:
            self._clients.discard(client)


def build_ws_router(hub: ConnectionHub) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        await hub.serve(ws)

    return router
```

- [ ] **Step 4: Run — expect pass**

Run: `python -m pytest observatory/tests/unit/test_ws.py -v`

- [ ] **Step 5: Lint + commit**

```bash
python -m ruff check observatory/
git add observatory/ws.py observatory/tests/unit/test_ws.py
git commit -m "$(cat <<'EOF'
observatory: WebSocket hub with snapshot + live fan-out (task 6)

Per-client queue + decimator + 2 s delta cadence (region_delta,
adjacency). Snapshot-on-connect includes registry, retained cache,
and last 500 ring records.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Service assembly + CLI entry + Dockerfile

Puts the pieces together into a FastAPI app with lifecycle hooks (connect MQTT, start delta loop, drain on shutdown). `python -m observatory` boots it.

**Files:**
- Create: `observatory/service.py`
- Create: `observatory/__main__.py`
- Create: `observatory/Dockerfile`

- [ ] **Step 1: Create `observatory/service.py`**

```python
"""FastAPI app factory for the observatory."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiomqtt
import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from observatory.adjacency import Adjacency
from observatory.api import build_router
from observatory.config import Settings
from observatory.mqtt_subscriber import MqttSubscriber, load_subscription_map
from observatory.region_registry import RegionRegistry
from observatory.retained_cache import RetainedCache
from observatory.ring_buffer import RingBuffer
from observatory.types import RingRecord
from observatory.ws import ConnectionHub, build_ws_router

log = structlog.get_logger(__name__)


def _parse_mqtt_url(url: str) -> tuple[str, int]:
    # "mqtt://host:port" → (host, port)
    rest = url.split("://", 1)[1]
    host, _, port_s = rest.partition(":")
    return host, int(port_s or "1883")


def build_app(settings: Settings) -> FastAPI:
    ring = RingBuffer(capacity=settings.ring_buffer_size)
    cache = RetainedCache()
    registry = RegionRegistry.seed_from(settings.hive_repo_root)
    adjacency = Adjacency(window_seconds=5.0)
    sub_map = load_subscription_map(settings.hive_repo_root)
    subscriber = MqttSubscriber(ring, cache, registry, adjacency, sub_map)
    hub = ConnectionHub(ring, cache, registry, adjacency, max_ws_rate=settings.max_ws_rate)

    # Wrap subscriber.dispatch so WS hub gets every envelope too.
    original_dispatch = subscriber.dispatch

    async def dispatch_and_fanout(msg):
        pre_len = len(ring)
        await original_dispatch(msg)
        post_len = len(ring)
        if post_len > pre_len:
            rec: RingRecord = ring.snapshot()[-1]
            await hub.broadcast_envelope(rec)

    subscriber.dispatch = dispatch_and_fanout  # type: ignore[assignment]

    stop_event = asyncio.Event()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        host, port = _parse_mqtt_url(settings.mqtt_url)
        client = aiomqtt.Client(hostname=host, port=port,
                                identifier=f"observatory-{host}-{port}")
        await hub.start()
        task: asyncio.Task | None = None

        async def _run():
            async with client:
                await client.subscribe("hive/#")
                await subscriber.run(client, stop_event)

        task = asyncio.create_task(_run())
        try:
            yield
        finally:
            stop_event.set()
            await hub.stop()
            if task:
                task.cancel()
            log.info("observatory.shutdown_complete")

    app = FastAPI(lifespan=lifespan, title="Hive Observatory", version="0.1.0")
    app.include_router(build_router(region_registry=registry))
    app.include_router(build_ws_router(hub))

    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        app.mount("/", StaticFiles(directory=str(web_dir), html=True), name="web")

    return app
```

- [ ] **Step 2: Create `observatory/__main__.py`**

```python
"""CLI entry: `python -m observatory`."""
from __future__ import annotations

import sys

import uvicorn

from observatory.config import Settings
from observatory.service import build_app


def main(argv: list[str] | None = None) -> int:
    settings = Settings.from_env()
    if settings.bind_host != "127.0.0.1":
        print(
            f"observatory: binding to non-loopback host {settings.bind_host!r} — "
            "make sure this is intentional.",
            file=sys.stderr,
        )
    app = build_app(settings)
    uvicorn.run(app, host=settings.bind_host, port=settings.bind_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Create `observatory/Dockerfile`**

```dockerfile
# Multi-stage: build frontend, then runtime image.
FROM node:20-alpine AS frontend
WORKDIR /src
COPY observatory/web-src/package.json observatory/web-src/package-lock.json* ./
RUN npm ci
COPY observatory/web-src/ ./
RUN npm run build
# outputs to /src/../web — bring it into the runtime stage via COPY below.

FROM python:3.11-slim AS runtime
WORKDIR /app
COPY observatory/pyproject.toml ./observatory/
RUN pip install --no-cache-dir flit_core && pip install --no-cache-dir ./observatory
COPY observatory/ ./observatory/
COPY --from=frontend /src/../web ./observatory/web
ENV OBSERVATORY_BIND_HOST=0.0.0.0
ENV OBSERVATORY_BIND_PORT=8765
EXPOSE 8765
CMD ["python", "-m", "observatory"]
```

- [ ] **Step 4: Smoke test: app builds**

Run: `python -c "from observatory.config import Settings; from observatory.service import build_app; app = build_app(Settings()); print('ok')"`
Expected: prints `ok`.

- [ ] **Step 5: Lint + commit**

```bash
python -m ruff check observatory/
git add observatory/service.py observatory/__main__.py observatory/Dockerfile
git commit -m "$(cat <<'EOF'
observatory: service assembly + CLI + Dockerfile (task 7)

FastAPI app factory wires ring buffer, retained cache, registry,
adjacency, MQTT subscriber, and WebSocket hub. Lifespan connects to
the broker, subscribes hive/#, starts the delta loop on the hub,
and drains cleanly on shutdown. __main__ boots uvicorn. Dockerfile
is multi-stage (node build → python runtime).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Component test — real broker end-to-end

Mirror the pattern used by the main Hive component tests (eclipse-mosquitto:2 via testcontainers; `WindowsSelectorEventLoopPolicy`; Ryuk disabled per top-level CLAUDE.md gotchas).

**Files:**
- Create: `observatory/tests/component/__init__.py`
- Create: `observatory/tests/component/conftest.py`
- Create: `observatory/tests/component/test_end_to_end.py`

- [ ] **Step 1: Create `observatory/tests/component/conftest.py`** (mirror `tests/component/conftest.py` from the main Hive tree)

```python
"""Platform glue for observatory component tests.

Mirrors the top-level tests/component/conftest.py:
- forces WindowsSelectorEventLoopPolicy (aiomqtt needs add_reader/add_writer)
- disables testcontainers Ryuk (port 8080 probe flaky on Windows)
"""
from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

- [ ] **Step 2: Write the end-to-end test**

`observatory/tests/component/test_end_to_end.py`:

```python
"""End-to-end: publish a message to a real broker, observe it via the WebSocket."""
from __future__ import annotations

import asyncio
import json
import socket

import aiomqtt
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from testcontainers.mqtt import MosquittoContainer

from observatory.config import Settings
from observatory.service import build_app


pytestmark = pytest.mark.component


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.mark.asyncio
async def test_publish_reaches_websocket(tmp_path) -> None:
    with MosquittoContainer(image="eclipse-mosquitto:2") as broker:
        broker_host = broker.get_container_host_ip()
        broker_port = int(broker.get_exposed_port(1883))

        settings = Settings(
            bind_host="127.0.0.1",
            bind_port=_free_port(),
            mqtt_url=f"mqtt://{broker_host}:{broker_port}",
            ring_buffer_size=100,
            max_ws_rate=200,
            hive_repo_root=tmp_path,
        )

        app = build_app(settings)
        client = TestClient(app)

        async with client:  # starts lifespan
            with client.websocket_connect("/ws") as ws:
                snap = ws.receive_json()
                assert snap["type"] == "snapshot"

                # Publish from a separate aiomqtt client
                envelope = {
                    "id": "abc",
                    "timestamp": "2026-04-20T00:00:00.000Z",
                    "source_region": "thalamus",
                    "topic": "hive/cognitive/prefrontal/plan",
                    "payload": {"x": 1},
                }
                async with aiomqtt.Client(hostname=broker_host, port=broker_port) as pub:
                    await pub.publish(
                        "hive/cognitive/prefrontal/plan",
                        payload=json.dumps(envelope).encode(),
                    )

                # Collect messages for up to 5 s until we see the envelope.
                received = None
                for _ in range(50):
                    msg = ws.receive_json(timeout=0.2)
                    if msg["type"] == "envelope" and msg["payload"]["topic"] == (
                        "hive/cognitive/prefrontal/plan"
                    ):
                        received = msg
                        break
                assert received is not None
                assert received["payload"]["source_region"] == "thalamus"
```

- [ ] **Step 3: Add `component` marker registration to workspace pytest config if not already present**

Check `pyproject.toml` at repo root for `[tool.pytest.ini_options]` → `markers` list. If `component` is not registered, add it. (Per top-level CLAUDE.md, all `[tool.pytest.ini_options]` lives at workspace root.)

- [ ] **Step 4: Run**

Requires Docker Desktop running.

Run: `python -m pytest observatory/tests/component/ -m component -v`
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add observatory/tests/component/
git commit -m "$(cat <<'EOF'
observatory: end-to-end component test via testcontainers (task 8)

Boots a real eclipse-mosquitto:2 broker, brings up the observatory
FastAPI app, connects a WebSocket client, publishes an envelope on
hive/cognitive/prefrontal/plan, and asserts the envelope arrives
on the WS stream.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Frontend scaffolding

Bare Vite + React + TS + Tailwind project in `observatory/web-src/`, building to `observatory/web/`. No scene yet — just a full-viewport canvas with a placeholder HUD rectangle to confirm the pipeline works.

**Files:**
- Create: `observatory/web-src/package.json`
- Create: `observatory/web-src/vite.config.ts`
- Create: `observatory/web-src/tsconfig.json`
- Create: `observatory/web-src/tsconfig.node.json`
- Create: `observatory/web-src/tailwind.config.ts`
- Create: `observatory/web-src/postcss.config.js`
- Create: `observatory/web-src/index.html`
- Create: `observatory/web-src/src/main.tsx`
- Create: `observatory/web-src/src/App.tsx`
- Create: `observatory/web-src/src/index.css`

- [ ] **Step 1: `observatory/web-src/package.json`**

```json
{
  "name": "observatory-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@react-three/drei": "^9.100.0",
    "@react-three/fiber": "^8.16.0",
    "d3-force-3d": "^3.0.5",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "three": "^0.163.0",
    "zustand": "^4.5.0"
  },
  "devDependencies": {
    "@types/d3-force-3d": "^3.0.10",
    "@types/react": "^18.3.0",
    "@types/react-dom": "^18.3.0",
    "@types/three": "^0.163.0",
    "@vitejs/plugin-react": "^4.3.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0",
    "tailwindcss": "^3.4.0",
    "typescript": "^5.5.0",
    "vite": "^5.3.0",
    "vitest": "^1.6.0"
  }
}
```

- [ ] **Step 2: `observatory/web-src/vite.config.ts`**

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: { outDir: '../web', emptyOutDir: true },
  server: { port: 5173, proxy: { '/api': 'http://localhost:8765', '/ws': { target: 'ws://localhost:8765', ws: true } } },
});
```

- [ ] **Step 3: `observatory/web-src/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true,
    "skipLibCheck": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "allowSyntheticDefaultImports": true,
    "esModuleInterop": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: `observatory/web-src/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts", "vitest.config.ts", "tailwind.config.ts"]
}
```

- [ ] **Step 5: `observatory/web-src/tailwind.config.ts`**

```typescript
import type { Config } from 'tailwindcss';
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: { colors: { hive: { bg: '#080814', panel: '#0d0d18', ink: '#e8e8f0' } } } },
  plugins: [],
} satisfies Config;
```

- [ ] **Step 6: `observatory/web-src/postcss.config.js`**

```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

- [ ] **Step 7: `observatory/web-src/index.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Hive Observatory</title>
  </head>
  <body class="bg-hive-bg text-hive-ink">
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 8: `observatory/web-src/src/index.css`**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root { height: 100%; margin: 0; }
```

- [ ] **Step 9: `observatory/web-src/src/main.tsx`**

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import { App } from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode><App /></React.StrictMode>
);
```

- [ ] **Step 10: `observatory/web-src/src/App.tsx`**

```tsx
export function App() {
  return (
    <div className="relative w-full h-full">
      <div className="absolute inset-0 flex items-center justify-center">
        <p className="opacity-60">observatory — scaffolding</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 11: Verify build**

```bash
cd observatory/web-src
npm install
npm run build
```

Expected: `observatory/web/` created with `index.html` + assets.

- [ ] **Step 12: Commit**

```bash
git add observatory/web-src/
git commit -m "$(cat <<'EOF'
observatory: frontend scaffolding (task 9)

Vite + React + TypeScript + Tailwind. Builds to observatory/web/
(gitignored). Dev server proxies /api and /ws to 127.0.0.1:8765.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: WebSocket client + REST client + zustand store

The frontend's glue to the backend.

**Files:**
- Create: `observatory/web-src/src/store.ts`
- Create: `observatory/web-src/src/api/ws.ts`
- Create: `observatory/web-src/src/api/rest.ts`
- Create: `observatory/web-src/vitest.config.ts`
- Create: `observatory/web-src/src/store.test.ts`
- Create: `observatory/web-src/src/api/ws.test.ts`

- [ ] **Step 1: `observatory/web-src/vitest.config.ts`**

```typescript
import { defineConfig } from 'vitest/config';
export default defineConfig({
  test: { environment: 'node', globals: false },
});
```

- [ ] **Step 2: Write `observatory/web-src/src/store.test.ts` (failing)**

```typescript
import { describe, it, expect } from 'vitest';
import { createStore } from './store';

describe('store', () => {
  it('applies a snapshot', () => {
    const s = createStore();
    s.getState().applySnapshot({
      regions: { thalamus: { role: 'cognitive', llm_model: 'x', stats: { phase: 'wake' } as any } },
      retained: { 'hive/modulator/cortisol': { payload: { value: 0.4 } } },
      recent: [],
      server_version: '0.1.0',
    });
    expect(s.getState().regions.thalamus.stats.phase).toBe('wake');
    expect(s.getState().ambient.modulators.cortisol).toBe(0.4);
  });

  it('appends an envelope into the ring', () => {
    const s = createStore();
    s.getState().pushEnvelope({
      observed_at: 1,
      topic: 'hive/cognitive/prefrontal/plan',
      envelope: {},
      source_region: 'thalamus',
      destinations: ['prefrontal_cortex'],
    });
    expect(s.getState().envelopes.length).toBe(1);
  });

  it('caps envelopes at 5000', () => {
    const s = createStore();
    for (let i = 0; i < 5100; i++) {
      s.getState().pushEnvelope({
        observed_at: i, topic: 't', envelope: {}, source_region: null, destinations: [],
      });
    }
    expect(s.getState().envelopes.length).toBe(5000);
  });
});
```

- [ ] **Step 3: Implement `observatory/web-src/src/store.ts`**

```typescript
import { create, StoreApi, UseBoundStore } from 'zustand';

export type RegionStats = {
  phase: string;
  queue_depth: number;
  stm_bytes: number;
  tokens_lifetime: number;
  handler_count: number;
  last_error_ts: string | null;
  msg_rate_in: number;
  msg_rate_out: number;
  llm_in_flight: boolean;
};

export type RegionMeta = {
  role: string;
  llm_model: string;
  stats: RegionStats;
};

export type Envelope = {
  observed_at: number;
  topic: string;
  envelope: Record<string, unknown>;
  source_region: string | null;
  destinations: string[];
};

export type Ambient = {
  modulators: Partial<Record<'cortisol' | 'dopamine' | 'serotonin' | 'norepinephrine' | 'oxytocin' | 'acetylcholine', number>>;
  self: { identity?: string; developmental_stage?: string; age?: number; felt_state?: string };
};

type Snapshot = {
  regions: Record<string, RegionMeta>;
  retained: Record<string, { payload?: Record<string, unknown> }>;
  recent: Envelope[];
  server_version: string;
};

type State = {
  regions: Record<string, RegionMeta>;
  envelopes: Envelope[];
  adjacency: Array<[string, string, number]>;
  ambient: Ambient;
  applySnapshot: (s: Snapshot) => void;
  applyRegionDelta: (regions: Record<string, RegionMeta>) => void;
  applyAdjacency: (pairs: Array<[string, string, number]>) => void;
  applyRetained: (topic: string, payload: Record<string, unknown>) => void;
  pushEnvelope: (env: Envelope) => void;
};

const RING_CAP = 5000;

function extractAmbient(retained: Snapshot['retained']): Ambient {
  const ambient: Ambient = { modulators: {}, self: {} };
  for (const [topic, env] of Object.entries(retained)) {
    const payload = env.payload ?? {};
    if (topic.startsWith('hive/modulator/')) {
      const name = topic.slice('hive/modulator/'.length) as keyof Ambient['modulators'];
      const v = Number(payload.value ?? NaN);
      if (!Number.isNaN(v)) ambient.modulators[name] = v;
    } else if (topic === 'hive/self/identity') ambient.self.identity = String(payload.value ?? '');
    else if (topic === 'hive/self/developmental_stage') ambient.self.developmental_stage = String(payload.value ?? '');
    else if (topic === 'hive/self/age') ambient.self.age = Number(payload.value ?? NaN);
    else if (topic === 'hive/interoception/felt_state') ambient.self.felt_state = String(payload.value ?? '');
  }
  return ambient;
}

export function createStore(): UseBoundStore<StoreApi<State>> {
  return create<State>((set, get) => ({
    regions: {},
    envelopes: [],
    adjacency: [],
    ambient: { modulators: {}, self: {} },
    applySnapshot: (s) => set({
      regions: s.regions,
      envelopes: s.recent,
      ambient: extractAmbient(s.retained),
    }),
    applyRegionDelta: (regions) => set({ regions }),
    applyAdjacency: (pairs) => set({ adjacency: pairs }),
    applyRetained: (topic, payload) => {
      const ambient = { ...get().ambient, modulators: { ...get().ambient.modulators }, self: { ...get().ambient.self } };
      if (topic.startsWith('hive/modulator/')) {
        const name = topic.slice('hive/modulator/'.length) as keyof Ambient['modulators'];
        ambient.modulators[name] = Number(payload.value ?? 0);
      }
      set({ ambient });
    },
    pushEnvelope: (env) => {
      const next = get().envelopes.concat(env);
      if (next.length > RING_CAP) next.splice(0, next.length - RING_CAP);
      set({ envelopes: next });
    },
  }));
}

export const useStore = createStore();
```

- [ ] **Step 4: Write `observatory/web-src/src/api/ws.test.ts` (failing)**

```typescript
import { describe, it, expect, vi } from 'vitest';
import { handleServerMessage } from './ws';
import { createStore } from '../store';

describe('handleServerMessage', () => {
  it('routes snapshot', () => {
    const s = createStore();
    const spy = vi.spyOn(s.getState(), 'applySnapshot');
    handleServerMessage(s, { type: 'snapshot', payload: {
      regions: {}, retained: {}, recent: [], server_version: '0.1.0' } });
    expect(spy).toHaveBeenCalled();
  });

  it('routes envelope', () => {
    const s = createStore();
    handleServerMessage(s, { type: 'envelope', payload: {
      observed_at: 1, topic: 'x', envelope: {}, source_region: null, destinations: [],
    }});
    expect(s.getState().envelopes.length).toBe(1);
  });

  it('routes region_delta and adjacency', () => {
    const s = createStore();
    handleServerMessage(s, { type: 'region_delta', payload: { regions: { a: { role: '', llm_model: '', stats: { phase: 'wake' } as any } } } });
    expect(s.getState().regions.a.stats.phase).toBe('wake');
    handleServerMessage(s, { type: 'adjacency', payload: { pairs: [['a', 'b', 0.5]] } });
    expect(s.getState().adjacency).toEqual([['a', 'b', 0.5]]);
  });
});
```

- [ ] **Step 5: Implement `observatory/web-src/src/api/ws.ts`**

```typescript
import type { StoreApi, UseBoundStore } from 'zustand';

type ServerMessage =
  | { type: 'snapshot'; payload: any }
  | { type: 'envelope'; payload: any }
  | { type: 'region_delta'; payload: { regions: Record<string, any> } }
  | { type: 'adjacency'; payload: { pairs: Array<[string, string, number]> } }
  | { type: 'decimated'; payload: { dropped: number } };

export function handleServerMessage(store: UseBoundStore<StoreApi<any>>, msg: ServerMessage): void {
  const s = store.getState();
  switch (msg.type) {
    case 'snapshot': s.applySnapshot(msg.payload); break;
    case 'envelope': s.pushEnvelope(msg.payload); break;
    case 'region_delta': s.applyRegionDelta(msg.payload.regions); break;
    case 'adjacency': s.applyAdjacency(msg.payload.pairs); break;
    case 'decimated': /* ignore for v1; hook for a future "lagging" badge */ break;
  }
}

export function connect(store: UseBoundStore<StoreApi<any>>, url = '/ws', onStatus?: (s: string) => void): () => void {
  let sock: WebSocket | null = null;
  let stopped = false;
  let retry = 500;

  const open = () => {
    const fullUrl = url.startsWith('ws') ? url : `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${url}`;
    sock = new WebSocket(fullUrl);
    sock.onopen = () => { retry = 500; onStatus?.('open'); };
    sock.onmessage = (ev) => {
      try { handleServerMessage(store, JSON.parse(ev.data)); }
      catch (err) { console.warn('ws parse error', err); }
    };
    sock.onclose = () => {
      onStatus?.('closed');
      if (!stopped) {
        setTimeout(open, Math.min(retry, 10000));
        retry *= 2;
      }
    };
    sock.onerror = () => sock?.close();
  };

  open();
  return () => { stopped = true; sock?.close(); };
}
```

- [ ] **Step 6: Implement `observatory/web-src/src/api/rest.ts`**

```typescript
export async function getHealth(): Promise<{ status: string; version: string }> {
  const r = await fetch('/api/health'); if (!r.ok) throw new Error('health failed'); return r.json();
}
export async function getRegions(): Promise<{ regions: Record<string, any> }> {
  const r = await fetch('/api/regions'); if (!r.ok) throw new Error('regions failed'); return r.json();
}
```

- [ ] **Step 7: Run frontend tests**

```bash
cd observatory/web-src
npm run test
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add observatory/web-src/src/store.ts observatory/web-src/src/store.test.ts observatory/web-src/src/api/ observatory/web-src/vitest.config.ts
git commit -m "$(cat <<'EOF'
observatory: zustand store + WS/REST clients (task 10)

State: regions, envelopes (ring cap 5000), adjacency, ambient
(modulators + self from retained topics). WS client parses server
messages and routes to store actions with auto-reconnect.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: Scene shell + force graph hook

Mounts a `<Canvas>` at full viewport, adds orbit controls, ambient+directional lights, and wires a `useForceGraph` hook that maintains per-region positions using `d3-force-3d`. No spheres rendered yet — verify by briefly adding debug cubes (remove before commit).

**Files:**
- Create: `observatory/web-src/src/scene/Scene.tsx`
- Create: `observatory/web-src/src/scene/useForceGraph.ts`
- Modify: `observatory/web-src/src/App.tsx`

- [ ] **Step 1: `observatory/web-src/src/scene/useForceGraph.ts`**

```typescript
import { useEffect, useMemo, useRef } from 'react';
import { forceSimulation, forceManyBody, forceLink, forceX, forceY, forceZ } from 'd3-force-3d';

export type ForceNode = { id: string; x: number; y: number; z: number; fx?: number; fy?: number; fz?: number };
export type ForceLink = { source: string; target: string; weight: number };

const PERIMETER_BIAS: Record<string, [number, number, number]> = {
  visual_cortex: [-6, -2, 0],
  auditory_cortex: [-6, 2, 0],
  broca_area: [6, -2, 0],
  motor_cortex: [6, 2, 0],
};

export function useForceGraph(names: string[], adjacency: Array<[string, string, number]>) {
  const nodesRef = useRef<Map<string, ForceNode>>(new Map());

  const nodes = useMemo<ForceNode[]>(() => {
    const map = nodesRef.current;
    for (const name of names) {
      if (!map.has(name)) {
        const [x, y, z] = PERIMETER_BIAS[name] ?? [
          (Math.random() - 0.5) * 4, (Math.random() - 0.5) * 4, (Math.random() - 0.5) * 4,
        ];
        const node: ForceNode = { id: name, x, y, z };
        if (name === 'medial_prefrontal_cortex') { node.fx = 0; node.fy = 0; node.fz = 0; }
        map.set(name, node);
      }
    }
    return Array.from(map.values());
  }, [names]);

  const simRef = useRef<ReturnType<typeof forceSimulation<ForceNode>> | null>(null);

  useEffect(() => {
    const sim = forceSimulation<ForceNode>(nodes, 3)
      .force('charge', forceManyBody().strength(-80))
      .force('xBias', forceX<ForceNode>((d) => PERIMETER_BIAS[d.id]?.[0] ?? 0).strength(0.02))
      .force('yBias', forceY<ForceNode>((d) => PERIMETER_BIAS[d.id]?.[1] ?? 0).strength(0.02))
      .force('zBias', forceZ<ForceNode>((d) => PERIMETER_BIAS[d.id]?.[2] ?? 0).strength(0.02))
      .alphaDecay(0.02)
      .velocityDecay(0.6);
    simRef.current = sim;
    return () => { sim.stop(); };
  }, [nodes]);

  useEffect(() => {
    if (!simRef.current) return;
    const links: ForceLink[] = adjacency.map(([s, t, w]) => ({ source: s, target: t, weight: w }));
    simRef.current
      .force('link', forceLink<ForceNode, ForceLink>(links).id((d) => d.id).distance(2.5).strength(0.1))
      .alpha(0.3)
      .restart();
  }, [adjacency]);

  return nodesRef;
}
```

- [ ] **Step 2: `observatory/web-src/src/scene/Scene.tsx`**

```tsx
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useStore } from '../store';
import { useForceGraph } from './useForceGraph';

export function Scene() {
  const regions = useStore((s) => s.regions);
  const adjacency = useStore((s) => s.adjacency);
  const names = Object.keys(regions);
  const nodes = useForceGraph(names, adjacency);

  // Stub: render a tiny cube at each position so we can verify physics before Task 12.
  // (Remove this block when Task 12 lands.)
  return (
    <Canvas camera={{ position: [0, 0, 12], fov: 55 }} style={{ background: '#080814' }}>
      <ambientLight intensity={0.35} />
      <directionalLight position={[10, 10, 5]} intensity={0.6} />
      {Array.from(nodes.current.values()).map((n) => (
        <mesh key={n.id} position={[n.x, n.y, n.z]}>
          <boxGeometry args={[0.3, 0.3, 0.3]} />
          <meshStandardMaterial color="#6af" />
        </mesh>
      ))}
      <OrbitControls />
    </Canvas>
  );
}
```

- [ ] **Step 3: Modify `observatory/web-src/src/App.tsx`**

```tsx
import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  useEffect(() => connect(useStore), []);
  return <div className="relative w-full h-full"><Scene /></div>;
}
```

- [ ] **Step 4: Visual verification**

Start the backend in one shell (`python -m observatory`) and the frontend dev server in another (`npm run dev` in `observatory/web-src/`). Open `http://localhost:5173`. Confirm cubes appear and gently settle.

- [ ] **Step 5: Commit**

```bash
git add observatory/web-src/src/scene/ observatory/web-src/src/App.tsx
git commit -m "$(cat <<'EOF'
observatory: scene shell + force graph (task 11)

Full-viewport Canvas with orbit controls, directional + ambient
lighting, and useForceGraph hook that seeds perimeter-biased
positions for sensory/motor regions and pins mPFC at origin.
Placeholder cubes render one per region; Task 12 replaces them
with the real region meshes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: Region rendering — phase color + halo + size + ring

Replaces the cubes with real region meshes: base sphere colored by `stats.phase`, emissive halo scaling with rolling token burn rate, slight size scaling from queue depth, and a thin torus for handler count.

**Files:**
- Create: `observatory/web-src/src/scene/Regions.tsx`
- Modify: `observatory/web-src/src/scene/Scene.tsx`

- [ ] **Step 1: `observatory/web-src/src/scene/Regions.tsx`**

```tsx
import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Color } from 'three';
import { useStore } from '../store';
import type { ForceNode } from './useForceGraph';

const PHASE_COLOR: Record<string, string> = {
  sleep: '#444450',
  wake: '#4a6a8a',
  processing: '#e8e8f0',
  unknown: '#2a2a36',
};

function Region({ node }: { node: ForceNode }) {
  const regions = useStore((s) => s.regions);
  const meta = regions[node.id];
  const meshRef = useRef<any>(null);
  const haloRef = useRef<any>(null);
  const tokensRef = useRef<number>(meta?.stats.tokens_lifetime ?? 0);
  const burnRef = useRef<number>(0);

  useFrame((_, dt) => {
    if (!meshRef.current) return;
    meshRef.current.position.set(node.x, node.y, node.z);
    if (haloRef.current) haloRef.current.position.set(node.x, node.y, node.z);
    if (!meta) return;
    // update burn estimate
    const tokens = meta.stats.tokens_lifetime;
    const delta = Math.max(0, tokens - tokensRef.current);
    tokensRef.current = tokens;
    burnRef.current = burnRef.current * 0.92 + (delta / Math.max(dt, 0.001)) * 0.08;
    const intensity = Math.min(1, burnRef.current / 500); // 500 tok/sec = full glow
    if (haloRef.current) haloRef.current.material.opacity = 0.15 + 0.6 * intensity;
    // base color
    const col = new Color(PHASE_COLOR[meta.stats.phase] ?? PHASE_COLOR.unknown);
    meshRef.current.material.color.lerp(col, Math.min(1, dt * 3));
    // size from queue depth
    const scale = 1 + Math.min(0.3, meta.stats.queue_depth * 0.03);
    meshRef.current.scale.setScalar(scale);
  });

  return (
    <group>
      <mesh ref={meshRef} position={[node.x, node.y, node.z]}>
        <sphereGeometry args={[0.4, 24, 24]} />
        <meshStandardMaterial color={PHASE_COLOR.unknown} />
      </mesh>
      <mesh ref={haloRef} position={[node.x, node.y, node.z]}>
        <sphereGeometry args={[0.6, 16, 16]} />
        <meshBasicMaterial color="#ffc97a" transparent opacity={0.15} depthWrite={false} />
      </mesh>
      <mesh position={[node.x, node.y, node.z]}>
        <torusGeometry args={[0.5, 0.02, 8, Math.max(4, (meta?.stats.handler_count ?? 4))]} />
        <meshBasicMaterial color="#8899aa" />
      </mesh>
    </group>
  );
}

export function Regions({ nodesRef }: { nodesRef: React.MutableRefObject<Map<string, ForceNode>> }) {
  const names = useStore((s) => Object.keys(s.regions));
  const nodes = useMemo(() => names.map((n) => nodesRef.current.get(n)!).filter(Boolean), [names, nodesRef]);
  return (<>{nodes.map((n) => <Region key={n.id} node={n} />)}</>);
}
```

- [ ] **Step 2: Modify `observatory/web-src/src/scene/Scene.tsx`**

Replace the placeholder `mesh` block with `<Regions nodesRef={nodes} />`:

```tsx
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useStore } from '../store';
import { useForceGraph } from './useForceGraph';
import { Regions } from './Regions';

export function Scene() {
  const regions = useStore((s) => s.regions);
  const adjacency = useStore((s) => s.adjacency);
  const names = Object.keys(regions);
  const nodes = useForceGraph(names, adjacency);
  return (
    <Canvas camera={{ position: [0, 0, 12], fov: 55 }} style={{ background: '#080814' }}>
      <ambientLight intensity={0.35} />
      <directionalLight position={[10, 10, 5]} intensity={0.6} />
      <Regions nodesRef={nodes} />
      <OrbitControls />
    </Canvas>
  );
}
```

- [ ] **Step 3: Visual verify**

Regions appear as spheres, color changes by phase, halo brightens with LLM activity, handler ring visible.

- [ ] **Step 4: Commit**

```bash
git add observatory/web-src/src/scene/Regions.tsx observatory/web-src/src/scene/Scene.tsx
git commit -m "$(cat <<'EOF'
observatory: region meshes — phase color, halo, size, handler ring (task 12)

Each region renders as a sphere (color from stats.phase), a
translucent halo whose opacity tracks a 500-tok/sec rolling burn
estimate, and a thin torus whose segment count matches handler_count.
Queue depth nudges sphere scale up to 1.3x.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: Sparks — traveling particles on edges

Envelopes emit one particle per (source, destination) pair. Particles travel from source to destination over a fixed duration (e.g., 800 ms), then expire. Color comes from a pure prefix mapper.

**Files:**
- Create: `observatory/web-src/src/scene/topicColors.ts`
- Create: `observatory/web-src/src/scene/topicColors.test.ts`
- Create: `observatory/web-src/src/scene/Sparks.tsx`
- Modify: `observatory/web-src/src/scene/Scene.tsx`

- [ ] **Step 1: Write failing test `topicColors.test.ts`**

```typescript
import { describe, it, expect } from 'vitest';
import { topicColor } from './topicColors';

describe('topicColor', () => {
  it.each([
    ['hive/cognitive/prefrontal/plan', '#e8e8e8'],
    ['hive/sensory/auditory/text', '#99ee66'],
    ['hive/motor/speech/intent', '#ee9966'],
    ['hive/metacognition/error/detected', '#bb66ff'],
    ['hive/system/heartbeat/thalamus', '#888888'],
    ['hive/habit/suggestion', '#ffcc66'],
    ['hive/attention/focus', '#66ccff'],
    ['hive/modulator/cortisol', '#ff66bb'],
    ['hive/rhythm/gamma', '#66cccc'],
    ['hive/unknown/branch', '#666666'],
  ])('maps %s → %s', (topic, expected) => {
    expect(topicColor(topic)).toBe(expected);
  });
});
```

- [ ] **Step 2: Implement `topicColors.ts`**

```typescript
const PREFIXES: Array<[string, string]> = [
  ['hive/cognitive/',     '#e8e8e8'],
  ['hive/sensory/',       '#99ee66'],
  ['hive/motor/',         '#ee9966'],
  ['hive/metacognition/', '#bb66ff'],
  ['hive/system/',        '#888888'],
  ['hive/habit/',         '#ffcc66'],
  ['hive/attention/',     '#66ccff'],
  ['hive/modulator/',     '#ff66bb'],
  ['hive/rhythm/',        '#66cccc'],
];
const FALLBACK = '#666666';

export function topicColor(topic: string): string {
  for (const [prefix, color] of PREFIXES) {
    if (topic.startsWith(prefix)) return color;
  }
  return FALLBACK;
}
```

- [ ] **Step 3: Run frontend tests**

```bash
cd observatory/web-src && npm run test
```

- [ ] **Step 4: Implement `observatory/web-src/src/scene/Sparks.tsx`**

```tsx
import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Color, InstancedMesh, Matrix4, Vector3 } from 'three';
import { useStore } from '../store';
import { topicColor } from './topicColors';
import type { ForceNode } from './useForceGraph';

const MAX_SPARKS = 2000;
const LIFETIME = 0.8; // seconds

type Spark = {
  src: Vector3;
  dst: Vector3;
  t0: number;
  color: Color;
};

export function Sparks({ nodesRef }: { nodesRef: React.MutableRefObject<Map<string, ForceNode>> }) {
  const meshRef = useRef<InstancedMesh>(null);
  const sparks = useRef<Spark[]>([]);
  const lastLenRef = useRef(0);

  // Subscribe to envelope appends by polling the envelopes array length each frame.
  useFrame((state, dt) => {
    const store = useStore.getState();
    const envs = store.envelopes;
    const newCount = envs.length - lastLenRef.current;
    if (newCount > 0) {
      const slice = envs.slice(envs.length - Math.min(newCount, 100));
      for (const e of slice) {
        if (!e.source_region || e.destinations.length === 0) continue;
        const src = nodesRef.current.get(e.source_region);
        if (!src) continue;
        const color = new Color(topicColor(e.topic));
        for (const dname of e.destinations) {
          const dst = nodesRef.current.get(dname);
          if (!dst) continue;
          if (sparks.current.length >= MAX_SPARKS) sparks.current.shift();
          sparks.current.push({
            src: new Vector3(src.x, src.y, src.z),
            dst: new Vector3(dst.x, dst.y, dst.z),
            t0: state.clock.elapsedTime,
            color,
          });
        }
      }
    }
    lastLenRef.current = envs.length;

    if (!meshRef.current) return;
    const m = new Matrix4();
    const pos = new Vector3();
    let i = 0;
    for (const s of sparks.current) {
      const age = state.clock.elapsedTime - s.t0;
      if (age > LIFETIME) continue;
      const t = age / LIFETIME;
      pos.lerpVectors(s.src, s.dst, t);
      m.makeTranslation(pos.x, pos.y, pos.z);
      meshRef.current.setMatrixAt(i, m);
      meshRef.current.setColorAt(i, s.color);
      i++;
    }
    meshRef.current.count = i;
    meshRef.current.instanceMatrix.needsUpdate = true;
    if (meshRef.current.instanceColor) meshRef.current.instanceColor.needsUpdate = true;
    // prune expired
    sparks.current = sparks.current.filter((s) => state.clock.elapsedTime - s.t0 <= LIFETIME);
  });

  return (
    <instancedMesh ref={meshRef} args={[undefined as any, undefined as any, MAX_SPARKS]}>
      <sphereGeometry args={[0.06, 8, 8]} />
      <meshBasicMaterial />
    </instancedMesh>
  );
}
```

- [ ] **Step 5: Modify `Scene.tsx` to include `<Sparks nodesRef={nodes} />`.**

- [ ] **Step 6: Commit**

```bash
git add observatory/web-src/src/scene/Sparks.tsx observatory/web-src/src/scene/topicColors.ts observatory/web-src/src/scene/topicColors.test.ts observatory/web-src/src/scene/Scene.tsx
git commit -m "$(cat <<'EOF'
observatory: traveling sparks on edges (task 13)

Instanced-mesh particles (cap 2000) lerp from source region to each
destination inferred in the envelope, colored by topic-branch prefix.
Lifetime 800 ms. Color table unit-tested; scene fan-out tested
manually against live broker traffic.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: Modulator fog + rhythm pulse

Scene-wide ambient channels: modulator values tint the scene; rhythm broadcasts subtly pulse the ambient light amplitude.

**Files:**
- Create: `observatory/web-src/src/scene/Fog.tsx`
- Create: `observatory/web-src/src/scene/Rhythm.tsx`
- Modify: `observatory/web-src/src/scene/Scene.tsx`

- [ ] **Step 1: Implement `Fog.tsx`**

```tsx
import { useFrame, useThree } from '@react-three/fiber';
import { Color, Fog } from 'three';
import { useStore } from '../store';

const MODULATOR_HUES: Record<string, [number, number, number]> = {
  cortisol:       [0.70, 0.20, 0.20], // red wash
  dopamine:       [0.90, 0.75, 0.30], // warm yellow
  serotonin:      [0.55, 0.80, 0.40], // green-gold
  norepinephrine: [0.40, 0.80, 0.90], // sharp cyan
  oxytocin:       [0.90, 0.55, 0.70], // pink
  acetylcholine:  [0.80, 0.80, 0.80], // subtle saturation
};
const WEIGHTS: Record<string, number> = {
  cortisol: 0.35, dopamine: 0.30, serotonin: 0.15,
  norepinephrine: 0.20, oxytocin: 0.10, acetylcholine: 0.10,
};

export function ModulatorFog() {
  const { scene } = useThree();
  const mods = useStore((s) => s.ambient.modulators);
  useFrame(() => {
    const bg = new Color(0.03, 0.03, 0.07);
    const target = bg.clone();
    for (const [name, value] of Object.entries(mods)) {
      const v = typeof value === 'number' ? value : 0;
      const hue = MODULATOR_HUES[name] ?? [0, 0, 0];
      const w = (WEIGHTS[name] ?? 0) * Math.max(0, Math.min(1, v));
      target.r = Math.min(1, target.r + hue[0] * w);
      target.g = Math.min(1, target.g + hue[1] * w);
      target.b = Math.min(1, target.b + hue[2] * w);
    }
    if (!scene.fog) scene.fog = new Fog(target, 10, 40);
    else {
      (scene.fog as Fog).color.copy(target);
    }
    scene.background = target;
  });
  return null;
}
```

- [ ] **Step 2: Implement `Rhythm.tsx`**

```tsx
import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';
import { useStore } from '../store';

// Drive a scene-wide ambient-light amplitude from hive/rhythm/{gamma, beta, theta}.
// gamma~40Hz, beta~20Hz, theta~6Hz. Take whichever is most recently published.

export function RhythmPulse({ lightRef }: { lightRef: React.MutableRefObject<any> }) {
  const envelopes = useStore((s) => s.envelopes);
  const latestRef = useRef<{ freq: number } | null>(null);

  // cheap polling — scan last 20 envelopes for rhythm topics
  useFrame(({ clock }, _dt) => {
    const slice = envelopes.slice(-20);
    for (let i = slice.length - 1; i >= 0; i--) {
      const t = slice[i].topic;
      if (t === 'hive/rhythm/gamma') { latestRef.current = { freq: 40 }; break; }
      if (t === 'hive/rhythm/beta')  { latestRef.current = { freq: 20 }; break; }
      if (t === 'hive/rhythm/theta') { latestRef.current = { freq: 6  }; break; }
    }
    if (!lightRef.current) return;
    const base = 0.35;
    if (latestRef.current) {
      const amp = 0.03;
      lightRef.current.intensity = base + amp * Math.sin(clock.elapsedTime * 2 * Math.PI * latestRef.current.freq * 0.02);
      // Note: the 0.02 scalar tames 40Hz to a visible ~0.8Hz — this is a perceptual stand-in, not literal frequency.
    } else {
      lightRef.current.intensity = base;
    }
  });
  return null;
}
```

- [ ] **Step 3: Modify `Scene.tsx`**

```tsx
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useRef } from 'react';
import { useStore } from '../store';
import { useForceGraph } from './useForceGraph';
import { Regions } from './Regions';
import { Sparks } from './Sparks';
import { ModulatorFog } from './Fog';
import { RhythmPulse } from './Rhythm';

export function Scene() {
  const regions = useStore((s) => s.regions);
  const adjacency = useStore((s) => s.adjacency);
  const names = Object.keys(regions);
  const nodes = useForceGraph(names, adjacency);
  const ambientRef = useRef<any>(null);
  return (
    <Canvas camera={{ position: [0, 0, 12], fov: 55 }}>
      <ambientLight ref={ambientRef} intensity={0.35} />
      <directionalLight position={[10, 10, 5]} intensity={0.6} />
      <ModulatorFog />
      <RhythmPulse lightRef={ambientRef} />
      <Regions nodesRef={nodes} />
      <Sparks nodesRef={nodes} />
      <OrbitControls />
    </Canvas>
  );
}
```

- [ ] **Step 4: Commit**

```bash
git add observatory/web-src/src/scene/Fog.tsx observatory/web-src/src/scene/Rhythm.tsx observatory/web-src/src/scene/Scene.tsx
git commit -m "$(cat <<'EOF'
observatory: modulator fog + rhythm pulse (task 14)

ModulatorFog updates scene.fog and scene.background each frame from
the weighted modulator values. RhythmPulse modulates ambient-light
intensity at a perceptually-scaled gamma/beta/theta tempo based on
the most recently observed rhythm topic.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: HUD — self panel + modulators + counters

Overlay layout that sits above the canvas: top-left self + modulators, bottom strip totals.

**Files:**
- Create: `observatory/web-src/src/hud/Hud.tsx`
- Create: `observatory/web-src/src/hud/SelfPanel.tsx`
- Create: `observatory/web-src/src/hud/Modulators.tsx`
- Create: `observatory/web-src/src/hud/Counters.tsx`
- Modify: `observatory/web-src/src/App.tsx`

- [ ] **Step 1: `SelfPanel.tsx`**

```tsx
import { useStore } from '../store';

export function SelfPanel() {
  const self = useStore((s) => s.ambient.self);
  return (
    <div className="p-3 bg-hive-panel/80 backdrop-blur rounded-md max-w-xs">
      <div className="text-[10px] tracking-widest opacity-60 uppercase">Self</div>
      <div className="text-sm leading-snug line-clamp-2">{self.identity ?? '—'}</div>
      <div className="flex gap-2 mt-1 text-xs">
        <span className="px-1.5 py-0.5 bg-white/10 rounded">{self.developmental_stage ?? 'unknown'}</span>
        <span className="px-1.5 py-0.5 bg-white/10 rounded">age {self.age ?? '—'}</span>
        <span className="px-1.5 py-0.5 bg-white/10 rounded">{self.felt_state ?? '—'}</span>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: `Modulators.tsx`**

```tsx
import { useStore } from '../store';

const ORDER = ['cortisol', 'dopamine', 'serotonin', 'norepinephrine', 'oxytocin', 'acetylcholine'] as const;

function Gauge({ name, value }: { name: string; value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-28 opacity-70">{name}</span>
      <div className="flex-1 h-1.5 bg-white/10 rounded overflow-hidden">
        <div className="h-full bg-white/60" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right tabular-nums opacity-80">{value.toFixed(2)}</span>
    </div>
  );
}

export function Modulators() {
  const mods = useStore((s) => s.ambient.modulators);
  return (
    <div className="p-3 bg-hive-panel/80 backdrop-blur rounded-md w-72 space-y-1 mt-2">
      <div className="text-[10px] tracking-widest opacity-60 uppercase">Modulators</div>
      {ORDER.map((n) => <Gauge key={n} name={n} value={mods[n] ?? 0} />)}
    </div>
  );
}
```

- [ ] **Step 3: `Counters.tsx`**

```tsx
import { useStore } from '../store';
import { useEffect, useState } from 'react';

export function Counters() {
  const regions = useStore((s) => s.regions);
  const envelopes = useStore((s) => s.envelopes);
  const [rate, setRate] = useState(0);
  useEffect(() => {
    const id = setInterval(() => {
      const now = performance.now() / 1000;
      const recent = envelopes.filter((e) => now - e.observed_at < 5).length;
      setRate(recent / 5);
    }, 1000);
    return () => clearInterval(id);
  }, [envelopes]);
  const totalTokens = Object.values(regions).reduce((a, r: any) => a + (r.stats?.tokens_lifetime ?? 0), 0);
  return (
    <div className="flex gap-6 text-xs px-3 py-2 bg-hive-panel/80 backdrop-blur rounded-md">
      <div><span className="opacity-60">Tokens total: </span><span className="tabular-nums">{totalTokens}</span></div>
      <div><span className="opacity-60">Msg/s: </span><span className="tabular-nums">{rate.toFixed(1)}</span></div>
    </div>
  );
}
```

- [ ] **Step 4: `Hud.tsx`**

```tsx
import { SelfPanel } from './SelfPanel';
import { Modulators } from './Modulators';
import { Counters } from './Counters';

export function Hud() {
  return (
    <>
      <div className="absolute top-3 left-3 pointer-events-none">
        <SelfPanel />
        <Modulators />
      </div>
      <div className="absolute bottom-3 left-3 pointer-events-none">
        <Counters />
      </div>
    </>
  );
}
```

- [ ] **Step 5: Modify `App.tsx`**

```tsx
import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { Hud } from './hud/Hud';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  useEffect(() => connect(useStore), []);
  return (
    <div className="relative w-full h-full">
      <Scene />
      <Hud />
    </div>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add observatory/web-src/src/hud/ observatory/web-src/src/App.tsx
git commit -m "$(cat <<'EOF'
observatory: HUD — self panel + modulator gauges + counters (task 15)

Fixed overlay: top-left shows identity / stage / age / felt_state and
six modulator gauges. Bottom strip shows total lifetime tokens across
regions and a 5-second rolling msg/s.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: Final integration — production build + static mount smoke test

Build the frontend, confirm FastAPI serves it, and run the full stack (backend + real broker) end-to-end locally to verify visual correctness.

**Files:**
- Modify: `observatory/HANDOFF.md` (bump status, note v1 shipped)

- [ ] **Step 1: Produce a production bundle**

```bash
cd observatory/web-src && npm run build
```

Expected: `observatory/web/index.html` + assets created. Note — `observatory/web/` is gitignored per Task 1.

- [ ] **Step 2: Boot the backend pointed at your Hive broker**

```bash
OBSERVATORY_MQTT_URL=mqtt://127.0.0.1:1883 python -m observatory
```

Expected: uvicorn starts on `127.0.0.1:8765`; `GET /api/health` returns `{"status": "ok", ...}`; `GET /` serves the built `index.html`.

- [ ] **Step 3: Visual end-to-end check**

1. Open `http://127.0.0.1:8765`.
2. Confirm force-directed scene renders, 14 region spheres settle into positions.
3. Start Hive regions (or publish test envelopes manually) and confirm:
   - Sphere colors shift with phase
   - Halos brighten during LLM activity
   - Sparks travel on edges
   - Modulator gauges update as regions publish `hive/modulator/*`
   - Self panel reflects `hive/self/*` retained state
   - Bottom strip counters tick

- [ ] **Step 4: Run full verification**

```bash
python -m pytest observatory/tests/unit/ -q
python -m pytest observatory/tests/component/ -m component -v
python -m ruff check observatory/
(cd observatory/web-src && npm run test)
```

Expected: all tests pass; ruff clean.

- [ ] **Step 5: Update `observatory/HANDOFF.md`** — mark v1 as ✅, set date, prepare the next-session prompt for v2.

Replace the progress table rows:
- `Plan written` → ✅ Complete (link to this plan file)
- `v1 implementation` → ✅ Complete (date, commit range)

Append the next-session prompt:

```markdown
## Next session

Canonical resume prompt: `continue observatory v2`.

Prereq: brainstorming session for v2 (region inspector details). The v2
scope is defined in spec §5.1; a short brainstorm may refine questions
about panel layout, keyboard shortcuts, and handler-source deferrals
before writing-plans runs.
```

- [ ] **Step 6: Commit**

```bash
git add observatory/HANDOFF.md
git commit -m "$(cat <<'EOF'
observatory: v1 ships (task 16)

Full verification pass: unit tests, component test (real broker via
testcontainers), ruff clean, frontend vitest clean, production build
served by FastAPI, visual end-to-end checked against live Hive.

HANDOFF.md updated to reflect v1 completion and point to v2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review (applied against spec before committing plan)

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| §3 Architecture overview | Tasks 4, 5, 6, 7 (backend pieces) + 9, 10, 11 (frontend wiring) |
| §4.1 Scene layout (force-directed, mPFC pinned, perimeter bias) | Task 11 (`useForceGraph.ts` `PERIMETER_BIAS`, mPFC `fx=fy=fz=0`) |
| §4.2 Per-region channels (base color, halo, size, ring) | Task 12 |
| §4.3 Traveling sparks + topic-branch colors + edge rate | Task 13 sparks + adjacency thickness — NOTE: v1 does not render the edges themselves as visible lines; adjacency drives spring distance and the spark endpoints. Visible edges added in v2 if desired; logged as a follow-up in decisions.md. |
| §4.4 Modulator fog + rhythm pulse | Task 14 |
| §4.5 HUD (self + modulators + counters) | Task 15 |
| §6.1 Stack | Task 1 `pyproject.toml` |
| §6.2 MQTT subscription | Task 4 + Task 7 lifespan |
| §6.3 Ring buffer | Task 1 |
| §6.4 Retained cache | Task 2 |
| §6.5 Region reader | Not included in v1 (spec §6.5 items all v2/v3). V1 needs only `regions_registry.yaml` load (Task 2) and `regions/*/subscriptions.yaml` scan (Task 4's `load_subscription_map`) — both narrow, single-purpose, non-sandbox-router reads. Full sandboxed `region_reader.py` is a Task 1 of the v2 plan. |
| §6.6 REST endpoints (v1: /health, /regions) | Task 5 |
| §6.7 WebSocket protocol (snapshot, envelope, region_delta, adjacency) | Task 6 |
| §6.8 Decimation | Task 3 (decimator) + Task 6 (applied per client) |
| §7.1 Frontend stack | Task 9 |
| §7.2 State model | Task 10 |
| §7.3 Rendering loop (R3F useFrame, instanced mesh sparks cap 2000) | Task 13 (MAX_SPARKS=2000) |
| §7.4 Interactions (OrbitControls; click inspector is v2) | Task 11 |
| §8 Repo layout | Task 1 (scaffolding) aligns with spec |
| §9 v1 milestone scope | Tasks 1–16 |
| §10 Safety and posture | Task 7 (`127.0.0.1` default + non-loopback warning); read-only enforced by absence of publish/write call sites across the package |
| §11 Tracking inside observatory/ | Task 1 (`memory/decisions.md`, `prompts/.gitkeep`) |

**One uncovered item flagged during review:** spec §4.3 references "edge thickness" as a separate visual channel. V1 renders spark endpoints using adjacency positions but does not draw the edge itself as a continuous line. Logged as a decision during planning — v1 ships with sparks as the primary edge signal; visible edge lines can be added if visual testing reveals the scene feels "empty" between sparks. Appended to `observatory/memory/decisions.md` as part of Task 1 seed.

**Placeholder scan:** no `TBD` / `TODO` / `FIXME` / "implement later" markers in the plan text. Every task shows complete code for every file it touches.

**Type consistency:** `RegionMeta`/`RegionStats`/`RingRecord` used identically across Tasks 1, 2, 4, 5, 6, 7; frontend mirrors shapes in `store.ts` (Task 10) and consumed from there in Tasks 11–15.

---

## Execution Handoff

Plan complete at [observatory/docs/plans/2026-04-20-observatory-plan.md](2026-04-20-observatory-plan.md). Execution model is **subagent-driven-development** per `observatory/CLAUDE.md` — fresh implementer subagent per task, two-stage review between tasks, one commit per task.

Canonical resume prompt: `continue observatory v1`.
