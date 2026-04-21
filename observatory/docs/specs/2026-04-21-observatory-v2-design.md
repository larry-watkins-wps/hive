# Observatory v2 — Region Inspector & Scene Visual Upgrade

*Draft: 2026-04-21 · Authoritative spec for v2 implementation*

---

## 1. Purpose

v2 adds the **region inspector** — the "Zoom in" view from the v1 spec's milestone table (§9) — and a **scene visual upgrade** that promotes v1's single-sphere regions to multi-layer fuzzy glows with always-visible name labels and brighter, reactive adjacency threads.

This spec extends `observatory/docs/specs/2026-04-20-observatory-design.md` (henceforth **v1 spec**). Sections of the v1 spec are authoritative for anything v2 does not explicitly re-scope here.

## 2. Scope

v2 ships the following on top of v1:

1. Sandboxed filesystem reader (`observatory/region_reader.py`), matching v1 spec §6.5 in full.
2. Five REST endpoints under `/api/regions/{name}/`: `prompt`, `stm`, `subscriptions`, `config`, `handlers`.
3. Inspector panel — right slide-over, 8 sections, click-to-open, minimal keyboard bindings.
4. Reactive adjacency threads — visible per-edge lines that brighten on spark traversal.
5. Region labels — name always floating, stats on hover, no card (floating text).
6. Scene visual upgrade — v1's `Regions.tsx` replaced with multi-layer fuzzy-orb rendering.

Explicitly **out of scope** for v2 (deferred to v3 or v1.1):

- Handler *source* reads (`/api/regions/{name}/handlers/{path}`) — v3.
- LTM list + content reads — v3.
- Git log endpoint + panel — v3.
- Pause / scrub / replay WebSocket commands — v3.
- Server-side region-focused WS filter — client-side filter only.
- Inspector state persistence across page reloads.
- 3D keyboard-focus-ring for region selection; command-palette picker.
- TLS for `mqtts://` (still warning-only in v2).
- Fuzzy-orb look-dev (e.g., animated turbulence, shader-based noise) beyond the layered-sprite approach defined in §6.

## 3. Region inspector panel

### 3.1 Layout & framing

- **Position:** fixed right, full viewport height, width `420 px`.
- **Open animation:** CSS `transform: translateX(0)` from `translateX(100%)`, `transition: transform 300ms ease-out`.
- **Scene dim:** when a region is selected, all scene meshes render at `opacity = 0.25` except the selected region's four-layer orb (full brightness). Threads also read the dim factor. Labels render at full brightness so the selected region's name + stats remain legible.
- **Close triggers:** `Esc`, `✕` button in header, or pointer-miss click on the canvas.
- **Keyboard cycling:** `[` previous region (alphabetical, wrap), `]` next region. Cycling updates `selectedRegion` and re-runs all section fetches; panel stays mounted to avoid slide-in/out flicker.
- **Camera:** on selection/cycle, `CameraControls.fitToBox(regionMesh, true, { smoothTime: 0.6, paddingTop: 0.5, paddingLeft: 0.5, paddingRight: 0.5, paddingBottom: 0.5 })`. On close, `CameraControls.reset(true)`. Swaps in for v1's `OrbitControls`; free orbit still works.
- **`R` key:** reset camera without closing the panel. Ignored when the keyboard-event target is an `<input>` / `<textarea>` / element with `contenteditable`.

### 3.2 Section inventory (top to bottom)

Each section is a self-contained React component under `observatory/web-src/src/inspector/sections/`.

1. **Header** — region name · phase badge · uptime since last restart · handler count · `llm_model` (fallback `—` if empty) · `✕` close button. Uses `RegionMeta` + `RegionStats` from store; no fetch.
2. **Stats strip** — five 5s-heartbeat-fed tiles in a row: `queue_depth_messages` (value + 24-point sparkline, 2-minute window), `stm_bytes` (value with threshold coloring: `< 16 kB` = default, `16–64 kB` = amber, `> 64 kB` = red), `llm_tokens_used_lifetime` (formatted, sparkline), `handler_count` (integer), `last_error_ts` (relative-to-now with red dot if `< 60 s` ago, otherwise grey). Sparklines rendered inline as `<svg>`.
3. **Modulator bath** — imports `Modulators.tsx` from v1 HUD (six gauges: DA / NE / 5HT / ACh / HIS / ORX). No duplication.
4. **Prompt** — collapsed by default. `<details>` summary shows size in kB. Expanded: scrollable monospaced `<pre>` of fetched text, with a "reload" button in the summary. Auto-refetch when the region's `last_error_ts` or `phase` changes.
5. **Messages log** — expanded by default. Scrolling list of last ~100 envelopes where `source_region == name || name ∈ destinations`. Client-side filter over the store's `recent` ring buffer; no backend change. Row layout: `HH:MM:SS · ↑/↓ · topic · payload-preview (first 80 chars)`. Click a row to expand full envelope JSON inline. Auto-scroll: when the user's scroll position is within `40 px` of the bottom, new arrivals scroll into view; otherwise auto-scroll pauses until the user returns near bottom. Implementation: `lastLenRef`-based incremental scan over the ring buffer (same pattern as v1 Sparks/Rhythm).
6. **STM** — collapsed by default. JSON tree view via a tiny in-repo recursive component (no new dependency). Same refetch rules as Prompt.
7. **Subscriptions** — collapsed by default. Flat `<ul>` of topic patterns. Fetched once per open; no auto-refresh.
8. **Handlers** — collapsed by default. Flat list of `path · size` (e.g., `handlers/on_wake.py · 1.2 kB`). Fetched once per open. Clicking an entry is a **no-op in v2** — source reads defer to v3.

Sections 4–8 render a chevron (`▸` / `▾`) indicating collapsed/expanded state. Default collapse state is fixed in v2 (Prompt / STM / Subscriptions / Handlers collapsed; Messages expanded).

### 3.3 Fetch + refetch rules

Per-section `useRegionFetch` hook returns `{ loading, error, data, reload }`.

| Section | Fetch trigger | Auto-refetch triggers |
|---|---|---|
| Header | — (from store) | store updates |
| Stats strip | — (from store heartbeat) | store updates |
| Modulator bath | — (from store) | store updates |
| Prompt | on open + region change | `last_error_ts` change · `phase` change · reload button |
| Messages | — (from store ring buffer) | envelope arrival |
| STM | on open + region change | `last_error_ts` change · `phase` change · reload button |
| Subscriptions | on open + region change | reload button only |
| Handlers | on open + region change | reload button only |
| Config | on open + region change | no auto-refetch |

**Config** is **not rendered as a standalone section** in v2 — the endpoint is fetched once per panel open and its parsed (redacted) contents are used only to populate the Header's `llm_model` value (falls back to `—` if the key is absent or parsing fails). No reload button; rarely changes.

### 3.4 Loading / error states

Each section renders one of:

- **loading:** 24-px grey skeleton bar.
- **error:** inline red text `Failed: <status> <statusText>` + retry button. Sandbox / 403 / 413 surface the backend's `{"error", "message"}` body text.
- **data:** the section's real content.

Empty states:

- Empty STM (`{}`) → "STM is empty."
- Zero handlers → "No handler files."
- Zero subscriptions → "No subscriptions declared."
- Prompt missing → "No `prompt.md` in this region."

## 4. Interaction model

```
┌──────────────────────────────────────────────────────────────────┐
│ click region mesh                                                │
│   └─> store.select(name)                                         │
│       ├─> CameraControls.fitToBox(mesh, true, { smoothTime: 0.6})│
│       ├─> dimFactor := 0.25 (affects all unselected meshes)      │
│       ├─> Inspector slides in (transform 300 ms)                 │
│       └─> each section's useRegionFetch fires                    │
│                                                                  │
│ Esc / ✕ / empty-space click / pointer-miss                       │
│   └─> store.select(null)                                         │
│       ├─> CameraControls.reset(true)                             │
│       ├─> dimFactor := 1.0                                       │
│       └─> Inspector slides out                                   │
│                                                                  │
│ [ / ]                                                            │
│   └─> store.cycle(±1)  // alphabetical wrap                      │
│       ├─> CameraControls.fitToBox(newMesh, …)                    │
│       └─> section hooks re-key on name → re-fetch                │
│                                                                  │
│ R                                                                │
│   └─> CameraControls.reset(true)  // panel stays open            │
└──────────────────────────────────────────────────────────────────┘
```

Keyboard handler (`observatory/web-src/src/inspector/useInspectorKeys.ts`) attaches one `window.addEventListener('keydown', …)` at `App` level. No per-component listeners. Early return when `event.target instanceof HTMLInputElement | HTMLTextAreaElement` or `event.target.isContentEditable`.

## 5. Scene visual upgrade

### 5.1 Region rendering — fuzzy multi-layer orbs

v1's `Regions.tsx` renders one `MeshStandardMaterial` sphere per region (plus a halo ring and a handler torus). v2 replaces the per-region visual with a **four-layer additive-glow group**:

| Layer | Geometry | Material | Scale (×region size) | Opacity / notes |
|---|---|---|---|---|
| Outer halo | `Sprite` with `SpriteMaterial` | `AdditiveBlending`, `depthWrite: false`, `map: GLOW_TEX` | wake: 5.2 · boot: 4.5 · sleep: 3.8 | wake: 0.28 · boot: 0.18 · sleep: 0.10 |
| Mid halo | `Sprite` | same material pattern | 2.6 | wake: 0.65 · sleep: 0.28 |
| Core | `SphereGeometry(r×0.55, 32, 24)` | `MeshStandardMaterial` | 0.55 | `emissiveIntensity` wake: 0.55 / sleep: 0.15; `roughness: 0.9`, `metalness: 0`, `transparent: true`, `opacity: 0.85` |
| Speckle | `Sprite` | same + `color: 0xffffff` | 0.9 | wake: 0.6 · sleep: 0.20 |

`GLOW_TEX` is a 256×256 procedurally generated canvas texture: radial gradient from rgba(255,255,255,1) at center to fully transparent at radius, with stops `[0, 0.18, 0.4, 0.7, 1.0]` at alpha `[1.0, 0.65, 0.22, 0.06, 0.0]`. Generated once at module scope and reused across all regions. `THREE.SRGBColorSpace`.

`SpriteMaterial.color` for outer/mid/speckle is set per-region (the phase-driven color from v1). The speckle uses white color for a hot-core feel.

**Dimming** (§3.1): applied by multiplying each material's `opacity` by `dimFactor` in a `useFrame` hook. Core `MeshStandardMaterial.opacity` also dims; sprites dim proportionally so the entire orb fades uniformly. Selected region's `dimFactor = 1.0`.

**Phase changes:** when a region's phase changes (`wake → sleep`, etc.), the layers' opacity and core's `emissiveIntensity` lerp over `800 ms` to the new-phase values. No color change — phase color handling is already v1's job via the base color selection in `Regions.tsx`, which v2 preserves.

**Halo ring + handler torus from v1:** removed. The new fuzzy-orb layers replace both channels visually. Handler count still surfaces in the panel header (§3.2.1) and can drive core size in a follow-up; v2 renders all cores at fixed `0.55 × region size`.

**Picker mesh:** an invisible `MeshBasicMaterial({ visible: false })` sphere at `1.2 × region size` is added per region purely for raycasting (hover / click). This decouples the interaction target from the visible layers. Click handlers attach here.

### 5.2 Region labels — floating text

Implementation: `three/addons/renderers/CSS2DRenderer.js` + `CSS2DObject`. A single `CSS2DRenderer` instance is created alongside the WebGL renderer, stacked above the canvas with `pointer-events: none`.

Per region, one `CSS2DObject` is attached to the picker mesh at local position `(0, r.size × 1.6, 0)`. The DOM node has class `float-label` with two child divs:

- `.name` — always visible. Shows the region name.
- `.stats` — hidden unless the label root has `.hover` class. Shows: phase tag (`WAKE` / `SLEEP` / `BOOT` / `SHUTDOWN`) · `queue <n>` · `stm <size>` · `tokens <formatted>`.

**Typography (CSS):**

```css
.float-label {
  pointer-events: none;
  text-align: center;
  transform: translate(-50%, -130%);
  font-family: 'Inter', ui-sans-serif, -apple-system, 'Segoe UI', sans-serif;
  white-space: nowrap;
  text-shadow:
    0 0 3px rgba(0,0,0,0.95),
    0 0 1px rgba(0,0,0,0.95);
}
.float-label .name {
  font-size: 10px;
  font-weight: 200;
  letter-spacing: 0.4px;
  color: rgba(230, 232, 238, 0.78);
}
.float-label .stats {
  display: none;
  font-family: ui-monospace, Menlo, Consolas, monospace;
  font-size: 9px;
  font-weight: 300;
  color: rgba(200, 204, 212, 0.78);
  margin-top: 2px;
  letter-spacing: 0.2px;
}
.float-label.hover .name  { color: rgba(255,255,255,0.95); }
.float-label.hover .stats { display: block; }
```

**Hover detection:** a three.js `Raycaster` on `pointermove` tests the picker meshes. The hit target's label gains `.hover`; all others lose it. Same mechanism drives the `cursor: pointer` styling.

**Selected region labels:** when a region is selected via click/cycle, the selected region's label is forced into `.hover` state regardless of pointer position (makes the "currently-inspecting" region's stats always visible during inspection).

### 5.3 Reactive adjacency threads

v1 ships without visible edges (decisions.md entry 7). v2 adds one `Line` per adjacency pair, each with its own `LineBasicMaterial` instance (cannot share — per-edge color/opacity state).

**Rendering:** `THREE.Line` (not `Line2` / `LineSegments2`) — WebGL `linewidth` quirks acknowledged; visual weight comes from additive blending + opacity, not stroke width.

**Material defaults:**

```
color: 0x2a3550 (at rest) — cool blue-grey
transparent: true
opacity: 0.08 (at rest)
blending: AdditiveBlending
depthWrite: false
```

**At-rest visibility floor:** `0.08` keeps the structure faintly visible so scene layout reads even when no traffic flows.

**Reactive pulse:** a module-level `Map<edgeKey, { pulse: number, color: Color }>` is updated when `Sparks.tsx` spawns a spark for a given edge (§7.3 of v1 spec). On spawn:

```ts
const entry = EDGE_PULSE.get(edgeKey);
if (entry) {
  entry.pulse = 1.0;
  entry.color.copy(topicColorObject(envelope.topic));
}
```

Each frame, `Edges.tsx` `useFrame` decays pulses at rate `1 / 0.8 s` and applies:

```
material.opacity = clamp(0.08 + 0.55 * pulse, 0, 1)
material.color   = pulse > 0.01 ? entry.color : 0x2a3550
```

Edge key: `${min(a, b)}|${max(a, b)}` (undirected). Adjacency changes (from the WebSocket `adjacency` message) rebuild the `<Line>` children; stale entries in `EDGE_PULSE` are GC'd on adjacency change.

**Dim factor:** also multiplies edge opacity so edges fade with the scene when a region is selected.

## 6. Backend

### 6.1 `observatory/region_reader.py`

Single entry point for all per-region disk reads. Module-level singleton bound at service startup.

```python
from dataclasses import dataclass
from pathlib import Path

class SandboxError(Exception):
    """Raised when a read violates sandbox rules. Carries HTTP status."""
    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code  # 403 | 404 | 413 | 502

@dataclass(frozen=True)
class HandlerEntry:
    path: str       # POSIX-style relative to region root, e.g. "handlers/on_wake.py"
    size: int       # bytes

class RegionReader:
    def __init__(self, regions_root: Path) -> None:
        """regions_root is resolved to absolute path. Must exist."""

    def read_prompt(self, region: str) -> str: ...
    def read_stm(self, region: str) -> dict: ...
    def read_subscriptions(self, region: str) -> dict: ...
    def read_config(self, region: str) -> dict: ...       # secrets redacted
    def list_handlers(self, region: str) -> list[HandlerEntry]: ...
```

**Validation pipeline applied to every call:**

1. `region` must match `^[A-Za-z0-9_-]+$`. Otherwise → `SandboxError(..., 404)`.
2. Compose: `candidate = (regions_root / region / rel_filename).resolve()`.
3. Assert `candidate.is_relative_to(regions_root)`. Otherwise → `SandboxError(..., 403)`.
4. Reject the candidate path if any component along `regions_root / region / rel_filename` (before resolve) is absolute, contains `..`, or contains a null byte. → `403`.
5. After resolve, assert `not Path(candidate).is_symlink()`. → `403`.
6. Assert `candidate.exists() and candidate.is_file()`. Otherwise → `404`.
7. Assert `candidate.stat().st_size <= MAX_FILE_BYTES` (default `2 * 1024 * 1024`). → `413`.
8. Open with mode `'r'` (text) or `'rb'` (bytes), UTF-8 encoding where text.

**Allowed filename patterns per method** (hardcoded):

| Method | Filename |
|---|---|
| `read_prompt` | `prompt.md` |
| `read_stm` | `memory/stm.json` |
| `read_subscriptions` | `subscriptions.yaml` |
| `read_config` | `config.yaml` |
| `list_handlers` | `handlers/**/*.py` (glob, non-recursive by *directory*, see below) |

**`list_handlers` traversal:** uses `(regions_root / region / 'handlers').rglob('*.py')`. Each match runs the validation pipeline (symlink rejection, size cap). Results sorted lexicographically by POSIX path. `size` read from `stat().st_size`. An entry's `path` is stored as a POSIX-style string relative to `regions_root / region`. If the `handlers/` directory is missing, returns an empty list (not an error).

**JSON/YAML parse failures:** `read_stm`, `read_subscriptions`, `read_config` parse files with `json.loads` / `yaml.safe_load`. Parse errors raise `SandboxError(..., 502)` with the parser error message attached.

**Redaction for `read_config`:** after successful YAML parse, the dict is recursively walked; any key whose lower-cased form ends with `_key`, `_token`, or `_secret` has its value replaced with the literal string `"***"`. Nested dicts are walked; lists of dicts too. Non-dict / non-list values are left alone except the replacement itself. Only applies to `read_config`.

**Logging:** every successful read emits a `structlog` event `observatory.region_read` with keys `region`, `file`, `size_bytes`, `method`. Sandbox errors emit `observatory.region_read_denied` with `region`, `file`, `code`, `reason`.

### 6.2 REST endpoints

All under `/api/regions/{name}/`. Shared error shape on failure:

```json
{"error": "sandbox|parse|not_found|oversize", "message": "human-readable detail"}
```

| Method + path | 200 body | Content-Type | Errors |
|---|---|---|---|
| `GET /prompt` | raw text | `text/plain; charset=utf-8` | 403 sandbox · 404 region or file missing · 413 oversize |
| `GET /stm` | parsed JSON | `application/json` | same + 502 parse |
| `GET /subscriptions` | parsed YAML → JSON | `application/json` | same + 502 parse |
| `GET /config` | parsed + redacted JSON | `application/json` | same + 502 parse |
| `GET /handlers` | `[{"path": "...", "size": 1234}, ...]` | `application/json` | same |

**Unknown region name:** if `name` is not in the in-memory registry (from `glia/regions_registry.yaml`, loaded at service startup per v1 Task 2), all five endpoints short-circuit to `404` before any disk touch.

**Caching:** `Cache-Control: no-store` on all five. Live introspection requires reflecting file changes immediately.

**Handler:** each endpoint is a thin FastAPI route that calls the reader, maps `SandboxError.code` to `HTTPException.status_code`, and lets non-`SandboxError` exceptions propagate to a default 500.

## 7. Frontend

### 7.1 New files

Under `observatory/web-src/src/`:

```
inspector/
  Inspector.tsx                 slide-over shell
  useInspectorKeys.ts           window keydown handler (Esc / [ / ] / R)
  useRegionFetch.ts             fetch hook with {loading, error, data, reload}
  sections/
    Header.tsx
    Stats.tsx
    ModulatorBath.tsx           thin wrapper re-exporting HUD's Modulators.tsx
    Prompt.tsx
    Messages.tsx
    Stm.tsx
    Subscriptions.tsx
    Handlers.tsx
    JsonTree.tsx                tiny recursive JSON renderer (used by Stm.tsx)
scene/
  FuzzyOrbs.tsx                 replaces v1 Regions.tsx
  Labels.tsx                    CSS2DRenderer setup + per-region CSS2DObject wiring
  Edges.tsx                     reactive-thread rendering, pulse decay
  glowTexture.ts                GLOW_TEX canvas generator, exported once
types.d.ts                      (extended — see §7.2)
```

Modified v1 files:

- `Scene.tsx` — replace `<Regions />` with `<FuzzyOrbs />`; add `<Labels />` + `<Edges />`; swap `<OrbitControls>` → `<CameraControls>` from `@react-three/drei`.
- `App.tsx` — mount `<Inspector />` alongside `<Scene />`; install `useInspectorKeys`.
- `store.ts` — add `selectedRegion`, `select`, `cycle`, `envelopesReceivedTotal` selectors preserved from v1.
- `rest.ts` — add `fetchPrompt`, `fetchStm`, `fetchSubscriptions`, `fetchConfig`, `fetchHandlers` wrappers; typed error returns.
- `Regions.tsx` — **deleted**.

Dependencies: no net-new runtime packages. `drei` already imports `CameraControls`; `CSS2DRenderer` ships with `three/addons`.

### 7.2 `types.d.ts` extensions

The v1 file ambient-shims `d3-force-3d`. v2 adds (if needed) declarations for `CSS2DRenderer` and `CSS2DObject` — three.js 0.160 ships these with types, so likely nothing to add. Verify during implementation; if TypeScript complains, add:

```ts
declare module 'three/addons/renderers/CSS2DRenderer.js';
```

### 7.3 Store additions

```ts
interface ObservatoryState {
  // ...existing v1 fields...
  selectedRegion: string | null;
  select: (name: string | null) => void;
  cycle: (direction: 1 | -1) => void;
}
```

`cycle` reads `Object.keys(regions).sort()` and steps `±1` with wrap. No-op if `selectedRegion` is `null` or the list is empty. Updating `selectedRegion` via `select` or `cycle` does not reach out to fetch; the inspector's section hooks re-key on `selectedRegion` change and trigger their own fetches.

### 7.4 Data flow — panel open sequence

```
<Regions picker-mesh onClick> ──> store.select(name)
                                      │
                                      ├──> Scene `dimFactor` selector recomputes (0.25)
                                      ├──> FuzzyOrbs useFrame lerps layer opacities
                                      ├──> Edges useFrame multiplies opacity by dimFactor
                                      ├──> Labels forces .hover on selected
                                      ├──> CameraControls.fitToBox(selectedMesh, true, {...})
                                      └──> Inspector mounts (was hidden), slide-in animation
                                            │
                                            └──> 5 × useRegionFetch fire:
                                                  prompt  → GET /api/regions/{name}/prompt
                                                  stm     → GET /api/regions/{name}/stm
                                                  subs    → GET /api/regions/{name}/subscriptions
                                                  config  → GET /api/regions/{name}/config
                                                  handlers→ GET /api/regions/{name}/handlers
                                                  (each renders skeleton → data | error)
```

## 8. Testing

### 8.1 Python unit

Under `observatory/tests/unit/`.

- `test_region_reader.py`:
  - Happy paths for all five methods against a seeded fixture directory.
  - Sandbox boundaries: symlink rejection (create symlink in fixture, assert 403); `..` rejection (input `"../etc/passwd"`); absolute path rejection; null byte rejection; unknown region name (`^[A-Za-z0-9_-]+$` violations).
  - Size cap: 3 MB file → 413.
  - Missing file → 404 (vs. missing region → 404 with different reason code).
  - `config.yaml` redaction: keys `api_key`, `auth_token`, `aws_secret`, `SESSION_KEY` (case-insensitive match on lower-case suffix) all redacted; nested under list/dict.
  - `list_handlers` with missing `handlers/` → `[]`.
  - `list_handlers` sorts POSIX-lexicographically.
  - Parse failures (malformed JSON for stm, malformed YAML for subs/config) → 502.
- `test_api_regions_v2.py`:
  - Each endpoint returns the expected 200 shape for a seeded region.
  - Each endpoint maps `SandboxError.code` → correct HTTP status.
  - Unknown region → 404 for all five.
  - `Cache-Control: no-store` header on all five.

### 8.2 Python component

Extend `observatory/tests/component/test_end_to_end.py` (v1 Task 8). Add a secondary flow:

- Seed a temporary `regions/testregion/` directory with `prompt.md`, `memory/stm.json`, `subscriptions.yaml`, `config.yaml` (containing a fake secret), and one `handlers/on_wake.py`.
- Point `OBSERVATORY_REGIONS_ROOT` at the temp dir.
- After broker connect, `httpx.AsyncClient.get("/api/regions/testregion/config")` — assert `api_key` value is `"***"` in the response.
- `get("/api/regions/testregion/handlers")` — assert one entry with correct path and size.

### 8.3 Frontend vitest

Under `observatory/web-src/src/`.

- `store.test.ts` — new cases: `select(name)` sets selectedRegion; `select(null)` clears it; `cycle(1)` from last region wraps to first; `cycle(-1)` from first wraps to last; `cycle` no-op when `selectedRegion` is null.
- `useRegionFetch.test.ts` — 200, 404, 403, 413, 502 paths. `reload()` resets state and refetches. Error body parsing: when response has `{"error", "message"}`, renders `message`; otherwise renders `status statusText`.
- `inspector/Header.test.tsx` — renders phase badge; falls back to `—` for empty `llm_model`.
- `inspector/Messages.test.tsx` — filter includes envelopes where region is source OR destination. Auto-scroll: new arrival at tail when `scrollTop` within 40 px of bottom → container scrolls; far from bottom → no scroll.
- `inspector/Stm.test.tsx` — renders JSON tree; empty object renders empty-state copy.
- `edges.test.ts` — `EDGE_PULSE` bump on spark spawn writes pulse=1 + color; `useFrame` tick decays pulse; at `pulse > 0.01`, material opacity = `0.08 + 0.55 × pulse`; at `pulse ≤ 0.01`, opacity = 0.08 and color resets.
- `scene/FuzzyOrbs.test.tsx` — layer counts per region (4); phase change lerps opacity over 800 ms (tick at 400 ms → half-way value).
- `scene/Labels.test.tsx` — `.name` always rendered; `.stats` only when `.hover` class present; selected region forces `.hover`.

### 8.4 Verification gates

Same as v1:

```bash
python -m pytest observatory/tests/ -q            # all tests
python -m pytest observatory/tests/component/ -m component -v  # requires Docker
python -m ruff check observatory/
cd observatory/web-src && npm run test && npx tsc -b && npm run build
```

## 9. Safety & posture

- **Read-only toward Hive:** unchanged from v1. Reader opens with `'r'` / `'rb'` only; no `write`/`append` modes anywhere in the package. No publish sites in `mqtt_client.py`.
- **Sandbox:** §6.1 validation pipeline is the single disk entry. Any future endpoint that touches disk MUST route through `RegionReader`.
- **Secret redaction:** applied in `read_config`, covered by unit tests. Redaction happens before JSON serialization.
- **Network binding:** unchanged. `127.0.0.1` default; non-loopback requires `OBSERVATORY_BIND_HOST` + startup warning.
- **Crash isolation:** unchanged. Observatory remains a sidecar; no glia / region dependencies.

## 10. Migration from v1

No breaking changes to the v1 backend. The following v1 files are modified:

- `observatory/service.py` — instantiate `RegionReader` at lifespan startup; wire into new endpoint handlers.
- `observatory/api.py` — register new routes.
- `observatory/config.py` — add `OBSERVATORY_REGIONS_ROOT` setting (default `./regions`).

New files backend:

- `observatory/region_reader.py`
- `observatory/api_regions_v2.py` (or extend `observatory/api.py` — implementation choice)
- `observatory/errors.py` extension (or new module for `SandboxError`).

Frontend changes listed in §7.1. `Regions.tsx` is deleted; v1 tests that assert on its internals get updated or removed.

**HANDOFF bump** (per `observatory/CLAUDE.md`): each task in the v2 plan updates `observatory/HANDOFF.md`'s progress table and adds a changelog row.

## 11. Open questions

None at spec time. Decisions logged during plan-writing or implementation go into `observatory/memory/decisions.md`.

## 12. Changelog

| Date | Change |
|---|---|
| 2026-04-21 | Initial v2 spec — inspector panel, sandbox reader, 5 REST endpoints, reactive threads, region labels, fuzzy-orb scene upgrade. Approved through brainstorming session. |
