# Observatory v3 — Real-Time Visibility Dock, Live Prompt, Expanded HUD

*Draft: 2026-04-22 · Authoritative spec for v3 implementation*

---

## 1. Purpose

v3's goal is **real-time visibility into Hive — shortest path**. Historical navigation (git log, scrub/replay, LTM browse) is **out of scope**. v3 surfaces what's already on MQTT and on disk *right now* so an operator can watch Hive think without reading logs.

v3 builds on v1 + v2. v2's right-slide-over inspector is retained as the depth UI ("region popup"). v3 adds:

1. A collapsible, resizable **bottom dock** with three tabs — Firehose, Topics, Metacognition — as the always-on *awareness* surface.
2. An **Appendix** section inside the inspector so the live prompt (`prompt.md` + `memory/appendices/rolling.md`) is visible, not just the immutable starter.
3. **HUD tiles** for `hive/system/metrics/*` and the four `hive/self/*` retained topics that v1/v2 only partly rendered.
4. A consistent **click-through** interaction: every row in every dock tab routes through "select region + focus camera + open inspector," making the 3D scene the single navigation surface.

Sections of the v2 spec (`observatory/docs/specs/2026-04-21-observatory-v2-design.md`) are authoritative for anything v3 does not re-scope here.

## 2. Scope

**In scope (observatory-only, no Hive-side touches):**

1. Bottom dock: collapse + resize + keyboard + persisted state + three tabs.
2. Firehose tab: full envelope stream, substring filter, pause, click-through.
3. Topics tab: 1-minute EWMA rate per topic, sparkline, publishers, click-through.
4. Metacognition tab: dedicated feed for `hive/metacognition/#`, severity colouring, click-through, tab-bar badge for recent errors.
5. Inspector Appendix subsection (reads `memory/appendices/rolling.md` via new REST route).
6. HUD System-Metrics tile (reads retained `hive/system/metrics/*`).
7. HUD Self-State tile expanded to all four `hive/self/*` retained topics.
8. Full-envelope JSON expand in the inspector's existing Messages section (replaces current preview-only rendering).

**Out of scope (deferred to v4+):**

- Handler-source reads (`/api/regions/{name}/handlers/{path}`) — not needed for real-time visibility.
- LTM list/content reads.
- Git log endpoint + panel.
- Pause / scrub / replay WebSocket commands.
- Server-side region-focused WS filter.
- Inspector state persistence across page reloads (dock state *is* persisted; inspector isn't).
- Any Hive-side publish changes. Per `observatory/CLAUDE.md` the observatory is read-only toward Hive. Every surface in v3 is driven by topics already on the wire (see §3).

## 3. What's on the wire today

Audit of `shared/topics.py` + `region_template/` + `glia/` publish sites (2026-04-22):

| Namespace | Retained? | v3 rendering |
|---|---|---|
| `hive/cognitive/{region}/#` | no | Firehose + Topics; Messages section (v2) |
| `hive/sensory/*`, `hive/motor/*` | mixed | Firehose + Topics |
| `hive/metacognition/{error,conflict,reflection}/*` | no | **Metacog tab** (new) + Firehose |
| `hive/self/{identity,values,personality,autobiographical_index}` | yes | **HUD Self tile** (new, full) |
| `hive/modulator/*`, `hive/attention/*`, `hive/interoception/*`, `hive/habit/*` | yes | Firehose + Topics; Modulators HUD (v1) |
| `hive/rhythm/{gamma,beta,theta}` | no | Firehose + Topics; Rhythm pulse (v1) |
| `hive/system/heartbeat/{region}` | yes | Firehose + Topics; Stats strip (v2) |
| `hive/system/region_stats/{region}` | yes | Firehose + Topics |
| `hive/system/metrics/{compute,tokens,region_health}` | yes | **HUD Metrics tile** (new) |
| `hive/system/{sleep,spawn,codechange}/*` | no | Firehose + Topics |
| `hive/broadcast/shutdown` | no | Firehose + Topics |

The observatory's existing WS envelope ring (`RING_CAP = 5000` in the zustand store, established v1) already captures every non-retained envelope plus retained snapshots at subscribe time. v3 adds **no new backend subscribers** — all three dock tabs are computed views over the existing ring.

## 4. Bottom dock

### 4.1 Frame

- **Position:** fixed bottom, `left: 0`, `right: 0`. The v2 inspector overlays on top of the dock at its right edge (dock extends the full viewport width; inspector paints over the rightmost 420 px when open). This keeps the dock's real estate stable whether the inspector is open or closed — rows don't reflow.
- **Default expanded height:** `220 px`. **Collapsed height:** `28 px` (tab strip + per-tab live count badges only, no content rows).
- **Resize:** drag the top 4 px edge. Clamp `[120 px, 520 px]`. Debounced persistence to `localStorage['observatory.dock.height']` (200 ms).
- **Collapse/expand:** chevron button at the right end of the tab strip **or** keyboard `` ` `` (backtick) anywhere outside an input/textarea/contenteditable element. Persist to `localStorage['observatory.dock.collapsed']`.
- **Pause/resume:** per-tab pause button (clipboard-style icon) **or** `Space` when the dock pane is focused. Paused = tab stops updating visible rows but continues counting. Unpausing appends all envelopes that arrived during the pause (up to RING_CAP).
- **Auto-scroll:** each tab auto-scrolls to newest when the user's scroll-offset-from-bottom is `< 40 px` (same rule as v2 Messages). Otherwise auto-scroll pauses until user returns near bottom.
- **Focus:** clicking inside the dock gives it a soft keyboard focus ring and enables `Space` (pause) and arrow-key row navigation. `Esc` returns focus to scene.

### 4.2 Tab strip

Single horizontal strip, `28 px` tall, flush to the top edge of the dock:

```
[🔥 Firehose  342/s ]  [📡 Topics  28 ]  [⚠ Metacog  ·3 ]              [⏸]  [v]
 │─────────────────│ │─────────────│ │──────────────│                  pause collapse
```

- The active tab has a 1 px top-border accent (`rgba(230,232,238,.9)`); inactive tabs sit at `rgba(230,232,238,.45)` text on transparent background.
- Live counts next to each tab name update regardless of which tab is visible (so you can glance at Metacog's `·N` badge while reading Firehose).
- Metacog's count is coloured red when `errors-in-last-60s > 0`, amber when `conflicts-in-last-60s > 0 && errors == 0`, grey otherwise.
- Topics count is total distinct topics seen in ring.
- Firehose count is a 1-second rolling msg/s rate (uses the store's `envelopesReceivedTotal` monotonic counter, sampled every 1 s — same technique v1 Counters uses).

### 4.3 Visual language

Larry's thin/soft/hover-reveal aesthetic (per `memory/feedback_observatory_visual_language.md`):

- 1 px top border only (`rgba(80,84,96,.55)`), no shadow, no gradient.
- Background `rgba(14,15,19,.86)` (matches inspector's slide-over).
- Row text: 11 px Inter 300; payload text: 10 px `ui-monospace`.
- Timestamps: 10 px `ui-monospace`, `rgba(136,140,152,.70)` (secondary).
- Row hover: entire row's alpha bumps from `.72` to `.95`; source-region name underlines `1 px solid rgba(230,232,238,.45)`.

## 5. Firehose tab

### 5.1 Row schema

```
HH:MM:SS.mmm  source_region → topic                           kind   payload-preview (≤ 120 chars)
14:22:05.417  prefrontal_cortex → hive/cognitive/pfc/plan     cog    {"goal":"reach_block","priority":0.8,…
14:22:05.390  glia              → hive/modulator/dopamine     mod    0.74
14:22:05.112  amygdala          → hive/metacognition/error/…  meta   LlmError: rate_limit_exceeded …
```

- Columns: `HH:MM:SS.mmm` (11 px mono) · `source_region` (ellipsis if `> 18` chars) · `→ topic` (ellipsis at container-width minus reserved) · `kind` (3-letter badge, coloured per §5.3) · `payload-preview`.
- Row height: `22 px`. Content fits one line.
- Payload preview logic: if `payload.content_type == "application/json"`, `JSON.stringify(payload.data).slice(0, 120)`. Else `String(payload.data).slice(0, 120)`. No newlines (`\n` → `↵`). Trailing ellipsis when truncated.

### 5.2 Filter bar

- Input at top of Firehose tab body (inline, not over the tab strip).
- Placeholder: `filter source · topic · payload  (regex /.../)`.
- Plain substring match by default, case-insensitive, across the concatenation `source_region + " " + topic + " " + payload_preview`.
- If the input starts with `/` and ends with `/` (or `/i`), treat inner text as a regex (flags limited to `i`). Invalid regex → red border on input, no rows filtered out.
- Debounce 150 ms. Filter state is **not** persisted across reloads (intentional — filters are session-local).

### 5.3 Kind tags

Derived from topic's top two segments:

| Topic prefix | Tag | Color |
|---|---|---|
| `hive/cognitive/*` | `cog` | `#8ac7ff` |
| `hive/sensory/*` | `sns` | `#b9d8a4` |
| `hive/motor/*` | `mot` | `#f5c679` |
| `hive/metacognition/*` | `meta` | `#ff8a88` |
| `hive/self/*` | `self` | `#d4b3ff` |
| `hive/modulator/*` | `mod` | `#ffd6a6` |
| `hive/attention/*` | `att` | `#aad0ff` |
| `hive/interoception/*` | `intr` | `#ffc4d8` |
| `hive/habit/*` | `hab` | `#bed1b8` |
| `hive/rhythm/*` | `rhy` | `#ffd08a` |
| `hive/system/heartbeat/*` | `hb` | `#9aa6bf` |
| `hive/system/region_stats/*` | `rst` | `#9aa6bf` |
| `hive/system/metrics/*` | `mtr` | `#9aa6bf` |
| `hive/system/sleep/*` | `slp` | `#b8b0e0` |
| `hive/system/spawn/*` | `spn` | `#c0e3b0` |
| `hive/system/codechange/*` | `cc` | `#ffb8b8` |
| `hive/broadcast/*` | `bcst` | `#d0d0d0` |
| (other) | `?` | `#808080` |

Colors reuse existing v1 `topicColors.ts` where overlap exists; v3 adds the missing prefixes. All colors honour the existing cache pattern to avoid per-frame `new Color(...)` allocation.

### 5.4 Click-through

See §7.

### 5.5 In-row payload expand

Each row has a chevron (`▸` / `▾`) at the right end. Expanded rows show a full JSON tree (reusing `JsonTree.tsx` from v2 Task 13) inline below the row with an indent. Expand state lives at the row-identity key `${observed_at}|${topic}|${source_region}` (same technique as v2 Messages).

## 6. Topics tab

### 6.1 Row schema

```
hive/cognitive/pfc/plan                       23 msg/s  ▁▃▅▇▅▃  4 pub   1.2 s ago
hive/system/heartbeat/+                       14 msg/s  ▁▁▂▂▂▂ 14 pub   0.4 s ago
hive/metacognition/error/detected              0 msg/s  ▁▁▁▁▁▁  1 pub  42.0 s ago
```

- Columns: `topic` (ellipsis) · `rate (msg/s, 60 s EWMA, α=0.1)` · `sparkline (6 buckets of 10 s each)` · `publishers (distinct source_region count over last 60 s)` · `last-seen (relative)`.
- Row height: `22 px`.
- Sort: descending by rate. Secondary sort by `last-seen` ascending.
- Row click: select the publisher with the most recent envelope on that topic + camera fit + inspector open. **Additionally** every region currently publishing that topic (within last 60 s) gets a 2 px outline ring in the scene until the user selects another row or dismisses.
- Row expand (chevron): inline list of last 5 envelopes on this topic, each clickable with the same select-flow.

### 6.2 Derivation

A `topicStats` selector computes over the envelope ring:

```ts
// pseudo
type TopicStat = {
  topic: string;
  ewmaRate: number;        // per-second, α = 0.1 updated every 1 s
  sparkBuckets: number[];  // length 6, each = count in 10 s bucket
  publishers: Set<string>; // source_region seen last 60 s
  lastSeenMs: number;      // performance.now() of most recent envelope
};
```

Selector runs on a 1 Hz interval (not per envelope). Subscribes read the map via zustand; re-render only when rate/spark/publisher set changes for the current render's top-N rows.

## 7. Metacognition tab

### 7.1 Row schema

```
14:22:05.112  amygdala          error.detected     LlmError: rate_limit_exceeded (model=claude…)
14:22:04.980  acc               conflict.observed  goal_collision: pfc.plan vs. motor.intent
14:22:02.441  prefrontal_cortex reflection.request analyze:rate_limit_exceeded
```

- Columns: `HH:MM:SS.mmm` · `source_region` · `event-kind` (last two topic segments joined with `.`) · `title/detail` (first 120 chars of the payload's most meaningful field).
- Title extraction: for `error.detected` use `payload.data.kind + ": " + payload.data.detail` when both present; fall back to `JSON.stringify(payload.data).slice(0, 120)`.
- Row coloring: `error.*` rows get a left-border accent in `#ff8a88`; `conflict.*` in `#ffc07a`; `reflection.*` in `rgba(210,212,220,.55)`.

### 7.2 Click-through

Standard select-flow (§8) **plus** the Messages section inside the inspector auto-expands to that envelope (jumping scroll to it and pre-expanding its JSON tree). Implementation: store carries a `pendingEnvelopeKey` field that Messages section consumes + clears on mount or on `selectRegion` change.

## 8. Interaction model — dock → scene → popup

Universal for every row in every tab:

```
row.click()
  └─> store.setSelectedRegion(row.regionName)
  │      ├─> Scene: CameraControls.fitToBox(mesh, true, { smoothTime: 0.6, padding: 0.5 })
  │      ├─> Scene: dimFactor := 0.25 for others, 1.0 for selected (v2 §3.1 unchanged)
  │      └─> Inspector slides in
  ├─> store.setPendingEnvelopeKey(row.envelopeKey)     // firehose + metacog only
  │      └─> Messages section scrolls + expands that envelope
  └─> dock: row stays highlighted with left-border accent until new click or region deselect

Esc
  └─> deselect + close inspector (v2 unchanged)
  └─> dock row highlight clears

[ / ]
  └─> cycle region (v2 unchanged); dock row highlight moves with selection

Topic row click
  └─> setSelectedRegion(mostRecentPublisher)
  └─> additionally: scene paints 2 px outline ring on every region in topic.publishers
       └─> outline clears on next selectedRegion change or after 15 s

`(backtick)
  └─> collapse/expand dock
```

**Hover preview (optional, flag-gated, cut if late):** hovering a firehose or metacog row for `> 250 ms` paints a 1 px outline ring on the source region in the scene, no camera move, no inspector change. Removing hover clears the ring. Behind a `VITE_DOCK_HOVER_PREVIEW=1` flag for the first ship; default off; reviewed after a session with live data.

## 9. Inspector Appendix section

### 9.1 Layout change

The Prompt section from v2 §3.2.4 is renamed **"Prompt & Appendix"** and contains two collapsibles:

1. **Prompt (DNA, _X_ kB)** — collapsed by default. Contents unchanged from v2: scrollable `<pre>` of `prompt.md`, reload button in the summary, auto-refetch on `last_error_ts`/`phase` change. Heading clarifies this file is immutable per the post-v2 append-only model.
2. **Appendix (rolling, _Y_ kB, _N_ entries)** — **expanded by default**. Parsed timeline of `memory/appendices/rolling.md`:
   - Split content on `^## ` headings (the file format documented in `region_template/appendix.py`).
   - Each entry rendered as a block: `timestamp` (11 px mono, secondary color) · `trigger` tag (11 px Inter 400, primary color) · body `<pre>` (10 px monospace).
   - Newest entry at top (reverse chronological). Scrollable, max-height 360 px.
   - When the file is `404` or zero entries: empty-state copy `"No appendix yet — region hasn't slept."`
   - Reload button in the summary.
   - Auto-refetch on `last_error_ts`/`phase` change, same rules as Prompt.

### 9.2 Backend — new REST route

`GET /api/regions/{name}/appendix`

- Sandboxed read (existing v2 `RegionReader` surface). Adds a new method `RegionReader.read_appendix(name: str) -> str | None`:
  - Resolves `regions/<name>/memory/appendices/rolling.md` via the existing sandbox root-escape guard.
  - Returns file contents (UTF-8) when present.
  - Returns `None` when file missing → route returns HTTP 404 with `{"error":"appendix_missing","message":"No appendix file for region"}`.
  - Same sandbox / 403 / file-too-large surface as existing endpoints (shared size cap; documented in v2 §4).
- `Cache-Control: no-store`.
- **No redaction.** Appendix content is LLM-authored narrative; it contains no secrets by construction. If an incident surfaces a secret in an appendix, that's a Hive-side bug to fix at write time, not observatory's concern.
- Route wired in the same file as v2 routes (`observatory/api/regions.py` or equivalent — see existing code for exact location).

### 9.3 Frontend wiring

- New REST wrapper `fetchRegionAppendix(name: string)` in `rest.ts`.
- New `useRegionAppendix` hook using the existing `useRegionFetch` pattern.
- New component `Appendix.tsx` under `inspector/sections/` that renders the parsed timeline.
- `Prompt.tsx` restructured into a parent `PromptAndAppendix.tsx` that hosts both collapsibles, or the existing `Prompt.tsx` gets a second collapsible sibling — implementer's call, with preference for the former to keep each child focused.

### 9.4 Entry parsing (minimal)

```ts
type AppendixEntry = {
  ts: string;       // raw ISO string from the "## <ts> — <trigger>" line
  trigger: string;  // the word after "— " on that line
  body: string;     // everything until the next "## " or EOF
};

function parseAppendix(md: string): AppendixEntry[] {
  // Split on ^## lines, keep the header line with its content, parse front metadata.
  // Tolerate trailing whitespace, missing "— trigger", and empty bodies.
  // If the file has no ## headings, return a single entry { ts: "", trigger: "", body: md }.
}
```

Parser lives in `observatory/web-src/src/inspector/sections/parseAppendix.ts` with unit tests.

## 10. HUD expansions

### 10.1 System-Metrics tile

New component `hud/SystemMetrics.tsx`. Reads three retained topics from store (already captured at subscribe time since v1):

| Source | Shown |
|---|---|
| `hive/system/metrics/compute` | `total_cpu_pct` · `total_mem_mb` |
| `hive/system/metrics/tokens` | `total_input_tokens` · `total_output_tokens` |
| `hive/system/metrics/region_health` | 14-cell grid, one per known region, coloured by liveness status |

Layout: two rows of stats (compute + tokens) above the region-health heatmap. Heatmap cell is `10 × 10 px` with `2 px` gap; cell color:
- `alive` → `#85d19a`
- `stale` → `#d6b85a` (heartbeat missed)
- `dead` → `#d66a6a`
- `unknown` → `rgba(136,140,152,.35)`

Hover a cell: show `{regionName} · {status} · last-hb HH:MM:SS` in a tooltip.

Tile sits in the HUD top-left column below the Self tile (§10.2) and above the v1 Counters.

### 10.2 Self-State tile

Existing v1 `SelfPanel` currently shows `hive/self/identity` only (pre-v3 commits dropped `developmental_stage` + `age`; v1 pulled partial identity text). v3 replaces it with a tabbed tile:

Tabs across top: **Identity · Values · Personality · Index** (11 px Inter 300, active-tab underline).

Each tab renders:

- **Identity:** key-value list of the payload's top-level string/number fields. One row per key.
- **Values:** if payload.data is a list, render as bullets; if dict, key-value list.
- **Personality:** same as Values.
- **Index (autobiographical_index):** list of entries, newest-first, each `ts · headline`. Truncated at 20 rows; "N more…" footer if longer.

Missing topic → tab shows `No data yet — mPFC hasn't published.`

Implementation note: the v1 SelfPanel component is removed; this component replaces it with a superset of functionality.

## 11. Messages section upgrade

v2 §3.2.5 shipped the Messages log with `payload-preview` (first 80 chars). v3 adds:

- Chevron on each row; clicking expands a `JsonTree`-rendered full payload inline below the row (same component used by STM in v2 and by Firehose in v3).
- Expand state keyed by `${observed_at}|${topic}`, already stable since v2 Task 14.
- The `pendingEnvelopeKey` store field (§7.2, §8) causes Messages to scroll that envelope into view and auto-expand it on arrival.

No new backend surface; this is a pure frontend enhancement of the existing component.

## 12. Data model — zustand store additions

```ts
interface Store {
  // existing v1/v2 fields unchanged …

  // Dock
  dockTab: 'firehose' | 'topics' | 'metacog';
  dockCollapsed: boolean;          // persisted
  dockHeight: number;              // persisted, [120, 520]
  dockPaused: boolean;             // transient
  firehoseFilter: string;          // transient
  expandedRowIds: Set<string>;     // transient, cleared on tab change

  // Derived/transient
  pendingEnvelopeKey: string | null; // consumed by Messages on mount/change

  // Actions
  setDockTab: (tab: Store['dockTab']) => void;
  setDockCollapsed: (b: boolean) => void;
  setDockHeight: (n: number) => void;
  setDockPaused: (b: boolean) => void;
  setFirehoseFilter: (s: string) => void;
  toggleRowExpand: (id: string) => void;
  setPendingEnvelopeKey: (key: string | null) => void;
}
```

Persistence layer: `useDockPersistence` hook reads/writes `localStorage` on mount / on change (debounced 200 ms) — hook, not middleware, to keep the store's serialization behaviour unchanged.

## 13. File & module layout

New files:

```
observatory/
  region_reader.py               # extended: read_appendix()
  api/regions.py                 # extended: /api/regions/{name}/appendix route
  web-src/src/
    dock/
      Dock.tsx
      DockTabStrip.tsx
      Firehose.tsx
      Topics.tsx
      Metacog.tsx
      useTopicStats.ts
      useDockPersistence.ts
      useDockKeys.ts
    hud/
      SystemMetrics.tsx
      SelfState.tsx               # replaces SelfPanel.tsx
    inspector/sections/
      Appendix.tsx
      parseAppendix.ts
```

Modified files (v2 → v3 changes):

```
observatory/web-src/src/
  store.ts                       # dock fields + pendingEnvelopeKey
  rest.ts                        # fetchRegionAppendix
  ws.ts                          # unchanged
  App.tsx                        # mount Dock; remove SelfPanel import
  topicColors.ts                 # add missing prefixes (interoception, habit, etc.)
  inspector/sections/
    Prompt.tsx  →  PromptAndAppendix.tsx  (or sibling Appendix.tsx)
    Messages.tsx                 # add JsonTree expand
```

Deleted files:

```
observatory/web-src/src/hud/SelfPanel.tsx   # replaced by SelfState.tsx
```

## 14. Testing strategy

**Backend (pytest, observatory/tests/unit/):**

- `test_region_reader_appendix.py`:
  - Reads `memory/appendices/rolling.md` when present.
  - Returns `None` when missing.
  - Sandbox escape attempts (`../../etc/passwd`, symlinks) blocked — reuses v2 `_deny` helper test suite.
  - Size cap applies (same cap as `read_prompt`).
- `test_api_regions.py` extended:
  - `/api/regions/{name}/appendix` 200 path returns content.
  - 404 path returns the `{error,message}` body.
  - Sandbox 403 path surfaces flat error body.
  - `Cache-Control: no-store` header present.

**Backend component (pytest, observatory/tests/component/):**

- `test_end_to_end.py` extended: seed a region with an appendix file, assert `/api/regions/<name>/appendix` returns it through the real FastAPI mount.

**Frontend (vitest, observatory/web-src/):**

- `parseAppendix.test.ts`: empty, single-entry, multi-entry, missing-trigger, trailing-whitespace, no-headings fallback.
- `Appendix.test.tsx`: renders entries, empty state on 404, reload button.
- `Firehose.test.tsx`: filter (substring + regex), pause + resume, row expand.
- `Topics.test.tsx`: EWMA rate updates, sorting, row expand into recent-5.
- `Metacog.test.tsx`: coloring per kind, tab badge count, click-through `pendingEnvelopeKey` set.
- `SystemMetrics.test.tsx`: renders from retained topics; missing-topic fallback.
- `SelfState.test.tsx`: tab switching, per-tab empty states.
- `Messages.test.tsx` extended: chevron expand, `pendingEnvelopeKey` consumption.
- `useDockPersistence.test.ts`: localStorage round-trip, clamp on out-of-range height.
- `useTopicStats.test.ts`: EWMA math, publishers set decay after 60 s.

**Visual E2E:** deferred to human-loop review (same pattern as v1 Task 16 / v2 Task 15).

## 15. Performance constraints

- Firehose max rendered rows: `1000`. Above that, the oldest rows are dropped from the rendered window regardless of ring size.
- Topics selector runs at `1 Hz`, not per envelope.
- JsonTree inline expand reuses the v2 component's existing recursion depth cap.
- No per-frame allocations from dock components (the `topicColors` module-level cache is extended, not duplicated).
- Store updates from dock state (tab/collapsed/height/paused/filter/expanded) must not trigger re-renders of Scene-tree components. Verify via `<Scene>`-level `React.memo` equality on the region-map selector (already in place from v2).

## 16. Open questions

- **Dock `Space`-to-pause vs. Scene `Space`-to-anything:** no Scene binding on Space today; assume v3 takes it when dock is focused. If v4 introduces a Scene Space binding, dock defers and uses `P` instead.
- **Topic-row scene outline decay:** 15 s constant in §8 is a guess; tune after live-data review.
- **Metacog title field selection:** §7.1 uses `payload.data.kind + ": " + payload.data.detail` as a best-effort heuristic. If real payloads have a different shape, adjust the parser in the implementer task rather than the spec.
- **Hover preview flag default:** Section 8 flags this `VITE_DOCK_HOVER_PREVIEW=1` default off for ship. Revisit after session-of-use review.

## 17. Non-goals — explicit

This section exists to pre-empt scope creep during implementation:

- No LTM read.
- No handler source read.
- No new Hive-side publishes.
- No new WS message types — dock is purely a view over the existing envelope stream + retained state.
- No inspector state persistence — the dock persists, the inspector does not (by design, the inspector is per-session).
- No topic *authoring* or MQTT publish UI — this is an instrument, not a participant (CLAUDE.md §Scope boundary).
