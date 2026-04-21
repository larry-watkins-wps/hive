# Observatory — Design Spec

*Status: Approved 2026-04-20*
*Owner: Larry Watkins*
*Scope: Hive v0+, initial target v1*

---

## 1. Purpose

A 3D visual instrument for watching Hive think. Primary use case: "consciousness monitor" — something you leave running to see regions activate, messages travel, and modulators wash the scene as Hive processes input. Secondary use case: drill down into a single region to understand why it did what it did.

The observatory is an **instrument**, not a participant. It reads from MQTT and from region filesystems. It never publishes into Hive's topic space and never writes to Hive files. A bug in the observatory cannot corrupt Hive state.

## 2. Scope boundary and invariants

**In scope:**

- Subscribing read-only to `hive/#` on the Hive MQTT broker.
- Reading region filesystem artifacts (`regions/<name>/prompt.md`, `memory/stm.json`, `memory/ltm/*`, `subscriptions.yaml`, `config.yaml`, `handlers/`, `.git/` log) via a path-sandboxed reader.
- Presenting a live 3D scene of the 14 regions, message traffic between them, modulator atmosphere, and rhythm timing.
- A region inspector panel reachable by zooming into one region.

**Out of scope (forever):**

- Writing to MQTT — the observatory does not publish. Optional `hive/observatory/heartbeat` may be added later for glia liveness tracking, but is explicitly not part of v1–v3.
- Writing to region filesystems.
- Controls that mutate Hive (no kill/restart/spawn buttons). Glia owns control; the observatory owns observation.
- Multi-user / auth. Localhost-only; bound to `127.0.0.1` by default.
- Persistent historical storage beyond the in-memory ring buffer. Long-term logs belong to Grafana/Loki.
- Mobile / tablet layouts. Desktop 3D only.

**Constitutional alignment:**

The observatory sits outside Hive's biological model (Principle I). It is the neuroscientist's microscope, not an organ. This is why it may read files — it is not a region, and Principle II's "all inter-region communication over MQTT" does not apply to an external observer reading the substrate. The observatory does not participate in cognition, does not deliberate, does not persist identity.

## 3. Architecture overview

```
┌──────────────────────────────────────────────────────────────┐
│                         Hive                                 │
│   14 regions  ──────► MQTT broker  ◄────── glia              │
│      │                    ▲                                  │
│      │ filesystem         │ subscribe hive/#                 │
│      ▼                    │                                  │
│   regions/<name>/         │                                  │
│     prompt.md             │                                  │
│     memory/stm.json       │                                  │
│     subscriptions.yaml    │                                  │
└──────────┬────────────────┼──────────────────────────────────┘
           │ read           │ read
           │                │
    ┌──────▼────────────────▼──────────────┐
    │  observatory/  (Python + FastAPI)    │
    │                                       │
    │    region_reader.py  ring_buffer.py   │
    │    service.py        (aiomqtt)        │
    │                                       │
    │    WebSocket  ── live envelopes + deltas
    │    REST       ── on-demand file reads │
    │    Static     ── /web (vite bundle)   │
    └──────────────────┬────────────────────┘
                       │  HTTP / WS
                       ▼
              ┌─────────────────┐
              │  Browser (SPA)  │
              │  React + R3F    │
              │  3D scene + HUD │
              └─────────────────┘
```

## 4. Visual vocabulary

### 4.1 Scene layout

Force-directed 3D graph via `d3-force-3d`:

- **mPFC pinned at origin.** `fx=fy=fz=0`. Hive's narrative self is the center of the scene.
- **Sensory and motor regions biased to perimeter positions.** Custom `forceX/Y/Z` per region pulls each toward a target `(x, y, z)`. This keeps hardware-adjacent regions at predictable "ports" while still allowing gentle drift.
- **All other regions float free.** Many-body repulsion plus link forces from the current message-rate adjacency matrix. Chatty pairs pull closer.
- **Spring constants tuned for calm motion.** `alphaDecay ≈ 0.02`, `velocityDecay ≈ 0.6`. Motion should feel like a slow jellyfish, not a seizure.
- **Link force recomputed on a cadence.** Every 2 s, the adjacency matrix is updated from the rolling message-rate view; springs retarget with a smooth transition rather than snapping.

### 4.2 Per-region visual channels

Each region is a sphere mesh. The following channels layer on the sphere:

| Channel | Source | Visual |
|---|---|---|
| Base color | `hive/system/heartbeat/<region>` → `state.phase` | Cool gray (sleep) · muted blue (wake/idle) · warm white (processing) |
| Halo / glow | Derived: heartbeat `llm_tokens_used_lifetime` delta + inferred "LLM call in flight" | Pulsing emissive ring; intensity scales with rolling token-burn rate |
| Size | `queue_depth_messages` from heartbeat | Mild scale nudge (1.0× at 0, 1.3× at ≥10). Avoids dramatic resizing. |
| Ring | `handler_count` from heartbeat | Thin torus around the sphere, subdivisions = handler count. Educational only; rarely changes. |

### 4.3 Inter-region channels

- **Traveling sparks on edges.** Every published message on a routable topic produces a small particle traveling along the edge from source region to destination region(s), using the same physics as the force graph's link positions. Color by topic branch:

  | Topic prefix | Color |
  |---|---|
  | `hive/cognitive/*` | `#e8e8e8` (bright white) |
  | `hive/sensory/*` | `#9e6` (green) |
  | `hive/motor/*` | `#e96` (orange) |
  | `hive/metacognition/*` | `#b6f` (purple) |
  | `hive/system/*` | `#888` (gray, subtle) |
  | `hive/habit/*` | `#fc6` (gold) |
  | `hive/attention/*` | `#6cf` (cyan) |

- **Edge thickness.** Continuous rolling rate (msgs/sec, 5-second window) between each region pair. Log-scale mapping to thickness keeps a 100:1 rate range legible.

- **Fan-out resolution.** For topics with multiple subscribers, the source publishes one spark per destination. The observatory knows the subscriber set from either the `subscriptions.yaml` snapshot (preferred) or from observed delivery patterns (fallback if snapshots stale).

### 4.4 Ambient channels (scene-wide)

- **Modulator fog.** Semi-transparent scene-wide tint. Hex values blended from current retained `hive/modulator/*`:

  - `cortisol` → reddish wash (weight 0.35 at value 1.0)
  - `dopamine` → warm yellow lift (weight 0.30 at value 1.0)
  - `serotonin` → soft green-gold (weight 0.15 at value 1.0)
  - `norepinephrine` → sharp cyan edge-light (weight 0.20 at value 1.0)
  - `oxytocin` → pink undertone (weight 0.10 at value 1.0)
  - `acetylcholine` → subtle saturation boost (weight 0.10 at value 1.0)

  Implemented via `<fog>` in `@react-three/fiber` plus a tone-mapping pass.

- **Rhythm pulse.** `hive/rhythm/{gamma, beta, theta}` broadcasts drive a subtle (±3%) modulation on scene ambient light amplitude at their respective frequencies. Intended to be almost subliminal — noticeable only with attention.

### 4.5 HUD (heads-up overlay)

Always visible, top-left corner, fixed:

- `hive/self/identity` — current narrative self, truncated to 2 lines
- `hive/self/developmental_stage` — badge ("teenage" | "young_adult" | "adult")
- `hive/self/age` — integer
- `hive/interoception/felt_state` — badge ("tired" | "overloaded" | "healthy" | ...)
- Small modulator panel: six named gauges (`cortisol`, `dopamine`, `serotonin`, `norepinephrine`, `oxytocin`, `acetylcholine`)

Bottom strip:

- Total lifetime tokens across all regions
- Messages/sec (rolling 5 s)
- Observatory uptime

## 5. Region inspector (v2)

Click a region or press `I` after selecting via keyboard → camera eases in via `drei/CameraControls`, scene dims to ~25% opacity, right-side panel slides in.

### 5.1 Panel contents, top to bottom

1. **Header** — region name · lifecycle phase badge · uptime since last restart · LLM model name · close button.
2. **Live stats strip** — five tiles fed by heartbeats (5 s cadence):
   - `queue_depth_messages` (sparkline, 2-minute window)
   - `stm_bytes` (gauge, threshold coloring)
   - `llm_tokens_used_lifetime` (counter + rate sparkline)
   - `handler_count` (integer)
   - `last_error_ts` (timestamp, red dot if < 60 s ago)
3. **Modulator bath** — the six gauges from the HUD, repeated. Cognitive emphasis that "this region is bathed in these levels right now."
4. **Prompt snapshot** — fetched on panel open from `GET /api/regions/<name>/prompt`. Scrollable, read-only. Refetched on demand via a reload button and automatically when the region's `last_error_ts` or phase changes (hint that it may have just woken from sleep).
5. **Recent messages log** — scrolling list of last ~100 envelopes where the region is source or destination, pulled from the ring-buffer WebSocket stream. Columns: timestamp · direction · topic · payload-preview. Click a row to expand full envelope JSON.
6. **STM viewer** — fetched from `GET /api/regions/<name>/stm`. JSON tree view. Same refetch rules as prompt.
7. **Subscriptions** — fetched from `GET /api/regions/<name>/subscriptions`. Flat list of topic patterns.

### 5.2 v3 additions

Appended to the panel after v3 ships:

- **Handler source listing** — `GET /api/regions/<name>/handlers` and `GET /api/regions/<name>/handlers/<path>`.
- **LTM notes** — `GET /api/regions/<name>/ltm` (list) and `GET /api/regions/<name>/ltm/<path>`.
- **Git log** — `GET /api/regions/<name>/git` returns recent commits for the region's git history.

## 6. Backend — data plumbing

### 6.1 Stack

- Python 3.11+ (matches rest of Hive).
- `fastapi` (^0.110), `aiomqtt` (^2.x, same version used by `region_template/mqtt_client.py`), `uvicorn[standard]`, `pydantic` (^2.x).
- Optional: `watchfiles` for prompt/STM change detection if we later add push-on-change.

### 6.2 MQTT subscription

- Connects to the same broker regions use (from `bus/mosquitto.conf` defaults or `OBSERVATORY_MQTT_URL` env var).
- Single subscription: `hive/#` with QoS 0 (fire-and-forget; missed messages are acceptable for a visualizer).
- Uses a client ID `observatory-<host>-<pid>` to distinguish from regions.
- On connect, the retained topics (`hive/modulator/*`, `hive/self/*`, `hive/interoception/*`, `hive/attention/*`, `hive/system/metrics/*`) arrive immediately; the ring buffer and retained cache are seeded from them.

### 6.3 Ring buffer

- `collections.deque(maxlen=N)` of envelope records. Default `N=10000`, configurable via `OBSERVATORY_RING_BUFFER_SIZE`.
- Record shape:
  ```python
  @dataclass
  class RingRecord:
      observed_at: float        # monotonic time
      envelope: dict            # parsed Envelope
      topic: str
      source_region: str | None # from envelope
      destinations: list[str]   # inferred from subscriptions
  ```
- Thread-safe append (single MQTT consumer task); iteration happens only from the asyncio event loop.

### 6.4 Retained-topic cache

- `dict[str, dict]` keyed by topic, holding the most recent envelope for every retained path.
- Snapshotted on WebSocket connect so new clients get instant state without waiting for the next tick.

### 6.5 Region reader (filesystem sandboxing)

All filesystem access goes through `observatory/region_reader.py`:

- Single allowed root: `<hive_repo>/regions/`, resolved to absolute path at startup.
- Request path is normalized via `Path(root / name / rel).resolve()`, then verified `is_relative_to(root)`. Any symlink, `..`, absolute, or null-byte input rejected.
- Allowed filename patterns per endpoint are hardcoded:
  - `prompt.md`
  - `memory/stm.json`
  - `memory/ltm/*.md`, `memory/ltm/*.json` (v3)
  - `subscriptions.yaml`
  - `config.yaml`
  - `handlers/**/*.py` (v3)
- Max file size per read: 2 MB. Larger files return HTTP 413.
- Read-only open modes.
- `config.yaml` redaction: any field matching `*_key`, `*_token`, `*_secret` is replaced with `"***"` before serialization.
- All reads logged with region name and file path.

### 6.6 REST endpoints

All under `/api/`. All return JSON unless otherwise noted.

| Endpoint | v | Description |
|---|---|---|
| `GET /api/regions` | v1 | List of region names seen in the registry plus derived stats. |
| `GET /api/regions/{name}/prompt` | v2 | Contents of `regions/<name>/prompt.md`. Content-Type `text/plain`. |
| `GET /api/regions/{name}/stm` | v2 | Parsed contents of `regions/<name>/memory/stm.json`. |
| `GET /api/regions/{name}/subscriptions` | v2 | Parsed `regions/<name>/subscriptions.yaml`. |
| `GET /api/regions/{name}/config` | v2 | Parsed `regions/<name>/config.yaml` with secrets redacted. |
| `GET /api/regions/{name}/ltm` | v3 | List of LTM entries (filename + size + mtime). |
| `GET /api/regions/{name}/ltm/{path:path}` | v3 | Contents of one LTM file. |
| `GET /api/regions/{name}/handlers` | v3 | Tree of handler files. |
| `GET /api/regions/{name}/handlers/{path:path}` | v3 | Contents of one handler file. |
| `GET /api/regions/{name}/git` | v3 | Recent commits (sha, ts, subject). |
| `GET /api/health` | v1 | Observatory liveness + version. |

### 6.7 WebSocket protocol

Single endpoint `/ws`. Server-to-client JSON messages.

**On connect (once):**
```json
{"type": "snapshot",
 "payload": {
   "regions": {...},            // current registry + derived stats
   "retained": {...},            // retained topics cache
   "recent": [...],              // last N envelopes from ring buffer
   "server_version": "0.1.0"
 }}
```

**Continuously after connect:**
```json
// Live envelope (one per MQTT message, possibly decimated if rate spikes)
{"type": "envelope",
 "payload": {"observed_at": 1713612345.123,
             "topic": "hive/cognitive/prefrontal/plan",
             "envelope": {...},
             "source_region": "prefrontal_cortex",
             "destinations": ["thalamus"]}}

// Derived per-region deltas (every 2 s)
{"type": "region_delta",
 "payload": {"regions": {"prefrontal_cortex": {"msg_rate_in": 1.2,
                                                 "msg_rate_out": 0.6,
                                                 "llm_in_flight": true}}}}

// Adjacency update (every 2 s)
{"type": "adjacency",
 "payload": {"pairs": [["prefrontal_cortex", "thalamus", 0.8],
                       ["thalamus", "prefrontal_cortex", 1.1]]}}
```

Client-to-server messages: none in v1. v3 adds pause/scrub commands.

### 6.8 Decimation

If envelope-publish rate exceeds a configurable threshold (`OBSERVATORY_MAX_WS_RATE`, default 200 msgs/sec per client), the WebSocket fan-out drops low-priority envelopes (system/heartbeat, rhythm) first, retains cognitive/sensory/motor/metacognition. Drops are reported to the client via `{"type": "decimated", "payload": {"dropped": N}}` so the UI can show a warning.

## 7. Frontend — presentation

### 7.1 Stack

- React 18, TypeScript.
- `three`, `@react-three/fiber`, `@react-three/drei`.
- `d3-force-3d` for physics.
- `zustand` for state (lightweight, no context churn on high-rate updates).
- `tailwindcss` for HUD / inspector styling.
- `vite` for dev server + production build.

### 7.2 State model

One zustand store with three slices:

- `regions`: map name → { base_color, phase, stats, position, velocity }
- `envelopes`: bounded ring (mirrors server ring buffer; client default 5000, server default 10000 — server is authoritative; client drops oldest first when exceeded)
- `ambient`: modulator values, rhythm phases, self-state

High-rate updates (envelopes, adjacency) bypass React re-render by writing directly into a mutable ref consumed by the Three.js render loop — only HUD components read zustand on a cadence.

### 7.3 Rendering loop

- R3F `useFrame` drives the scene update at 60fps target.
- Physics step runs off-thread via a Web Worker if profiling shows main-thread stalls (stretch; not required for v1).
- Spark particles live in an instanced mesh with ~2000 concurrent-sparks cap. Older sparks recycle.

### 7.4 Interactions

- Orbit / dolly / pan via `@react-three/drei/OrbitControls`.
- Click a region sphere → selects it; a second click or `I` opens inspector.
- `ESC` closes inspector.
- `Space` pauses new envelope ingestion on the client (pinned scene for screenshots). v3 extends this to full scrub.

## 8. Repo layout

```
observatory/
├── CLAUDE.md
├── HANDOFF.md
├── Dockerfile
├── pyproject.toml
├── __init__.py
├── __main__.py                     # `python -m observatory`
├── service.py                      # FastAPI app assembly
├── mqtt_subscriber.py              # aiomqtt consumer → ring buffer
├── ring_buffer.py
├── retained_cache.py
├── region_reader.py                # sandboxed filesystem reader
├── api.py                          # REST routes
├── ws.py                           # WebSocket endpoint
├── adjacency.py                    # rolling message-rate matrix
├── decimator.py
├── types.py
├── docs/
│   ├── specs/
│   │   └── 2026-04-20-observatory-design.md
│   └── plans/
│       └── 2026-04-20-observatory-plan.md   # (written by writing-plans)
├── prompts/                        # implementer prompts per task
├── memory/
│   └── decisions.md
├── tests/
│   ├── unit/
│   └── component/
├── web/                            # built vite bundle — NOT committed; produced by `npm run build` in web-src/ (see .gitignore)
└── web-src/
    ├── package.json
    ├── vite.config.ts
    ├── tsconfig.json
    ├── tailwind.config.ts
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── store.ts                # zustand
        ├── scene/
        │   ├── Scene.tsx
        │   ├── Regions.tsx
        │   ├── Sparks.tsx
        │   ├── Fog.tsx
        │   ├── Rhythm.tsx
        │   └── useForceGraph.ts
        ├── hud/
        │   ├── Hud.tsx
        │   ├── SelfPanel.tsx
        │   └── Modulators.tsx
        ├── inspector/
        │   ├── Inspector.tsx
        │   ├── StatsStrip.tsx
        │   ├── PromptView.tsx
        │   ├── StmView.tsx
        │   └── MessagesLog.tsx
        └── api/
            ├── ws.ts
            └── rest.ts
```

Parallel to `glia/` and `region_template/` at the repo root.

## 9. Milestones

### v1 — "Watching Hive think"

Ships the scene, the ambient channels, and the backend plumbing.

- Backend: MQTT subscriber, ring buffer, retained cache, WebSocket, `/api/regions`, `/api/health`.
- Frontend: force-directed 3D scene with the 14 regions, base color from phase, halos from token rate, sparks on edges, modulator fog, rhythm pulse, HUD with self-state and modulator gauges.
- Docker image that runs `python -m observatory` on `127.0.0.1:8765`.
- No inspector panel.
- Tests: unit tests for ring buffer, retained cache, adjacency computation, sandboxed reader boundary; a component test that boots the service against a testcontainer broker and asserts a published message arrives over the WebSocket.

### v2 — "Zoom in"

Adds the region inspector.

- Backend: REST endpoints for prompt, STM, subscriptions, config (with redaction).
- Frontend: click-to-zoom, side panel with stats, modulator bath, prompt view, STM tree, messages log filtered by region, subscriptions list.
- Tests: REST handler tests including sandbox boundary violations (should return 403), redaction tests, inspector component tests.

### v3 — "Full introspection + replay"

- Backend: endpoints for LTM, handlers, git log. Pause/scrub WebSocket command.
- Frontend: file browser panels for LTM and handlers, git log panel, timeline scrubber.
- Tests: full end-to-end replay of a recorded session.

## 10. Safety and posture

- **Read-only toward Hive.** Enforced by: MQTT client never publishes (no `publish` call sites); filesystem reader opens only in `"r"` / `"rb"` mode; no `git write` code paths.
- **Path sandboxing.** `region_reader.py` is the sole filesystem entry point; any future REST handler that touches disk must go through it.
- **Secret redaction.** `config.yaml` secrets redacted before JSON serialization.
- **Network binding.** `127.0.0.1` default; exposing on a non-loopback interface requires an explicit `OBSERVATORY_BIND_HOST` env var plus a consent log line at startup.
- **Crash isolation.** Observatory crashing does not affect Hive (separate process, no glia dependency). Glia does not supervise it; it is a sidecar.

## 11. Tracking inside `observatory/`

This directory is self-contained. Specs, plans, prompts, and session memory for the observatory live here — not in the top-level `docs/superpowers/` tree.

- `observatory/CLAUDE.md` — resume protocol and scope-boundary guide for agents working on observatory tasks.
- `observatory/HANDOFF.md` — session handoff, progress table, next-session prompt.
- `observatory/docs/specs/` — design specs. This file is the first.
- `observatory/docs/plans/` — implementation plans from `writing-plans`.
- `observatory/prompts/` — per-task implementer prompts, kept for audit.
- `observatory/memory/decisions.md` — running log of non-obvious calls made during implementation.

Top-level `CLAUDE.md` gets one line added so the main-repo agent recognizes `continue observatory ...` prompts and routes into `observatory/CLAUDE.md` instead of the main handoff.

Canonical resume prompt: `continue observatory v1` (or `v2`, `v3`).

## 12. Open questions

None at spec time. If any surface during plan-writing or implementation, they are logged in `observatory/memory/decisions.md` with date, question, and the call that was made.

## 13. Changelog

| Date | Change |
|---|---|
| 2026-04-20 | Initial version — approved through brainstorming session. |
