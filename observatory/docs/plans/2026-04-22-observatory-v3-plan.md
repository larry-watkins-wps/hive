# Observatory v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Fresh implementer subagent per task; two-stage review between tasks per `observatory/CLAUDE.md`.

**Goal:** Ship the v3 "real-time visibility" milestone — a collapsible resizable bottom dock with three tabs (Firehose / Topics / Metacognition), an inspector Appendix section that renders `memory/appendices/rolling.md` alongside `prompt.md`, and HUD tiles for `hive/system/metrics/*` and the four `hive/self/*` retained topics. Plus a full-envelope JSON expand in the existing Messages section and a unified dock-row → scene-focus → region-popup interaction model.

**Architecture:** Backend adds a single new REST route (`/api/regions/{name}/appendix`) backed by a new `RegionReader.read_appendix` method. Frontend adds a `dock/` subtree (frame + tab strip + three tabs + persistence hooks + keyboard hook), grows the zustand store with dock state + `pendingEnvelopeKey`, replaces `hud/SelfPanel.tsx` with `hud/SelfState.tsx`, adds `hud/SystemMetrics.tsx`, and restructures the inspector's Prompt section into Prompt + Appendix. No new runtime dependencies. No WS changes — all three dock tabs are computed views over the existing envelope ring plus retained-snapshot state.

**Tech Stack:** same as v1/v2. React 18, TypeScript 5, Vite 5, Tailwind 3, zustand 4, three.js + @react-three/fiber + @react-three/drei, vitest; FastAPI + pydantic backend; pytest + pytest-asyncio.

**Spec:** [observatory/docs/specs/2026-04-22-observatory-v3-design.md](../specs/2026-04-22-observatory-v3-design.md) — authoritative. Plan conflicts with spec → spec wins; log the discrepancy in `observatory/memory/decisions.md`.

**Tracking convention** (per `observatory/CLAUDE.md`):
- Per-task implementer prompts: `observatory/prompts/v3-task-NN-<slug>.md`
- Non-obvious decisions: `observatory/memory/decisions.md` (append-only)
- One commit per plan task with HEREDOC message ending with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- Two-stage review after each implementer (spec-compliance `general-purpose`, then code-quality `superpowers:code-reviewer`); fix-loop on anything Important+

## Drifts from spec & current state that implementers must know

1. **`rest.ts` already throws `RestError` with a parsed flat error body** (see `observatory/web-src/src/api/rest.ts:17-51`). New fetchers in Task 3 reuse the existing `_get` helper — do NOT duplicate the error handling.
2. **Store's `extractAmbient` currently pulls `hive/self/developmental_stage` and `hive/self/age`** (see `store.ts:75-79`), but those topics were dropped in commit `155854d`. Task 2 removes the dead code paths and adds handlers for `values` / `personality` / `autobiographical_index`.
3. **`SelfPanel.tsx` still renders `developmental_stage` + `age` badges** (`hud/SelfPanel.tsx:10-11`) — it's been showing `"unknown"` / `"—"` for two commits. Task 9 deletes `SelfPanel.tsx` and replaces it with `hud/SelfState.tsx`.
4. **`hud/Hud.tsx` mounts `SelfPanel`, `Modulators`, and `Counters`** in that order. Task 9 updates `Hud.tsx` to mount `SelfState` + `SystemMetrics` + `Modulators` + `Counters` in the new order documented in §10 of the spec (self on top, metrics below it, modulators + counters unchanged).
5. **Inspector `format.ts` already exports `fmtBytes`.** Reuse it in Task 8's Appendix header (`"{N} entries · {fmtBytes(body.length)}"`) — no second implementation.
6. **`JsonTree.tsx` is already in `inspector/sections/`** (introduced in v2 Task 13). Firehose (Task 5), Metacog (Task 7), and Messages (Task 10) all import the same component — no copy.
7. **Messages section already keys expand state by `${observed_at}|${topic}`** (v2 Task 14). Task 10's `pendingEnvelopeKey` consumption uses the same key shape.
8. **`Hud.tsx` currently uses Tailwind `bg-hive-panel/80` + `backdrop-blur`.** v3 tiles match this visual language — the new tiles inherit the HUD stack's existing container styling.
9. **Dock `Space`-to-pause must guard against input focus** the same way `useInspectorKeys.ts:3-13` guards `[` / `]` / `R`. Factor the guard into a shared helper if clean; otherwise inline-copy with a comment.
10. **The `hud/` stack floats top-left.** Dock renders at fixed bottom, full viewport width. Inspector's right slide-over z-indexes above the dock (so the inspector panel overlays the right 420 px of the dock). No reflow on inspector open/close.
11. **`observatory/prompts/` has v1 and v2 prompts already committed.** New files use `v3-task-NN-<slug>.md` naming.
12. **`regions/<name>/memory/appendices/rolling.md` is lazy-created on first sleep** (see `region_template/appendix.py`). Fresh / newly spawned regions will legitimately 404 this endpoint until their first sleep cycle — empty-state UI handles this (§9.1 of spec).
13. **Regex matching in TypeScript:** prefer `str.match(re)` over `re.exec(str)` in this plan's code samples. Both work; the plan uses `.match()` throughout to avoid a false-positive security hook that flags `.exec(` as a `child_process.exec` call.

---

## File Structure (locked in up front)

### Backend (Python)

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/region_reader.py` (modify) | Add `read_appendix(region) -> str` (raises `SandboxError(404)` on missing) | 1 |
| `observatory/api.py` (modify) | Register `/api/regions/{name}/appendix` route | 1 |

### Backend tests

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/tests/unit/test_region_reader.py` (modify) | Add happy-path, missing-404, sandbox, oversize tests for `read_appendix` | 1 |
| `observatory/tests/unit/test_api_regions_v2.py` (modify) | Add happy-path + 404 + 403 tests for `/appendix` route | 1 |
| `observatory/tests/component/test_end_to_end.py` (modify) | Seed a region with `memory/appendices/rolling.md`; assert `/appendix` returns content via real broker + real FastAPI app | 11 |

### Frontend store + API

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/src/store.ts` (modify) | Add dock state + `pendingEnvelopeKey` + self-state retained handling + `retained` raw map | 2, 9 |
| `observatory/web-src/src/api/rest.ts` (modify) | Add `fetchAppendix` | 3 |
| `observatory/web-src/src/inspector/sections/parseAppendix.ts` | Pure parser: `parseAppendix(md: string): AppendixEntry[]` | 3 |
| `observatory/web-src/src/inspector/useRegionAppendix.ts` | `{loading, error, data, reload}` hook (reuses `useRegionFetch` pattern) | 3 |

### Frontend dock

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/src/dock/Dock.tsx` | Frame: bottom container, resize handle, collapse toggle, height persistence, mounts the active tab | 4 |
| `observatory/web-src/src/dock/DockTabStrip.tsx` | Top strip: three tab buttons + live counts + pause + collapse | 4 |
| `observatory/web-src/src/dock/useDockPersistence.ts` | Load/save `dock.height` + `dock.collapsed` to localStorage; clamps height to `[120, 520]` | 4 |
| `observatory/web-src/src/dock/useDockKeys.ts` | Window-level keydown for `` ` `` (collapse) and `Space` (pause, dock-focused only); input-focus guard | 4 |
| `observatory/web-src/src/dock/selectRegionFromRow.ts` | Pure helper implementing the universal click-through: sets `selectedRegion` + `pendingEnvelopeKey` | 4 |
| `observatory/web-src/src/dock/Firehose.tsx` | Tab: filter bar + scrollable row list + in-row JsonTree expand | 5 |
| `observatory/web-src/src/dock/FirehoseRow.tsx` | One row: timestamp · source · `→ topic` · kind badge · payload-preview · chevron | 5 |
| `observatory/web-src/src/dock/useTopicStats.ts` | 1 Hz selector that builds `Map<topic, TopicStat>` from envelope ring | 6 |
| `observatory/web-src/src/dock/Topics.tsx` | Tab: sorted topic rows + per-row expand (last-5 envelopes) | 6 |
| `observatory/web-src/src/dock/Metacog.tsx` | Tab: rows for `hive/metacognition/#`, colored by kind | 7 |

### Frontend HUD + inspector

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/src/hud/SystemMetrics.tsx` | Retained `hive/system/metrics/*` tile: CPU/mem + token totals + region-health heatmap | 9 |
| `observatory/web-src/src/hud/SelfState.tsx` | Replaces `SelfPanel.tsx`: 4 tabs (Identity / Values / Personality / Autobio) | 9 |
| `observatory/web-src/src/hud/SelfPanel.tsx` | **Deleted** | 9 |
| `observatory/web-src/src/hud/Hud.tsx` (modify) | Remount children: `<SelfState/>`, `<SystemMetrics/>`, `<Modulators/>`, `<Counters/>` | 9 |
| `observatory/web-src/src/inspector/sections/Appendix.tsx` | Parsed timeline view | 8 |
| `observatory/web-src/src/inspector/sections/Prompt.tsx` (modify) | Header label "Prompt (DNA, N kB)"; remains a collapsible `<details>` | 8 |
| `observatory/web-src/src/inspector/Inspector.tsx` (modify) | Mount `<Appendix />` directly below `<Prompt />` in section list | 8 |
| `observatory/web-src/src/inspector/sections/Messages.tsx` (modify) | Add JsonTree chevron expand per row; consume `pendingEnvelopeKey` | 10 |
| `observatory/web-src/src/scene/topicColors.ts` (modify) | Extend topic → color map for interoception / habit / heartbeat / region_stats / metrics / sleep / spawn / codechange / broadcast. Export `kindTag(topic)`. | 5 |

### Frontend mount

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/src/App.tsx` (modify) | Mount `<Dock />` at bottom; install `useDockKeys` | 4 |

### Frontend tests

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/src/store.test.ts` (modify) | Dock fields default + mutators; `pendingEnvelopeKey` set/clear; new self-topic retained handling; raw `retained` map | 2, 9 |
| `observatory/web-src/src/api/rest.test.ts` (modify) | `fetchAppendix` 200, 404 (throws `RestError`) | 3 |
| `observatory/web-src/src/inspector/sections/parseAppendix.test.ts` | Empty, single, multi, missing-trigger, trailing-whitespace, no-headings | 3 |
| `observatory/web-src/src/inspector/useRegionAppendix.test.ts` | Hook loading → data; hook loading → error → reload | 3 |
| `observatory/web-src/src/dock/useDockPersistence.test.ts` | localStorage round-trip; clamp out-of-range height | 4 |
| `observatory/web-src/src/dock/Dock.test.tsx` | Default height; collapse toggle; resize handle | 4 |
| `observatory/web-src/src/dock/selectRegionFromRow.test.ts` | Sets `selectedRegion` + `pendingEnvelopeKey` | 4 |
| `observatory/web-src/src/dock/Firehose.test.tsx` | Substring filter; regex filter; pause/resume; row JsonTree expand | 5 |
| `observatory/web-src/src/scene/topicColors.test.ts` (modify) | Add kindTag cases for the new prefixes | 5 |
| `observatory/web-src/src/dock/useTopicStats.test.ts` | EWMA math, publishers set decay, sparkline buckets | 6 |
| `observatory/web-src/src/dock/Topics.test.tsx` | Renders sorted by rate; expand shows last-5 | 6 |
| `observatory/web-src/src/dock/Metacog.test.tsx` | Coloring per kind; title extraction | 7 |
| `observatory/web-src/src/inspector/sections/Appendix.test.tsx` | Entries rendered; empty state on 404; reload refetches | 8 |
| `observatory/web-src/src/hud/SystemMetrics.test.tsx` | Renders from retained; missing-topic fallbacks | 9 |
| `observatory/web-src/src/hud/SelfState.test.tsx` | Tab switching; empty-state per tab | 9 |
| `observatory/web-src/src/inspector/Messages.test.tsx` (modify) | JsonTree expand; `pendingEnvelopeKey` scroll + auto-expand | 10 |

### Docs / tracking (per observatory/CLAUDE.md)

| File | Action |
|---|---|
| `observatory/HANDOFF.md` | Bump at the end of every task (progress table + changelog) |
| `observatory/memory/decisions.md` | Append entry per non-obvious call |
| `observatory/prompts/v3-task-NN-<slug>.md` | Store implementer prompts for audit |

---

## Task 1 — Backend: `read_appendix` + `/api/regions/{name}/appendix` route

**Files:**
- Modify: `observatory/region_reader.py`
- Modify: `observatory/api.py`
- Modify: `observatory/tests/unit/test_region_reader.py`
- Modify: `observatory/tests/unit/test_api_regions_v2.py`

### Context for implementer

The observatory's sandboxed `RegionReader` already handles `prompt.md`, `stm.json`, `subscriptions.yaml`, `config.yaml`, and the handlers directory (see `region_reader.py:73-126`). The v3 spec §9 adds `memory/appendices/rolling.md`: a lazy-created, append-only file written by the region runtime at sleep time (see `region_template/appendix.py`). Fresh regions legitimately don't have this file — the route must return 404 when missing and the frontend renders an empty state.

**Key constraint:** the existing `_validate()` pipeline in `region_reader.py:153-205` already emits 404 for missing files (see line 190: `self._deny(..., 404, "missing", ...)`). You do NOT add custom missing-handling — reusing `_validate()` via a new `read_appendix()` is the entire method body.

**No redaction.** Per spec §9.2, appendix content is LLM-authored narrative. No `_redact()` pass.

### Steps

- [ ] **Step 1 — Write failing reader tests.**

  Open `observatory/tests/unit/test_region_reader.py`. Append:

  ```python
  class TestReadAppendix:
      def test_reads_appendix_contents(self, reader_fixture):
          reader, root = reader_fixture
          region = root / "good_region"
          appendix_dir = region / "memory" / "appendices"
          appendix_dir.mkdir(parents=True, exist_ok=True)
          (appendix_dir / "rolling.md").write_text(
              "## 2026-04-22T10:00:00Z - sleep\n\nLearned that topic X ...\n",
              encoding="utf-8",
          )
          assert "topic X" in reader.read_appendix("good_region")

      def test_missing_appendix_raises_404(self, reader_fixture):
          reader, _ = reader_fixture
          with pytest.raises(SandboxError) as exc:
              reader.read_appendix("good_region")
          assert exc.value.code == 404

      def test_invalid_region_name(self, reader_fixture):
          reader, _ = reader_fixture
          with pytest.raises(SandboxError) as exc:
              reader.read_appendix("../evil")
          assert exc.value.code == 404

      def test_oversize_appendix_rejected(self, reader_fixture):
          reader, root = reader_fixture
          region = root / "good_region"
          appendix_dir = region / "memory" / "appendices"
          appendix_dir.mkdir(parents=True, exist_ok=True)
          from observatory.region_reader import MAX_FILE_BYTES
          (appendix_dir / "rolling.md").write_bytes(b"a" * (MAX_FILE_BYTES + 1))
          with pytest.raises(SandboxError) as exc:
              reader.read_appendix("good_region")
          assert exc.value.code == 413
  ```

  Confirm the `reader_fixture` defined at the top of `test_region_reader.py` sets up `good_region` under a tmpdir — v2 Tasks 1-3 already added it.

- [ ] **Step 2 — Run to verify failure.**

  ```
  python -m pytest observatory/tests/unit/test_region_reader.py::TestReadAppendix -v
  ```
  Expected: 4 FAILED with `AttributeError: 'RegionReader' object has no attribute 'read_appendix'`.

- [ ] **Step 3 — Implement `read_appendix`.**

  Open `observatory/region_reader.py`. Add after `read_config` (around line 89):

  ```python
  def read_appendix(self, region: str) -> str:
      """Read ``regions/<region>/memory/appendices/rolling.md``.

      Raises ``SandboxError(code=404)`` when the file doesn't exist - a
      fresh region that has never slept legitimately lacks this file.
      """
      path = self._validate(
          region,
          "memory/appendices/rolling.md",
          method="read_appendix",
      )
      return path.read_text(encoding="utf-8")
  ```

- [ ] **Step 4 — Run reader tests.** Expected: all 4 PASS.

- [ ] **Step 5 — Write failing API tests.**

  Open `observatory/tests/unit/test_api_regions_v2.py`. Append:

  ```python
  class TestAppendixRoute:
      def test_returns_appendix_text(self, seeded_app):
          app, root = seeded_app
          region_dir = root / "good_region"
          app_dir = region_dir / "memory" / "appendices"
          app_dir.mkdir(parents=True, exist_ok=True)
          (app_dir / "rolling.md").write_text(
              "## 2026-04-22T10:00:00Z - sleep\n\nbody\n", encoding="utf-8"
          )
          client = TestClient(app)
          r = client.get("/api/regions/good_region/appendix")
          assert r.status_code == 200
          assert r.headers["cache-control"] == "no-store"
          assert "body" in r.text

      def test_404_when_missing(self, seeded_app):
          app, _ = seeded_app
          client = TestClient(app)
          r = client.get("/api/regions/good_region/appendix")
          assert r.status_code == 404
          body = r.json()
          assert body["error"] == "not_found"

      def test_404_when_region_unknown(self, seeded_app):
          app, _ = seeded_app
          client = TestClient(app)
          r = client.get("/api/regions/unknown/appendix")
          assert r.status_code == 404
          assert r.json()["error"] == "not_found"
  ```

  Use the existing `seeded_app` fixture (v2 Task 4 landed it).

- [ ] **Step 6 — Run to verify failure.** Expected: 3 FAILED.

- [ ] **Step 7 — Add the `/appendix` route.**

  Open `observatory/api.py`. Register under `get_prompt`:

  ```python
  @router.get("/regions/{name}/appendix", response_class=PlainTextResponse)
  def get_appendix(name: str, request: Request) -> PlainTextResponse:
      _ensure_region(request, name)
      try:
          text = _reader(request).read_appendix(name)
      except SandboxError as e:
          raise HTTPException(status_code=e.code, detail=_error_detail(e)) from e
      return PlainTextResponse(
          text,
          media_type="text/plain; charset=utf-8",
          headers=_NO_STORE,
      )
  ```

- [ ] **Step 8 — Run full test suite + ruff.**

  ```
  python -m pytest observatory/tests/unit/ -q
  python -m ruff check observatory/
  ```
  Expected: all green.

- [ ] **Step 9 — Commit.**

  ```bash
  git add observatory/region_reader.py observatory/api.py observatory/tests/unit/
  git commit -m "$(cat <<'EOF'
  observatory: /appendix route reads rolling.md (v3 task 1)

  Adds RegionReader.read_appendix (reuses _validate() pipeline - 404 on
  missing, 403 on sandbox violation, 413 on oversize, no redaction) and
  GET /api/regions/{name}/appendix route mirroring the /prompt shape.

  Fresh regions legitimately 404 this endpoint until first sleep creates
  memory/appendices/rolling.md (see region_template/appendix.py).

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 2 — Store: dock state + `pendingEnvelopeKey` + self-state retained handling

**Files:**
- Modify: `observatory/web-src/src/store.ts`
- Modify: `observatory/web-src/src/store.test.ts`

### Context for implementer

Per spec §12, v3 grows the zustand store with six dock-related fields, one `pendingEnvelopeKey`, and expanded `Ambient.self` coverage for the four `hive/self/*` retained topics. The store currently handles `identity`, `developmental_stage`, and `age` — the latter two are dead code (topics dropped in commit `155854d`). Remove them; add `values`, `personality`, `autobiographical_index`.

**Persistence:** the dock-persistence hook in Task 4 reads/writes localStorage and hydrates store state on mount; the store itself is persistence-agnostic.

**No changes to the `envelopes` ring or `envelopesReceivedTotal` counter.** Both remain the source of truth for Firehose / Topics / Metacog selectors.

### Steps

- [ ] **Step 1 — Write failing store tests for dock + pendingEnvelopeKey.**

  Open `observatory/web-src/src/store.test.ts`. Append:

  ```typescript
  describe('dock state', () => {
    it('has sensible defaults', () => {
      const s = createStore().getState();
      expect(s.dockTab).toBe('firehose');
      expect(s.dockCollapsed).toBe(false);
      expect(s.dockHeight).toBe(220);
      expect(s.dockPaused).toBe(false);
      expect(s.firehoseFilter).toBe('');
      expect(s.expandedRowIds.size).toBe(0);
      expect(s.pendingEnvelopeKey).toBeNull();
    });

    it('setDockTab switches tab and clears expandedRowIds', () => {
      const store = createStore();
      store.getState().toggleRowExpand('row-1');
      expect(store.getState().expandedRowIds.has('row-1')).toBe(true);
      store.getState().setDockTab('topics');
      expect(store.getState().dockTab).toBe('topics');
      expect(store.getState().expandedRowIds.size).toBe(0);
    });

    it('setDockHeight clamps to [120, 520]', () => {
      const store = createStore();
      store.getState().setDockHeight(50);
      expect(store.getState().dockHeight).toBe(120);
      store.getState().setDockHeight(1000);
      expect(store.getState().dockHeight).toBe(520);
      store.getState().setDockHeight(300);
      expect(store.getState().dockHeight).toBe(300);
    });

    it('toggleRowExpand toggles set membership', () => {
      const store = createStore();
      store.getState().toggleRowExpand('a');
      expect(store.getState().expandedRowIds.has('a')).toBe(true);
      store.getState().toggleRowExpand('a');
      expect(store.getState().expandedRowIds.has('a')).toBe(false);
    });

    it('setPendingEnvelopeKey sets and clears', () => {
      const store = createStore();
      store.getState().setPendingEnvelopeKey('123|hive/a');
      expect(store.getState().pendingEnvelopeKey).toBe('123|hive/a');
      store.getState().setPendingEnvelopeKey(null);
      expect(store.getState().pendingEnvelopeKey).toBeNull();
    });
  });

  describe('self-state retained handling', () => {
    it('applySnapshot picks up identity / values / personality / autobiographical_index', () => {
      const store = createStore();
      store.getState().applySnapshot({
        regions: {},
        retained: {
          'hive/self/identity': { payload: { value: 'I am Hive.' } },
          'hive/self/values': { payload: { value: ['curiosity', 'care'] } },
          'hive/self/personality': { payload: { value: { warmth: 0.8 } } },
          'hive/self/autobiographical_index': { payload: { value: [{ ts: '2026-04-22', headline: 'first wake' }] } },
        },
        recent: [],
        server_version: 'test',
      });
      const self = store.getState().ambient.self;
      expect(self.identity).toBe('I am Hive.');
      expect(self.values).toEqual(['curiosity', 'care']);
      expect(self.personality).toEqual({ warmth: 0.8 });
      expect(self.autobiographical_index).toEqual([{ ts: '2026-04-22', headline: 'first wake' }]);
    });

    it('applyRetained handles the four self topics live', () => {
      const store = createStore();
      store.getState().applyRetained('hive/self/values', { value: ['a', 'b'] });
      expect(store.getState().ambient.self.values).toEqual(['a', 'b']);
    });
  });
  ```

- [ ] **Step 2 — Run to verify failure.**

  ```
  cd observatory/web-src && npx vitest run store.test.ts
  ```
  Expected: FAILED.

- [ ] **Step 3 — Extend the `Ambient` type.**

  In `observatory/web-src/src/store.ts` replace `Ambient`:

  ```typescript
  export type Ambient = {
    modulators: Partial<Record<'cortisol' | 'dopamine' | 'serotonin' | 'norepinephrine' | 'oxytocin' | 'acetylcholine', number>>;
    self: {
      identity?: string;
      values?: unknown;
      personality?: unknown;
      autobiographical_index?: unknown;
      felt_state?: string;
    };
  };
  ```

  (Remove `developmental_stage` and `age`.)

- [ ] **Step 4 — Extend the `State` type with dock fields + actions.**

  ```typescript
  type State = {
    // existing fields unchanged through `cycle` …

    // v3 dock
    dockTab: 'firehose' | 'topics' | 'metacog';
    dockCollapsed: boolean;
    dockHeight: number;              // clamped [120, 520]
    dockPaused: boolean;
    firehoseFilter: string;
    expandedRowIds: Set<string>;
    pendingEnvelopeKey: string | null;

    setDockTab: (tab: 'firehose' | 'topics' | 'metacog') => void;
    setDockCollapsed: (b: boolean) => void;
    setDockHeight: (n: number) => void;
    setDockPaused: (b: boolean) => void;
    setFirehoseFilter: (s: string) => void;
    toggleRowExpand: (id: string) => void;
    setPendingEnvelopeKey: (key: string | null) => void;
  };
  ```

- [ ] **Step 5 — Update `extractAmbient` + `applyRetained` for the four self topics.**

  ```typescript
  function extractAmbient(retained: Snapshot['retained']): Ambient {
    const ambient: Ambient = { modulators: {}, self: {} };
    for (const [topic, env] of Object.entries(retained)) {
      const payload = env.payload ?? {};
      const value = (payload as { value?: unknown }).value;
      if (topic.startsWith('hive/modulator/')) {
        const name = topic.slice('hive/modulator/'.length);
        if (!isModulatorName(name)) continue;
        const v = Number(value ?? NaN);
        if (!Number.isNaN(v)) ambient.modulators[name] = v;
      } else if (topic === 'hive/self/identity') ambient.self.identity = String(value ?? '');
      else if (topic === 'hive/self/values') ambient.self.values = value;
      else if (topic === 'hive/self/personality') ambient.self.personality = value;
      else if (topic === 'hive/self/autobiographical_index') ambient.self.autobiographical_index = value;
      else if (topic === 'hive/interoception/felt_state') ambient.self.felt_state = String(value ?? '');
    }
    return ambient;
  }
  ```

  Update `applyRetained` similarly:

  ```typescript
  applyRetained: (topic, payload) => {
    const ambient = {
      ...get().ambient,
      modulators: { ...get().ambient.modulators },
      self: { ...get().ambient.self },
    };
    const value = (payload as { value?: unknown }).value;
    if (topic.startsWith('hive/modulator/')) {
      const name = topic.slice('hive/modulator/'.length);
      if (!isModulatorName(name)) return;
      ambient.modulators[name] = Number(value ?? 0);
    } else if (topic === 'hive/self/identity') ambient.self.identity = String(value ?? '');
    else if (topic === 'hive/self/values') ambient.self.values = value;
    else if (topic === 'hive/self/personality') ambient.self.personality = value;
    else if (topic === 'hive/self/autobiographical_index') ambient.self.autobiographical_index = value;
    else if (topic === 'hive/interoception/felt_state') ambient.self.felt_state = String(value ?? '');
    set({ ambient });
  },
  ```

- [ ] **Step 6 — Add dock fields + action implementations to the store factory.**

  ```typescript
  export function createStore(): UseBoundStore<StoreApi<State>> {
    return create<State>((set, get) => ({
      // existing v1/v2 state …

      dockTab: 'firehose',
      dockCollapsed: false,
      dockHeight: 220,
      dockPaused: false,
      firehoseFilter: '',
      expandedRowIds: new Set<string>(),
      pendingEnvelopeKey: null,

      setDockTab: (tab) => set({ dockTab: tab, expandedRowIds: new Set() }),
      setDockCollapsed: (b) => set({ dockCollapsed: b }),
      setDockHeight: (n) => set({ dockHeight: Math.max(120, Math.min(520, n)) }),
      setDockPaused: (b) => set({ dockPaused: b }),
      setFirehoseFilter: (s) => set({ firehoseFilter: s }),
      toggleRowExpand: (id) => {
        const next = new Set(get().expandedRowIds);
        if (next.has(id)) next.delete(id); else next.add(id);
        set({ expandedRowIds: next });
      },
      setPendingEnvelopeKey: (key) => set({ pendingEnvelopeKey: key }),
    }));
  }
  ```

- [ ] **Step 7 — Handle the removed-field follow-up in `SelfPanel.tsx`.**

  After Step 5, `hud/SelfPanel.tsx` will fail typecheck (it reads `self.developmental_stage`). Two acceptable approaches:

  - Quick fix: narrow `// @ts-expect-error deleted field; scheduled for deletion in Task 9` comments on lines 10-11. Component keeps rendering stale "unknown"/"—" until Task 9.
  - Clean fix: delete `hud/SelfPanel.tsx` now and remove the import from `Hud.tsx`; the top-left stack temporarily renders without a self panel until Task 9 adds `SelfState.tsx`.

  Take whichever the implementer's review prefers; document the call in `decisions.md`.

- [ ] **Step 8 — Run tests + typecheck.**

  ```
  cd observatory/web-src && npx vitest run store.test.ts && npx tsc -b
  ```
  Expected: all green.

- [ ] **Step 9 — Commit.**

  ```bash
  git add observatory/web-src/src/store.ts observatory/web-src/src/store.test.ts
  # plus whichever of: observatory/web-src/src/hud/SelfPanel.tsx OR observatory/web-src/src/hud/Hud.tsx
  git commit -m "$(cat <<'EOF'
  observatory: store — dock + pendingEnvelopeKey + self-state topics (v3 task 2)

  Adds six dock fields (dockTab/Collapsed/Height/Paused + firehoseFilter
  + expandedRowIds) + pendingEnvelopeKey + actions. Replaces dead
  developmental_stage/age handling (topics dropped in 155854d) with
  values/personality/autobiographical_index off the four hive/self/*
  topics. Clamps dockHeight to [120, 520]. Clears expandedRowIds on
  tab switch.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 3 — REST wrapper + `useRegionAppendix` + `parseAppendix` parser

**Files:**
- Modify: `observatory/web-src/src/api/rest.ts`
- Modify: `observatory/web-src/src/api/rest.test.ts`
- Create: `observatory/web-src/src/inspector/sections/parseAppendix.ts`
- Create: `observatory/web-src/src/inspector/sections/parseAppendix.test.ts`
- Create: `observatory/web-src/src/inspector/useRegionAppendix.ts`
- Create: `observatory/web-src/src/inspector/useRegionAppendix.test.ts`

### Context for implementer

Three independent pieces that together power the Appendix section in Task 8. All can be developed and tested without the section component existing yet.

**REST wrapper** mirrors `fetchPrompt`. The existing `_get` helper already raises `RestError` on non-2xx.

**Parser** is pure. Input: the raw `rolling.md` contents. Output: list of `AppendixEntry`. Format (from `region_template/appendix.py`): entries framed with `## <ISO-timestamp> — <trigger>` H2 headings. Tolerate external hand-edits.

**Hook** follows the v2 `useRegionFetch` pattern. The key difference: map `RestError(404)` to `data === ''` (empty), so the section renders an empty state instead of `Failed: 404`.

### Steps

- [ ] **Step 1 — Write failing parser tests.**

  Create `observatory/web-src/src/inspector/sections/parseAppendix.test.ts`:

  ```typescript
  import { describe, it, expect } from 'vitest';
  import { parseAppendix } from './parseAppendix';

  describe('parseAppendix', () => {
    it('returns [] for empty input', () => {
      expect(parseAppendix('')).toEqual([]);
    });

    it('parses a single entry', () => {
      const md = '## 2026-04-22T10:00:00Z — sleep\n\nbody line one\nbody line two\n';
      expect(parseAppendix(md)).toEqual([
        { ts: '2026-04-22T10:00:00Z', trigger: 'sleep', body: 'body line one\nbody line two' },
      ]);
    });

    it('parses multiple entries in file order', () => {
      const md = [
        '## 2026-04-22T10:00:00Z — sleep', '',
        'entry one', '',
        '## 2026-04-22T12:00:00Z — sleep', '',
        'entry two',
      ].join('\n');
      const entries = parseAppendix(md);
      expect(entries).toHaveLength(2);
      expect(entries[0].ts).toBe('2026-04-22T10:00:00Z');
      expect(entries[0].body).toBe('entry one');
      expect(entries[1].ts).toBe('2026-04-22T12:00:00Z');
      expect(entries[1].body).toBe('entry two');
    });

    it('tolerates missing trigger (no em-dash)', () => {
      const md = '## 2026-04-22T10:00:00Z\n\nbody';
      expect(parseAppendix(md)).toEqual([
        { ts: '2026-04-22T10:00:00Z', trigger: '', body: 'body' },
      ]);
    });

    it('tolerates trailing whitespace', () => {
      const md = '## 2026-04-22T10:00:00Z — sleep   \n\nbody\n\n';
      const [entry] = parseAppendix(md);
      expect(entry.ts).toBe('2026-04-22T10:00:00Z');
      expect(entry.trigger).toBe('sleep');
      expect(entry.body).toBe('body');
    });

    it('returns single implicit entry when file has no ## headings', () => {
      const md = 'hand-written preamble with no ## sections\nline two';
      expect(parseAppendix(md)).toEqual([
        { ts: '', trigger: '', body: 'hand-written preamble with no ## sections\nline two' },
      ]);
    });
  });
  ```

- [ ] **Step 2 — Run to verify failure.** Expected: FAILED (module missing).

- [ ] **Step 3 — Implement parser.**

  Create `observatory/web-src/src/inspector/sections/parseAppendix.ts`:

  ```typescript
  export type AppendixEntry = {
    ts: string;       // ISO timestamp from the "## <ts> — <trigger>" line (may be empty)
    trigger: string;  // word after "— " (may be empty)
    body: string;     // everything between this heading and the next (trimmed)
  };

  export function parseAppendix(md: string): AppendixEntry[] {
    if (md.trim() === '') return [];

    const lines = md.split('\n');
    const headings: Array<{ lineIdx: number; ts: string; trigger: string }> = [];
    for (let i = 0; i < lines.length; i++) {
      const m = lines[i].match(/^## (.+)$/);
      if (m) {
        const inner = m[1].trim();
        const split = inner.match(/^([^—]+?)\s*(?:—\s*(.*))?$/);
        const ts = (split?.[1] ?? inner).trim();
        const trigger = (split?.[2] ?? '').trim();
        headings.push({ lineIdx: i, ts, trigger });
      }
    }

    if (headings.length === 0) {
      return [{ ts: '', trigger: '', body: md.trim() }];
    }

    const entries: AppendixEntry[] = [];
    for (let i = 0; i < headings.length; i++) {
      const start = headings[i].lineIdx + 1;
      const end = i + 1 < headings.length ? headings[i + 1].lineIdx : lines.length;
      const body = lines.slice(start, end).join('\n').trim();
      entries.push({ ts: headings[i].ts, trigger: headings[i].trigger, body });
    }
    return entries;
  }
  ```

- [ ] **Step 4 — Run parser tests.** Expected: 6 PASS.

- [ ] **Step 5 — Write failing REST fetcher test.**

  Open `observatory/web-src/src/api/rest.test.ts`. Append:

  ```typescript
  describe('fetchAppendix', () => {
    it('returns text on 200', async () => {
      const body = '## 2026-04-22T10:00:00Z — sleep\n\nbody';
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(body, { status: 200, headers: { 'content-type': 'text/plain' } }),
      ) as typeof fetch;
      const text = await fetchAppendix('good_region');
      expect(text).toBe(body);
    });

    it('throws RestError with status 404 on missing appendix', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: 'not_found', message: 'no appendix' }), {
          status: 404,
          headers: { 'content-type': 'application/json' },
        }),
      ) as typeof fetch;
      await expect(fetchAppendix('good_region')).rejects.toMatchObject({
        name: 'RestError',
        status: 404,
      });
    });
  });
  ```

  Add `fetchAppendix` to the imports.

- [ ] **Step 6 — Implement `fetchAppendix`.**

  Open `observatory/web-src/src/api/rest.ts`. Append:

  ```typescript
  export async function fetchAppendix(name: string): Promise<string> {
    const r = await _get(`/api/regions/${encodeURIComponent(name)}/appendix`);
    return r.text();
  }
  ```

- [ ] **Step 7 — Run REST tests.** Expected: pass.

- [ ] **Step 8 — Write failing hook tests.**

  Create `observatory/web-src/src/inspector/useRegionAppendix.test.ts`:

  ```typescript
  import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
  import { renderHook, waitFor, cleanup } from '@testing-library/react';
  import { useRegionAppendix } from './useRegionAppendix';
  import * as rest from '../api/rest';

  describe('useRegionAppendix', () => {
    beforeEach(() => { vi.restoreAllMocks(); });
    afterEach(() => { cleanup(); });

    it('loads data on mount', async () => {
      vi.spyOn(rest, 'fetchAppendix').mockResolvedValue('## 2026-04-22T10:00:00Z — sleep\n\nhi');
      const { result } = renderHook(() => useRegionAppendix('r'));
      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(result.current.data).toContain('## 2026-04-22');
      expect(result.current.error).toBeNull();
    });

    it('maps 404 to empty data (not error)', async () => {
      const err = new rest.RestError(404, 'not found');
      vi.spyOn(rest, 'fetchAppendix').mockRejectedValue(err);
      const { result } = renderHook(() => useRegionAppendix('r'));
      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(result.current.data).toBe('');
      expect(result.current.error).toBeNull();
    });

    it('surfaces non-404 errors', async () => {
      const err = new rest.RestError(403, 'sandbox');
      vi.spyOn(rest, 'fetchAppendix').mockRejectedValue(err);
      const { result } = renderHook(() => useRegionAppendix('r'));
      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(result.current.data).toBeNull();
      expect(result.current.error?.message).toBe('sandbox');
    });

    it('reload refetches', async () => {
      const spy = vi.spyOn(rest, 'fetchAppendix').mockResolvedValue('first');
      const { result } = renderHook(() => useRegionAppendix('r'));
      await waitFor(() => expect(result.current.data).toBe('first'));
      spy.mockResolvedValue('second');
      result.current.reload();
      await waitFor(() => expect(result.current.data).toBe('second'));
    });
  });
  ```

- [ ] **Step 9 — Implement hook.**

  Create `observatory/web-src/src/inspector/useRegionAppendix.ts`:

  ```typescript
  import { useCallback, useEffect, useRef, useState } from 'react';
  import { fetchAppendix, RestError } from '../api/rest';

  type HookState = {
    loading: boolean;
    error: Error | null;
    data: string | null;   // '' = intentional empty (404); null = not loaded yet
    reload: () => void;
  };

  export function useRegionAppendix(name: string | null): HookState {
    const [loading, setLoading] = useState<boolean>(name != null);
    const [error, setError] = useState<Error | null>(null);
    const [data, setData] = useState<string | null>(null);
    const reqId = useRef(0);

    const load = useCallback(async () => {
      if (name == null) return;
      const id = ++reqId.current;
      setLoading(true);
      setError(null);
      try {
        const text = await fetchAppendix(name);
        if (id !== reqId.current) return;
        setData(text);
      } catch (e) {
        if (id !== reqId.current) return;
        if (e instanceof RestError && e.status === 404) {
          setData('');
        } else {
          setError(e instanceof Error ? e : new Error(String(e)));
          setData(null);
        }
      } finally {
        if (id === reqId.current) setLoading(false);
      }
    }, [name]);

    useEffect(() => { void load(); }, [load]);

    return { loading, error, data, reload: () => void load() };
  }
  ```

- [ ] **Step 10 — Run hook tests.** Expected: 4 PASS.

- [ ] **Step 11 — Full frontend suite + typecheck.**

  ```
  cd observatory/web-src && npx vitest run && npx tsc -b
  ```

- [ ] **Step 12 — Commit.**

  ```bash
  git add observatory/web-src/src/api/ observatory/web-src/src/inspector/
  git commit -m "$(cat <<'EOF'
  observatory: rest+hook+parser for rolling appendix (v3 task 3)

  fetchAppendix wraps GET /api/regions/{name}/appendix. useRegionAppendix
  maps RestError(404) to data:'' so fresh regions that have never slept
  render an empty state instead of a red 'Failed: 404'. parseAppendix is
  a pure markdown parser using String.prototype.match: splits on
  ^## <ts> [— <trigger>] headings, tolerates missing trigger, trailing
  whitespace, and files without any headings (collapse to a single
  implicit entry).

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 4 — Dock shell: frame + tab strip + persistence + keys + row-select helper

**Files:**
- Create: `observatory/web-src/src/dock/Dock.tsx`
- Create: `observatory/web-src/src/dock/DockTabStrip.tsx`
- Create: `observatory/web-src/src/dock/useDockPersistence.ts`
- Create: `observatory/web-src/src/dock/useDockKeys.ts`
- Create: `observatory/web-src/src/dock/selectRegionFromRow.ts`
- Create: `observatory/web-src/src/dock/Dock.test.tsx`
- Create: `observatory/web-src/src/dock/useDockPersistence.test.ts`
- Create: `observatory/web-src/src/dock/selectRegionFromRow.test.ts`
- Modify: `observatory/web-src/src/App.tsx`

### Context for implementer

Empty-shell task. The three tabs (Firehose / Topics / Metacog) are placeholders here — real content lands in Tasks 5-7.

**Keyboard contract:**
- `` ` `` (backtick) → toggles `dockCollapsed`.
- `Space` → only when focus is inside `#dock-root` → toggles `dockPaused`.
- Both keys: no-op if event target is an input / textarea / contenteditable.

**Resize contract:**
- Drag the top 4 px edge of the dock. `pointerdown` captures + starts tracking; `pointermove` sets `dockHeight = startH + (startY - clientY)`; `pointerup` releases.
- `useDockPersistence` subscribes to `dockHeight` / `dockCollapsed` changes and debounces to `localStorage` (200 ms). On mount, it rehydrates from localStorage (with clamping).

**`selectRegionFromRow`** is a pure helper — implements §8 of the spec. `(store, { regionName, envelopeKey })` → calls `select(regionName)` and `setPendingEnvelopeKey(envelopeKey)`.

### Steps

- [ ] **Step 1 — Write failing `useDockPersistence` tests.**

  Create `observatory/web-src/src/dock/useDockPersistence.test.ts`:

  ```typescript
  import { describe, it, expect, beforeEach, afterEach } from 'vitest';
  import { renderHook, act, cleanup } from '@testing-library/react';
  import { useDockPersistence } from './useDockPersistence';
  import { createStore } from '../store';

  describe('useDockPersistence', () => {
    beforeEach(() => { localStorage.clear(); });
    afterEach(() => { cleanup(); });

    it('hydrates from localStorage on mount', () => {
      localStorage.setItem('observatory.dock.height', '300');
      localStorage.setItem('observatory.dock.collapsed', 'true');
      const store = createStore();
      renderHook(() => useDockPersistence(store));
      expect(store.getState().dockHeight).toBe(300);
      expect(store.getState().dockCollapsed).toBe(true);
    });

    it('clamps out-of-range height on hydrate', () => {
      localStorage.setItem('observatory.dock.height', '60');
      const store = createStore();
      renderHook(() => useDockPersistence(store));
      expect(store.getState().dockHeight).toBe(120);
    });

    it('writes to localStorage on state change (debounced)', async () => {
      const store = createStore();
      renderHook(() => useDockPersistence(store));
      act(() => { store.getState().setDockHeight(350); });
      await new Promise((r) => setTimeout(r, 260));
      expect(localStorage.getItem('observatory.dock.height')).toBe('350');
    });

    it('ignores malformed stored values', () => {
      localStorage.setItem('observatory.dock.height', 'abc');
      const store = createStore();
      renderHook(() => useDockPersistence(store));
      expect(store.getState().dockHeight).toBe(220);
    });
  });
  ```

- [ ] **Step 2 — Run to verify failure.** Expected: FAILED.

- [ ] **Step 3 — Implement persistence hook.**

  Create `observatory/web-src/src/dock/useDockPersistence.ts`:

  ```typescript
  import { useEffect, useRef } from 'react';
  import type { StoreApi, UseBoundStore } from 'zustand';

  const KEY_HEIGHT = 'observatory.dock.height';
  const KEY_COLLAPSED = 'observatory.dock.collapsed';
  const DEBOUNCE_MS = 200;
  const MIN = 120;
  const MAX = 520;

  type AnyStore = UseBoundStore<StoreApi<{
    dockHeight: number;
    dockCollapsed: boolean;
    setDockHeight: (n: number) => void;
    setDockCollapsed: (b: boolean) => void;
  }>>;

  export function useDockPersistence(store: AnyStore): void {
    const hydrated = useRef(false);

    useEffect(() => {
      if (hydrated.current) return;
      hydrated.current = true;
      const h = Number(localStorage.getItem(KEY_HEIGHT));
      if (Number.isFinite(h) && h > 0) {
        store.getState().setDockHeight(Math.max(MIN, Math.min(MAX, h)));
      }
      const c = localStorage.getItem(KEY_COLLAPSED);
      if (c === 'true' || c === 'false') {
        store.getState().setDockCollapsed(c === 'true');
      }
    }, [store]);

    useEffect(() => {
      let timer: ReturnType<typeof setTimeout> | null = null;
      const schedule = (fn: () => void) => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(fn, DEBOUNCE_MS);
      };
      const unsub = store.subscribe((s, prev) => {
        if (s.dockHeight !== prev.dockHeight) {
          schedule(() => localStorage.setItem(KEY_HEIGHT, String(s.dockHeight)));
        }
        if (s.dockCollapsed !== prev.dockCollapsed) {
          schedule(() => localStorage.setItem(KEY_COLLAPSED, String(s.dockCollapsed)));
        }
      });
      return () => { unsub(); if (timer) clearTimeout(timer); };
    }, [store]);
  }
  ```

- [ ] **Step 4 — Run persistence tests.** Expected: 4 PASS.

- [ ] **Step 5 — Write failing `selectRegionFromRow` test.**

  Create `observatory/web-src/src/dock/selectRegionFromRow.test.ts`:

  ```typescript
  import { describe, it, expect } from 'vitest';
  import { createStore } from '../store';
  import { selectRegionFromRow } from './selectRegionFromRow';

  describe('selectRegionFromRow', () => {
    it('sets selectedRegion and pendingEnvelopeKey', () => {
      const store = createStore();
      selectRegionFromRow(store, { regionName: 'pfc', envelopeKey: '123|hive/cog' });
      expect(store.getState().selectedRegion).toBe('pfc');
      expect(store.getState().pendingEnvelopeKey).toBe('123|hive/cog');
    });

    it('accepts null envelopeKey', () => {
      const store = createStore();
      selectRegionFromRow(store, { regionName: 'pfc', envelopeKey: null });
      expect(store.getState().selectedRegion).toBe('pfc');
      expect(store.getState().pendingEnvelopeKey).toBeNull();
    });

    it('no-op when regionName is null', () => {
      const store = createStore();
      store.getState().select('existing');
      selectRegionFromRow(store, { regionName: null, envelopeKey: null });
      expect(store.getState().selectedRegion).toBe('existing');
    });
  });
  ```

- [ ] **Step 6 — Implement helper.**

  Create `observatory/web-src/src/dock/selectRegionFromRow.ts`:

  ```typescript
  import type { StoreApi, UseBoundStore } from 'zustand';

  type MinStore = UseBoundStore<StoreApi<{
    select: (name: string | null) => void;
    setPendingEnvelopeKey: (key: string | null) => void;
    selectedRegion: string | null;
  }>>;

  export function selectRegionFromRow(
    store: MinStore,
    { regionName, envelopeKey }: { regionName: string | null; envelopeKey: string | null },
  ): void {
    if (regionName == null) return;
    store.getState().select(regionName);
    store.getState().setPendingEnvelopeKey(envelopeKey);
  }
  ```

- [ ] **Step 7 — Run helper tests.** Expected: 3 PASS.

- [ ] **Step 8 — Implement `useDockKeys`.**

  Create `observatory/web-src/src/dock/useDockKeys.ts`:

  ```typescript
  import { useEffect } from 'react';
  import { useStore } from '../store';

  function isEditableTarget(t: EventTarget | null): boolean {
    if (!(t instanceof HTMLElement)) return false;
    if (t instanceof HTMLInputElement) return true;
    if (t instanceof HTMLTextAreaElement) return true;
    return t.isContentEditable;
  }

  function inDock(t: EventTarget | null): boolean {
    if (!(t instanceof HTMLElement)) return false;
    return t.closest('#dock-root') != null;
  }

  export function useDockKeys(): void {
    useEffect(() => {
      const handler = (e: KeyboardEvent) => {
        if (isEditableTarget(e.target)) return;
        if (e.key === '`' && !e.metaKey && !e.ctrlKey) {
          e.preventDefault();
          const { dockCollapsed, setDockCollapsed } = useStore.getState();
          setDockCollapsed(!dockCollapsed);
          return;
        }
        if (e.key === ' ' && inDock(e.target)) {
          e.preventDefault();
          const { dockPaused, setDockPaused } = useStore.getState();
          setDockPaused(!dockPaused);
        }
      };
      window.addEventListener('keydown', handler);
      return () => window.removeEventListener('keydown', handler);
    }, []);
  }
  ```

- [ ] **Step 9 — Implement `DockTabStrip`.**

  Create `observatory/web-src/src/dock/DockTabStrip.tsx`:

  ```tsx
  import { useStore } from '../store';

  const TABS: Array<{ id: 'firehose' | 'topics' | 'metacog'; label: string }> = [
    { id: 'firehose', label: 'Firehose' },
    { id: 'topics', label: 'Topics' },
    { id: 'metacog', label: 'Metacog' },
  ];

  export function DockTabStrip({ firehoseRate, topicCount, metacogBadge }: {
    firehoseRate: number;
    topicCount: number;
    metacogBadge: { count: number; severity: 'error' | 'conflict' | 'quiet' };
  }) {
    const dockTab = useStore((s) => s.dockTab);
    const setDockTab = useStore((s) => s.setDockTab);
    const dockCollapsed = useStore((s) => s.dockCollapsed);
    const setDockCollapsed = useStore((s) => s.setDockCollapsed);
    const dockPaused = useStore((s) => s.dockPaused);
    const setDockPaused = useStore((s) => s.setDockPaused);

    const badgeColor =
      metacogBadge.severity === 'error' ? 'text-[#ff8a88]' :
      metacogBadge.severity === 'conflict' ? 'text-[#ffc07a]' : 'text-[rgba(230,232,238,.45)]';

    return (
      <div className="flex items-center h-7 px-2 border-b border-[rgba(80,84,96,.55)] select-none" style={{ fontSize: 11 }}>
        {TABS.map((t) => {
          const active = dockTab === t.id;
          const count =
            t.id === 'firehose' ? `${firehoseRate.toFixed(0)}/s` :
            t.id === 'topics' ? `${topicCount}` :
            `·${metacogBadge.count}`;
          const countClass = t.id === 'metacog' ? badgeColor : 'text-[rgba(230,232,238,.55)]';
          return (
            <button
              key={t.id}
              onClick={() => setDockTab(t.id)}
              className={[
                'px-3 h-7 mr-1',
                active ? 'text-[rgba(230,232,238,.95)] border-t border-[rgba(230,232,238,.9)]' : 'text-[rgba(230,232,238,.45)]',
              ].join(' ')}
            >
              {t.label}
              {' '}
              <span className={['font-mono ml-1', countClass].join(' ')} style={{ fontSize: 10 }}>
                {count}
              </span>
            </button>
          );
        })}
        <div className="flex-1" />
        <button
          className="w-6 h-6 text-[rgba(230,232,238,.55)] hover:text-[rgba(230,232,238,.95)]"
          onClick={() => setDockPaused(!dockPaused)}
          title={dockPaused ? 'Resume (Space)' : 'Pause (Space)'}
        >
          {dockPaused ? '▶' : '⏸'}
        </button>
        <button
          className="w-6 h-6 text-[rgba(230,232,238,.55)] hover:text-[rgba(230,232,238,.95)]"
          onClick={() => setDockCollapsed(!dockCollapsed)}
          title={dockCollapsed ? 'Expand (`)' : 'Collapse (`)'}
        >
          {dockCollapsed ? '˄' : '˅'}
        </button>
      </div>
    );
  }
  ```

- [ ] **Step 10 — Implement `Dock` frame.**

  Create `observatory/web-src/src/dock/Dock.tsx`:

  ```tsx
  import { useEffect, useRef, useState } from 'react';
  import { useStore } from '../store';
  import { DockTabStrip } from './DockTabStrip';
  import { useDockPersistence } from './useDockPersistence';

  function FirehosePlaceholder() {
    return <div className="p-3 text-xs opacity-60">Firehose — implemented in v3 Task 5</div>;
  }
  function TopicsPlaceholder() {
    return <div className="p-3 text-xs opacity-60">Topics — implemented in v3 Task 6</div>;
  }
  function MetacogPlaceholder() {
    return <div className="p-3 text-xs opacity-60">Metacog — implemented in v3 Task 7</div>;
  }

  export function Dock() {
    useDockPersistence(useStore);
    const tab = useStore((s) => s.dockTab);
    const collapsed = useStore((s) => s.dockCollapsed);
    const height = useStore((s) => s.dockHeight);
    const setDockHeight = useStore((s) => s.setDockHeight);

    const [dragging, setDragging] = useState(false);
    const startY = useRef(0);
    const startH = useRef(220);

    useEffect(() => {
      if (!dragging) return;
      const onMove = (e: PointerEvent) => {
        const delta = startY.current - e.clientY;
        setDockHeight(startH.current + delta);
      };
      const onUp = () => setDragging(false);
      window.addEventListener('pointermove', onMove);
      window.addEventListener('pointerup', onUp);
      return () => {
        window.removeEventListener('pointermove', onMove);
        window.removeEventListener('pointerup', onUp);
      };
    }, [dragging, setDockHeight]);

    const activeHeight = collapsed ? 28 : height;

    return (
      <div
        id="dock-root"
        tabIndex={0}
        className="fixed bottom-0 left-0 right-0 bg-[rgba(14,15,19,.86)] border-t border-[rgba(80,84,96,.55)] text-[rgba(230,232,238,.85)] z-30 flex flex-col"
        style={{ height: activeHeight }}
      >
        <div
          className="absolute -top-1 left-0 right-0 h-1 cursor-ns-resize"
          onPointerDown={(e) => {
            startY.current = e.clientY;
            startH.current = height;
            setDragging(true);
          }}
        />
        <DockTabStrip
          firehoseRate={0}
          topicCount={0}
          metacogBadge={{ count: 0, severity: 'quiet' }}
        />
        {!collapsed && (
          <div className="flex-1 overflow-hidden">
            {tab === 'firehose' && <FirehosePlaceholder />}
            {tab === 'topics' && <TopicsPlaceholder />}
            {tab === 'metacog' && <MetacogPlaceholder />}
          </div>
        )}
      </div>
    );
  }
  ```

- [ ] **Step 11 — Mount `<Dock />` + `useDockKeys` in `App.tsx`.**

  Read `observatory/web-src/src/App.tsx`; in the JSX tree add `<Dock />` as a sibling to the existing Canvas/Hud/Inspector mounts, and call `useDockKeys()` at the top of the component body.

  ```tsx
  import { Dock } from './dock/Dock';
  import { useDockKeys } from './dock/useDockKeys';

  export default function App() {
    useDockKeys();
    return (
      <div className="w-screen h-screen overflow-hidden bg-hive-bg text-hive-fg">
        {/* existing Canvas + Hud + Inspector */}
        <Dock />
      </div>
    );
  }
  ```

- [ ] **Step 12 — Write failing Dock component test.**

  Create `observatory/web-src/src/dock/Dock.test.tsx`:

  ```tsx
  import { describe, it, expect, afterEach } from 'vitest';
  import { render, cleanup } from '@testing-library/react';
  import { Dock } from './Dock';
  import { useStore } from '../store';

  afterEach(() => { cleanup(); localStorage.clear(); useStore.setState({ dockCollapsed: false, dockTab: 'firehose', dockHeight: 220 }); });

  describe('Dock frame', () => {
    it('renders at default height 220px', () => {
      const { container } = render(<Dock />);
      const root = container.querySelector('#dock-root') as HTMLElement;
      expect(root.style.height).toBe('220px');
    });

    it('collapses to 28px when dockCollapsed is true', () => {
      const { container, rerender } = render(<Dock />);
      useStore.setState({ dockCollapsed: true });
      rerender(<Dock />);
      const root = container.querySelector('#dock-root') as HTMLElement;
      expect(root.style.height).toBe('28px');
    });

    it('mounts the placeholder for the active tab', () => {
      const { queryByText, rerender } = render(<Dock />);
      expect(queryByText(/Firehose — implemented/)).toBeTruthy();
      useStore.setState({ dockTab: 'topics' });
      rerender(<Dock />);
      expect(queryByText(/Topics — implemented/)).toBeTruthy();
    });
  });
  ```

- [ ] **Step 13 — Run tests + typecheck.**

  ```
  cd observatory/web-src && npx vitest run dock/ && npx tsc -b
  ```
  Expected: pass.

- [ ] **Step 14 — Commit.**

  ```bash
  git add observatory/web-src/src/dock/ observatory/web-src/src/App.tsx
  git commit -m "$(cat <<'EOF'
  observatory: dock shell — frame + tab strip + persistence + keys (v3 task 4)

  Bottom dock with three tab-strip buttons (Firehose / Topics / Metacog),
  collapsible + resizable (drag 4 px top edge), persisted to localStorage
  (200 ms debounced, clamped [120, 520]). Keyboard: backtick toggles
  collapse, Space toggles pause when focus is in #dock-root. Input-focus
  guard matches useInspectorKeys. Tabs are placeholders - real content
  lands in Tasks 5-7.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 5 — Firehose tab + topicColors extension

**Files:**
- Create: `observatory/web-src/src/dock/Firehose.tsx`
- Create: `observatory/web-src/src/dock/FirehoseRow.tsx`
- Create: `observatory/web-src/src/dock/Firehose.test.tsx`
- Modify: `observatory/web-src/src/scene/topicColors.ts`
- Modify: `observatory/web-src/src/scene/topicColors.test.ts`
- Modify: `observatory/web-src/src/dock/Dock.tsx` (wire real Firehose + live rate count)

### Context for implementer

Spec §5 locks row schema, filter behavior, kind-tag table, pause/resume, and click-through. Rows use `selectRegionFromRow` from Task 4.

**Preview rules (§5.1):**
- `application/json` → `JSON.stringify(payload.data).slice(0, 120)`. Replace `\n` with `↵`. Trailing ellipsis when truncated.
- Other → `String(payload.data).slice(0, 120)` same rules.

**Filter rules (§5.2):**
- Empty → match all.
- Substring (default) → case-insensitive substring match against `${source_region} ${topic} ${JSON.stringify(envelope)}`.
- Regex mode → input is `/pattern/` or `/pattern/i`; compile with `new RegExp`. Invalid regex → red border, no filtering.
- 150 ms debounce.

**Pause:** snapshot the envelope ring at pause time; while paused, don't re-read. On unpause, snap back to live.

**Max rendered rows:** 1000.

**`kindTag(topic)`:** export from `topicColors.ts` with the mapping table from spec §5.3 using `String.prototype.startsWith`.

### Steps

- [ ] **Step 1 — Extend `topicColors.ts`.**

  Read `observatory/web-src/src/scene/topicColors.ts`. Extend any existing `startsWith` branches to cover every prefix in spec §5.3. Add:

  ```typescript
  export function kindTag(topic: string): string {
    if (topic.startsWith('hive/cognitive/')) return 'cog';
    if (topic.startsWith('hive/sensory/')) return 'sns';
    if (topic.startsWith('hive/motor/')) return 'mot';
    if (topic.startsWith('hive/metacognition/')) return 'meta';
    if (topic.startsWith('hive/self/')) return 'self';
    if (topic.startsWith('hive/modulator/')) return 'mod';
    if (topic.startsWith('hive/attention/')) return 'att';
    if (topic.startsWith('hive/interoception/')) return 'intr';
    if (topic.startsWith('hive/habit/')) return 'hab';
    if (topic.startsWith('hive/rhythm/')) return 'rhy';
    if (topic.startsWith('hive/system/heartbeat/')) return 'hb';
    if (topic.startsWith('hive/system/region_stats/')) return 'rst';
    if (topic.startsWith('hive/system/metrics/')) return 'mtr';
    if (topic.startsWith('hive/system/sleep/')) return 'slp';
    if (topic.startsWith('hive/system/spawn/')) return 'spn';
    if (topic.startsWith('hive/system/codechange/')) return 'cc';
    if (topic.startsWith('hive/broadcast/')) return 'bcst';
    return '?';
  }
  ```

  Extend the color map + `COLOR_CACHE` with any missing prefixes per spec §5.3.

- [ ] **Step 2 — `kindTag` tests.**

  Append to `observatory/web-src/src/scene/topicColors.test.ts`:

  ```typescript
  import { kindTag } from './topicColors';
  describe('kindTag', () => {
    const cases: Array<[string, string]> = [
      ['hive/cognitive/pfc/plan', 'cog'],
      ['hive/sensory/visual/features', 'sns'],
      ['hive/motor/intent', 'mot'],
      ['hive/metacognition/error/detected', 'meta'],
      ['hive/self/identity', 'self'],
      ['hive/modulator/dopamine', 'mod'],
      ['hive/attention/focus', 'att'],
      ['hive/interoception/felt_state', 'intr'],
      ['hive/habit/suggestion', 'hab'],
      ['hive/rhythm/gamma', 'rhy'],
      ['hive/system/heartbeat/pfc', 'hb'],
      ['hive/system/region_stats/pfc', 'rst'],
      ['hive/system/metrics/compute', 'mtr'],
      ['hive/system/sleep/granted', 'slp'],
      ['hive/system/spawn/complete', 'spn'],
      ['hive/system/codechange/approved', 'cc'],
      ['hive/broadcast/shutdown', 'bcst'],
      ['unknown/topic', '?'],
    ];
    it.each(cases)('%s → %s', (topic, tag) => expect(kindTag(topic)).toBe(tag));
  });
  ```

- [ ] **Step 3 — Write Firehose component tests.**

  Create `observatory/web-src/src/dock/Firehose.test.tsx`:

  ```tsx
  import { describe, it, expect, afterEach } from 'vitest';
  import { render, fireEvent, cleanup } from '@testing-library/react';
  import { Firehose } from './Firehose';
  import { useStore } from '../store';

  function push(topic: string, source: string, data: unknown = {}) {
    useStore.getState().pushEnvelope({
      observed_at: Date.now() + Math.random(),
      topic,
      envelope: { payload: { content_type: 'application/json', data } } as unknown as Record<string, unknown>,
      source_region: source,
      destinations: [],
    });
  }

  afterEach(() => {
    cleanup();
    useStore.setState({ envelopes: [], firehoseFilter: '', dockPaused: false, expandedRowIds: new Set() });
  });

  describe('Firehose', () => {
    it('renders rows from envelope ring', () => {
      push('hive/cognitive/pfc/plan', 'pfc');
      push('hive/cognitive/pfc/plan', 'pfc');
      const { container } = render(<Firehose />);
      expect(container.querySelectorAll('[data-testid="firehose-row"]').length).toBe(2);
    });

    it('substring filter is case-insensitive', async () => {
      push('hive/cognitive/pfc/plan', 'prefrontal_cortex');
      push('hive/modulator/dopamine', 'glia');
      const { container, getByPlaceholderText } = render(<Firehose />);
      const input = getByPlaceholderText(/filter source · topic · payload/i) as HTMLInputElement;
      fireEvent.change(input, { target: { value: 'DOPAMINE' } });
      await new Promise((r) => setTimeout(r, 200));
      const rows = container.querySelectorAll('[data-testid="firehose-row"]');
      rows.forEach((r) => expect(r.textContent).toMatch(/dopamine/i));
    });

    it('regex filter honours /pattern/i', async () => {
      push('hive/cognitive/pfc/plan', 'pfc');
      push('hive/modulator/dopamine', 'glia');
      const { container, getByPlaceholderText } = render(<Firehose />);
      const input = getByPlaceholderText(/filter source · topic · payload/i) as HTMLInputElement;
      fireEvent.change(input, { target: { value: '/modulator/i' } });
      await new Promise((r) => setTimeout(r, 200));
      expect(container.querySelectorAll('[data-testid="firehose-row"]').length).toBe(1);
    });

    it('pause snapshots the ring', () => {
      push('hive/a', 'r');
      push('hive/b', 'r');
      const { container, rerender } = render(<Firehose />);
      expect(container.querySelectorAll('[data-testid="firehose-row"]').length).toBe(2);
      useStore.setState({ dockPaused: true });
      rerender(<Firehose />);
      push('hive/c', 'r');
      rerender(<Firehose />);
      expect(container.querySelectorAll('[data-testid="firehose-row"]').length).toBe(2);
    });
  });
  ```

- [ ] **Step 4 — Run to verify failure.** Expected: FAILED.

- [ ] **Step 5 — Implement `FirehoseRow`.**

  Create `observatory/web-src/src/dock/FirehoseRow.tsx`:

  ```tsx
  import { useStore } from '../store';
  import { kindTag } from '../scene/topicColors';
  import { JsonTree } from '../inspector/sections/JsonTree';
  import { selectRegionFromRow } from './selectRegionFromRow';
  import type { Envelope } from '../store';

  function previewOf(env: Record<string, unknown>): string {
    const payload = (env as { payload?: { content_type?: string; data?: unknown } }).payload;
    if (!payload) return '';
    let raw = '';
    if (payload.content_type === 'application/json') {
      try { raw = JSON.stringify(payload.data); } catch { raw = String(payload.data); }
    } else {
      raw = String(payload.data ?? '');
    }
    raw = raw.replace(/\n/g, '↵');
    return raw.length > 120 ? raw.slice(0, 120) + '…' : raw;
  }

  function ts(ms: number): string {
    return new Date(ms).toISOString().slice(11, 23);  // HH:MM:SS.mmm
  }

  export function FirehoseRow({ env, rowKey }: { env: Envelope; rowKey: string }) {
    const expanded = useStore((s) => s.expandedRowIds.has(rowKey));
    const toggleRowExpand = useStore((s) => s.toggleRowExpand);
    const selected = useStore((s) => s.selectedRegion === env.source_region);
    const preview = previewOf(env.envelope);
    const tag = kindTag(env.topic);

    return (
      <div
        data-testid="firehose-row"
        className={[
          'grid grid-cols-[auto_auto_1fr_auto_auto] items-center gap-2 px-2 py-1 cursor-pointer',
          'hover:bg-[rgba(230,232,238,.05)]',
          selected ? 'border-l-2 border-[rgba(230,232,238,.9)]' : 'border-l-2 border-transparent',
        ].join(' ')}
        onClick={() => selectRegionFromRow(useStore, {
          regionName: env.source_region,
          envelopeKey: `${env.observed_at}|${env.topic}`,
        })}
      >
        <span className="font-mono text-[10px] text-[rgba(136,140,152,.70)]">{ts(env.observed_at)}</span>
        <span className="text-[11px] truncate max-w-[14ch]">{env.source_region ?? '—'}</span>
        <span className="font-mono text-[10px] truncate opacity-80">→ {env.topic}</span>
        <span className="font-mono text-[10px] px-1 rounded bg-[rgba(255,255,255,.05)]">{tag}</span>
        <button
          className="text-[10px] opacity-70 px-1"
          onClick={(e) => { e.stopPropagation(); toggleRowExpand(rowKey); }}
        >
          {expanded ? '▾' : '▸'}
        </button>
        {!expanded && <div className="col-span-5 font-mono text-[10px] opacity-70 truncate pl-4">{preview}</div>}
        {expanded && (
          <div className="col-span-5 pl-6 py-1 text-[10px]">
            <JsonTree value={env.envelope} />
          </div>
        )}
      </div>
    );
  }
  ```

- [ ] **Step 6 — Implement `Firehose`.**

  Create `observatory/web-src/src/dock/Firehose.tsx`:

  ```tsx
  import { useEffect, useMemo, useRef, useState } from 'react';
  import { useStore } from '../store';
  import { FirehoseRow } from './FirehoseRow';

  const MAX_ROWS = 1000;

  function matcher(filter: string): { fn: (s: string) => boolean; valid: boolean } {
    const empty = filter.trim() === '';
    if (empty) return { fn: () => true, valid: true };
    const m = filter.match(/^\/(.+)\/(i)?$/);
    if (m) {
      try {
        const rx = new RegExp(m[1], m[2] ?? '');
        return { fn: (s) => rx.test(s), valid: true };
      } catch {
        return { fn: () => true, valid: false };
      }
    }
    const lc = filter.toLowerCase();
    return { fn: (s) => s.toLowerCase().includes(lc), valid: true };
  }

  export function Firehose() {
    const filter = useStore((s) => s.firehoseFilter);
    const setFilter = useStore((s) => s.setFirehoseFilter);
    const paused = useStore((s) => s.dockPaused);

    const [input, setInput] = useState(filter);
    useEffect(() => {
      const t = setTimeout(() => setFilter(input), 150);
      return () => clearTimeout(t);
    }, [input, setFilter]);

    const match = useMemo(() => matcher(filter), [filter]);

    const liveEnvs = useStore((s) => s.envelopes);
    const snapshotRef = useRef<typeof liveEnvs | null>(null);
    useEffect(() => {
      if (paused && snapshotRef.current == null) snapshotRef.current = liveEnvs;
      if (!paused) snapshotRef.current = null;
    }, [paused, liveEnvs]);
    const envs = paused && snapshotRef.current ? snapshotRef.current : liveEnvs;

    const rows = useMemo(() => {
      const sliced = envs.slice(-MAX_ROWS);
      return sliced.filter((e) => {
        const src = e.source_region ?? '';
        const haystack = `${src} ${e.topic} ${JSON.stringify(e.envelope)}`;
        return match.fn(haystack);
      });
    }, [envs, match]);

    const scrollRef = useRef<HTMLDivElement | null>(null);
    useEffect(() => {
      const el = scrollRef.current;
      if (!el) return;
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      if (nearBottom) el.scrollTop = el.scrollHeight;
    }, [rows]);

    return (
      <div className="flex flex-col h-full">
        <div className="px-2 py-1 border-b border-[rgba(80,84,96,.35)]">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="filter source · topic · payload  (regex /.../)"
            className={[
              'w-full bg-transparent text-[11px] font-mono outline-none px-1 py-0.5',
              match.valid ? 'text-[rgba(230,232,238,.9)]' : 'text-[#ff8a88] border border-[#ff8a88]',
            ].join(' ')}
          />
        </div>
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          {rows.map((e) => (
            <FirehoseRow
              key={`${e.observed_at}|${e.topic}|${e.source_region ?? ''}`}
              rowKey={`${e.observed_at}|${e.topic}|${e.source_region ?? ''}`}
              env={e}
            />
          ))}
        </div>
      </div>
    );
  }
  ```

- [ ] **Step 7 — Wire into `Dock.tsx`.**

  Replace `FirehosePlaceholder` with the real `Firehose`. Wire the live `firehoseRate`:

  ```tsx
  import { Firehose } from './Firehose';

  function useFirehoseRate(): number {
    const [rate, setRate] = useState(0);
    const lastTotal = useRef(0);
    useEffect(() => {
      const id = setInterval(() => {
        const cur = useStore.getState().envelopesReceivedTotal;
        setRate(cur - lastTotal.current);
        lastTotal.current = cur;
      }, 1000);
      return () => clearInterval(id);
    }, []);
    return rate;
  }

  // In Dock:
  const firehoseRate = useFirehoseRate();
  // pass firehoseRate={firehoseRate} to DockTabStrip
  // render {tab === 'firehose' && <Firehose />}
  ```

- [ ] **Step 8 — Run tests + typecheck.**

  ```
  cd observatory/web-src && npx vitest run dock/ scene/topicColors.test.ts && npx tsc -b
  ```

- [ ] **Step 9 — Commit.**

  ```bash
  git add observatory/web-src/src/dock/ observatory/web-src/src/scene/topicColors.ts observatory/web-src/src/scene/topicColors.test.ts
  git commit -m "$(cat <<'EOF'
  observatory: firehose tab + topicColors kindTag (v3 task 5)

  Firehose renders the envelope ring with timestamp, source, topic, kind
  badge, preview; substring + /regex/i filter with 150 ms debounce; pause
  snapshots the ring at pause time and re-syncs on resume. Rows use the
  shared selectRegionFromRow helper for click-through. Auto-scroll to
  newest when user is within 40 px of bottom. Max rendered rows capped
  at 1000. kindTag extends topicColors with all v3 prefixes.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 6 — Topics tab + `useTopicStats` selector

**Files:**
- Create: `observatory/web-src/src/dock/useTopicStats.ts`
- Create: `observatory/web-src/src/dock/useTopicStats.test.ts`
- Create: `observatory/web-src/src/dock/Topics.tsx`
- Create: `observatory/web-src/src/dock/Topics.test.tsx`
- Modify: `observatory/web-src/src/dock/Dock.tsx` (wire live topic count + mount Topics)

### Context for implementer

Per spec §6.2, the selector runs at 1 Hz (not per envelope) and builds `Map<string, TopicStat>` where `TopicStat` has:

```ts
type TopicStat = {
  topic: string;
  ewmaRate: number;        // per-second, α = 0.1
  sparkBuckets: number[];  // length 6, each = count in 10 s bucket
  publishers: Set<string>; // source_region seen last 60 s
  publisherLastSeen: Map<string, number>;
  lastSeenMs: number;      // wallclock Date.now()
};
```

**Hot-path:** reads `useStore.getState().envelopes` once per 1 s tick; does NOT use reactive subscription.

### Steps

- [ ] **Step 1 — Write failing selector tests.**

  Create `observatory/web-src/src/dock/useTopicStats.test.ts`:

  ```typescript
  import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
  import { renderHook, act, cleanup } from '@testing-library/react';
  import { useTopicStats } from './useTopicStats';
  import { useStore } from '../store';

  describe('useTopicStats', () => {
    beforeEach(() => { vi.useFakeTimers(); useStore.setState({ envelopes: [], envelopesReceivedTotal: 0 }); });
    afterEach(() => { vi.useRealTimers(); cleanup(); });

    it('returns empty map initially', () => {
      const { result } = renderHook(() => useTopicStats());
      expect(result.current.size).toBe(0);
    });

    it('accumulates after first tick', () => {
      const { result } = renderHook(() => useTopicStats());
      for (let i = 0; i < 5; i++) {
        useStore.getState().pushEnvelope({
          observed_at: Date.now(), topic: 'hive/a', envelope: {}, source_region: 'r', destinations: [],
        });
      }
      act(() => { vi.advanceTimersByTime(1100); });
      const s = result.current.get('hive/a');
      expect(s).toBeDefined();
      expect(s!.publishers.has('r')).toBe(true);
      expect(s!.ewmaRate).toBeGreaterThan(0);
      expect(s!.sparkBuckets.at(-1)).toBe(5);
    });

    it('publishers decay after 60 s of no envelopes', () => {
      const { result } = renderHook(() => useTopicStats());
      useStore.getState().pushEnvelope({
        observed_at: Date.now(), topic: 'hive/a', envelope: {}, source_region: 'r', destinations: [],
      });
      act(() => { vi.advanceTimersByTime(1100); });
      expect(result.current.get('hive/a')!.publishers.has('r')).toBe(true);
      act(() => { vi.advanceTimersByTime(60_000); });
      expect(result.current.get('hive/a')!.publishers.has('r')).toBe(false);
    });
  });
  ```

- [ ] **Step 2 — Run to verify failure.** Expected: FAILED.

- [ ] **Step 3 — Implement hook.**

  Create `observatory/web-src/src/dock/useTopicStats.ts`:

  ```typescript
  import { useEffect, useRef, useState } from 'react';
  import { useStore } from '../store';

  export type TopicStat = {
    topic: string;
    ewmaRate: number;
    sparkBuckets: number[];
    publishers: Set<string>;
    publisherLastSeen: Map<string, number>;
    lastSeenMs: number;
  };

  const ALPHA = 0.1;
  const BUCKETS = 6;
  const PUBLISHER_DECAY_MS = 60_000;

  export function useTopicStats(): Map<string, TopicStat> {
    const [snapshot, setSnapshot] = useState<Map<string, TopicStat>>(new Map());
    const stateRef = useRef<Map<string, TopicStat>>(new Map());
    const lastIndexRef = useRef<number>(0);

    useEffect(() => {
      const tick = () => {
        const now = Date.now();
        const envs = useStore.getState().envelopes;
        const total = useStore.getState().envelopesReceivedTotal;

        const delta = Math.max(0, total - lastIndexRef.current);
        const take = Math.min(delta, envs.length);
        const fresh = envs.slice(envs.length - take);
        lastIndexRef.current = total;

        // Roll bucket window forward + decay old publishers
        for (const stat of stateRef.current.values()) {
          stat.sparkBuckets.shift();
          stat.sparkBuckets.push(0);
          for (const [pub, last] of stat.publisherLastSeen) {
            if (now - last > PUBLISHER_DECAY_MS) {
              stat.publisherLastSeen.delete(pub);
              stat.publishers.delete(pub);
            }
          }
        }

        // Absorb new envelopes
        for (const e of fresh) {
          let s = stateRef.current.get(e.topic);
          if (!s) {
            s = {
              topic: e.topic,
              ewmaRate: 0,
              sparkBuckets: new Array(BUCKETS).fill(0),
              publishers: new Set<string>(),
              publisherLastSeen: new Map<string, number>(),
              lastSeenMs: now,
            };
            stateRef.current.set(e.topic, s);
          }
          s.sparkBuckets[BUCKETS - 1] += 1;
          s.lastSeenMs = now;
          if (e.source_region) {
            s.publishers.add(e.source_region);
            s.publisherLastSeen.set(e.source_region, now);
          }
        }

        // EWMA on per-tick count
        const perTopicCount = new Map<string, number>();
        for (const e of fresh) perTopicCount.set(e.topic, (perTopicCount.get(e.topic) ?? 0) + 1);
        for (const stat of stateRef.current.values()) {
          const n = perTopicCount.get(stat.topic) ?? 0;
          stat.ewmaRate = ALPHA * n + (1 - ALPHA) * stat.ewmaRate;
        }

        setSnapshot(new Map(stateRef.current));
      };
      const id = setInterval(tick, 1000);
      return () => clearInterval(id);
    }, []);

    return snapshot;
  }
  ```

- [ ] **Step 4 — Run selector tests.** Expected: 3 PASS.

- [ ] **Step 5 — Write Topics component tests.**

  Create `observatory/web-src/src/dock/Topics.test.tsx`:

  ```tsx
  import { describe, it, expect, afterEach } from 'vitest';
  import { render, cleanup } from '@testing-library/react';
  import { Topics } from './Topics';
  import { useStore } from '../store';

  afterEach(() => { cleanup(); useStore.setState({ envelopes: [], envelopesReceivedTotal: 0 }); });

  describe('Topics', () => {
    it('shows empty state when no topics', () => {
      const { getByText } = render(<Topics />);
      expect(getByText(/No topics yet/i)).toBeTruthy();
    });

    it('renders without crashing when envelopes exist', () => {
      useStore.getState().pushEnvelope({
        observed_at: Date.now(), topic: 'hive/a', envelope: {}, source_region: 'r', destinations: [],
      });
      const { container } = render(<Topics />);
      expect(container).toBeTruthy();
    });
  });
  ```

- [ ] **Step 6 — Implement Topics component.**

  Create `observatory/web-src/src/dock/Topics.tsx`:

  ```tsx
  import { useState } from 'react';
  import { useStore } from '../store';
  import { useTopicStats, TopicStat } from './useTopicStats';
  import { selectRegionFromRow } from './selectRegionFromRow';
  import { kindTag } from '../scene/topicColors';

  function relativeTime(lastSeenMs: number): string {
    const s = (Date.now() - lastSeenMs) / 1000;
    if (s < 1) return '<1 s ago';
    if (s < 60) return `${s.toFixed(1)} s ago`;
    return `${(s / 60).toFixed(1)} min ago`;
  }

  function Sparkline({ buckets }: { buckets: number[] }) {
    const max = Math.max(1, ...buckets);
    return (
      <svg viewBox="0 0 48 8" width="48" height="8" preserveAspectRatio="none">
        {buckets.map((n, i) => {
          const h = (n / max) * 8;
          return <rect key={i} x={i * 8 + 1} y={8 - h} width={6} height={h} fill="rgba(230,232,238,.65)" />;
        })}
      </svg>
    );
  }

  function Row({ stat }: { stat: TopicStat }) {
    const [expanded, setExpanded] = useState(false);
    const envelopes = useStore((s) => s.envelopes);
    const recent5 = envelopes.filter((e) => e.topic === stat.topic).slice(-5).reverse();

    const onRowClick = () => {
      const mostRecent = recent5[0];
      if (!mostRecent) return;
      selectRegionFromRow(useStore, {
        regionName: mostRecent.source_region,
        envelopeKey: `${mostRecent.observed_at}|${mostRecent.topic}`,
      });
    };

    return (
      <>
        <div
          className="grid grid-cols-[1fr_auto_auto_auto_auto_auto_auto] items-center gap-2 px-2 py-1 cursor-pointer hover:bg-[rgba(230,232,238,.05)]"
          onClick={onRowClick}
        >
          <span className="font-mono text-[11px] truncate">{stat.topic}</span>
          <span className="font-mono text-[10px] px-1 rounded bg-[rgba(255,255,255,.05)]">{kindTag(stat.topic)}</span>
          <span className="font-mono text-[10px] text-[rgba(230,232,238,.9)]">{stat.ewmaRate.toFixed(1)} msg/s</span>
          <Sparkline buckets={stat.sparkBuckets} />
          <span className="font-mono text-[10px] opacity-70">{stat.publishers.size} pub</span>
          <span className="font-mono text-[10px] opacity-60">{relativeTime(stat.lastSeenMs)}</span>
          <button className="text-[10px] opacity-70" onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}>
            {expanded ? '▾' : '▸'}
          </button>
        </div>
        {expanded && (
          <div className="pl-6 pb-1">
            {recent5.map((env) => (
              <div
                key={`${env.observed_at}|${env.source_region ?? ''}`}
                className="text-[10px] font-mono cursor-pointer hover:opacity-100 opacity-75"
                onClick={() => selectRegionFromRow(useStore, {
                  regionName: env.source_region,
                  envelopeKey: `${env.observed_at}|${env.topic}`,
                })}
              >
                {new Date(env.observed_at).toISOString().slice(11, 23)} · {env.source_region ?? '—'}
              </div>
            ))}
          </div>
        )}
      </>
    );
  }

  export function Topics() {
    const stats = useTopicStats();
    if (stats.size === 0) {
      return <div className="p-3 text-xs opacity-60">No topics yet — waiting for envelopes…</div>;
    }
    const rows = Array.from(stats.values()).sort((a, b) => {
      if (b.ewmaRate !== a.ewmaRate) return b.ewmaRate - a.ewmaRate;
      return a.lastSeenMs - b.lastSeenMs;
    });
    return (
      <div className="overflow-y-auto h-full">
        {rows.map((s) => <Row key={s.topic} stat={s} />)}
      </div>
    );
  }
  ```

- [ ] **Step 7 — Wire into `Dock.tsx`.**

  ```tsx
  import { Topics } from './Topics';
  import { useTopicStats } from './useTopicStats';

  // In Dock:
  const topicsMap = useTopicStats();
  // pass topicCount={topicsMap.size} to DockTabStrip
  // render {tab === 'topics' && <Topics />}
  ```

- [ ] **Step 8 — Run tests + typecheck.**

  ```
  cd observatory/web-src && npx vitest run dock/ && npx tsc -b
  ```

- [ ] **Step 9 — Commit.**

  ```bash
  git add observatory/web-src/src/dock/
  git commit -m "$(cat <<'EOF'
  observatory: topics tab + useTopicStats (v3 task 6)

  1 Hz selector builds Map<topic, TopicStat> with EWMA rate (α=0.1),
  rolling 6-bucket * 10 s sparkline, publisher set decaying after 60 s
  of silence, and wallclock last-seen. Topics tab renders rows sorted
  by ewmaRate desc (secondary: newest last-seen), with per-row expand
  into last 5 envelopes. Reuses selectRegionFromRow for click-through.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 7 — Metacognition tab + dock badge

**Files:**
- Create: `observatory/web-src/src/dock/Metacog.tsx`
- Create: `observatory/web-src/src/dock/Metacog.test.tsx`
- Modify: `observatory/web-src/src/dock/Dock.tsx`

### Context for implementer

Per spec §7, filter envelope ring to `hive/metacognition/`. Color rows:
- `error.*` → left-border `#ff8a88`
- `conflict.*` → left-border `#ffc07a`
- `reflection.*` → left-border `rgba(210,212,220,.55)`

Dock tab badge count = events in last 60 s; severity color red > amber > grey.

Title extraction (spec §7.1): for errors, `payload.data.kind + ': ' + payload.data.detail` when both present; fall back to `JSON.stringify(payload.data).slice(0, 120)`.

Click → `selectRegionFromRow` (which sets `pendingEnvelopeKey` → Messages scroll + expand via Task 10).

### Steps

- [ ] **Step 1 — Write failing component tests.**

  Create `observatory/web-src/src/dock/Metacog.test.tsx`:

  ```tsx
  import { describe, it, expect, afterEach } from 'vitest';
  import { render, cleanup } from '@testing-library/react';
  import { Metacog } from './Metacog';
  import { useStore } from '../store';

  afterEach(() => { cleanup(); useStore.setState({ envelopes: [], envelopesReceivedTotal: 0 }); });

  function pushMetacog(topic: string, source: string, data: unknown, observed_at = Date.now()) {
    useStore.getState().pushEnvelope({
      observed_at,
      topic,
      envelope: { payload: { content_type: 'application/json', data } } as unknown as Record<string, unknown>,
      source_region: source,
      destinations: [],
    });
  }

  describe('Metacog', () => {
    it('filters to hive/metacognition topics', () => {
      pushMetacog('hive/metacognition/error/detected', 'pfc', { kind: 'E', detail: 'd' });
      pushMetacog('hive/cognitive/pfc/plan', 'pfc', {});
      const { container } = render(<Metacog />);
      expect(container.querySelectorAll('[data-testid="metacog-row"]').length).toBe(1);
    });

    it('extracts title as kind + ": " + detail for errors', () => {
      pushMetacog('hive/metacognition/error/detected', 'pfc', { kind: 'LlmError', detail: 'rate_limit' });
      const { getByText } = render(<Metacog />);
      expect(getByText(/LlmError:\s*rate_limit/)).toBeTruthy();
    });
  });
  ```

- [ ] **Step 2 — Run to verify failure.** Expected: FAILED.

- [ ] **Step 3 — Implement Metacog.**

  Create `observatory/web-src/src/dock/Metacog.tsx`:

  ```tsx
  import { useEffect, useRef } from 'react';
  import { useStore, Envelope } from '../store';
  import { selectRegionFromRow } from './selectRegionFromRow';

  function titleOf(env: Envelope): string {
    const payload = (env.envelope as { payload?: { data?: unknown } }).payload;
    const data = payload?.data as { kind?: string; detail?: string } | undefined;
    if (data?.kind && data?.detail) return `${data.kind}: ${data.detail}`.slice(0, 120);
    try { return JSON.stringify(data).slice(0, 120); } catch { return String(data ?? ''); }
  }

  function colorOf(topic: string): string {
    if (topic.includes('/error/')) return '#ff8a88';
    if (topic.includes('/conflict/')) return '#ffc07a';
    if (topic.includes('/reflection/')) return 'rgba(210,212,220,.55)';
    return 'rgba(230,232,238,.45)';
  }

  function kindOf(topic: string): string {
    const parts = topic.split('/');
    return `${parts.at(-2) ?? ''}.${parts.at(-1) ?? ''}`;
  }

  function ts(ms: number) { return new Date(ms).toISOString().slice(11, 23); }

  export function Metacog() {
    const envs = useStore((s) => s.envelopes);
    const rows = envs.filter((e) => e.topic.startsWith('hive/metacognition/'));

    const scrollRef = useRef<HTMLDivElement | null>(null);
    useEffect(() => {
      const el = scrollRef.current;
      if (!el) return;
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
      if (nearBottom) el.scrollTop = el.scrollHeight;
    }, [rows.length]);

    if (rows.length === 0) return <div className="p-3 text-xs opacity-60">No metacognition events yet.</div>;

    return (
      <div ref={scrollRef} className="overflow-y-auto h-full">
        {rows.map((e) => (
          <div
            key={`${e.observed_at}|${e.topic}`}
            data-testid="metacog-row"
            className="grid grid-cols-[auto_auto_auto_1fr] items-center gap-2 px-2 py-1 cursor-pointer hover:bg-[rgba(230,232,238,.05)]"
            style={{ borderLeft: `2px solid ${colorOf(e.topic)}` }}
            onClick={() => selectRegionFromRow(useStore, {
              regionName: e.source_region,
              envelopeKey: `${e.observed_at}|${e.topic}`,
            })}
          >
            <span className="font-mono text-[10px] text-[rgba(136,140,152,.70)]">{ts(e.observed_at)}</span>
            <span className="text-[11px] truncate max-w-[14ch]">{e.source_region ?? '—'}</span>
            <span className="font-mono text-[10px] opacity-80">{kindOf(e.topic)}</span>
            <span className="font-mono text-[10px] truncate opacity-80">{titleOf(e)}</span>
          </div>
        ))}
      </div>
    );
  }
  ```

- [ ] **Step 4 — Wire into `Dock.tsx` with live badge.**

  ```tsx
  import { Metacog } from './Metacog';

  function useMetacogBadge(): { count: number; severity: 'error' | 'conflict' | 'quiet' } {
    const envs = useStore((s) => s.envelopes);
    const now = Date.now();
    const recent = envs.filter((e) => e.topic.startsWith('hive/metacognition/') && now - e.observed_at < 60_000);
    const errors = recent.filter((e) => e.topic.includes('/error/')).length;
    const conflicts = recent.filter((e) => e.topic.includes('/conflict/')).length;
    return {
      count: recent.length,
      severity: errors > 0 ? 'error' : conflicts > 0 ? 'conflict' : 'quiet',
    };
  }

  // In Dock:
  const metacogBadge = useMetacogBadge();
  // pass to DockTabStrip; render {tab === 'metacog' && <Metacog />}
  ```

- [ ] **Step 5 — Run tests + typecheck + commit.**

  ```
  cd observatory/web-src && npx vitest run dock/ && npx tsc -b
  ```

  ```bash
  git add observatory/web-src/src/dock/
  git commit -m "$(cat <<'EOF'
  observatory: metacognition tab + badge (v3 task 7)

  Filters envelope ring to hive/metacognition/#; rows colored by kind
  (error red, conflict amber, reflection grey). Title extraction uses
  payload.data.kind + ': ' + payload.data.detail for errors, falling
  back to JSON.stringify for conflicts/reflections. Dock tab badge shows
  count-last-60s with severity color (red if any error, amber if any
  conflict, grey otherwise).

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 8 — Inspector: Appendix section + Prompt relabel

**Files:**
- Create: `observatory/web-src/src/inspector/sections/Appendix.tsx`
- Create: `observatory/web-src/src/inspector/sections/Appendix.test.tsx`
- Modify: `observatory/web-src/src/inspector/sections/Prompt.tsx`
- Modify: `observatory/web-src/src/inspector/Inspector.tsx`

### Context for implementer

Per spec §9: keep Prompt's shape; relabel header to `Prompt (DNA)`. Add Appendix as a sibling `<details>` below Prompt, **expanded by default**.

**On 404** → empty-state `"No appendix yet — region hasn't slept."`
**On non-404 error** → `Failed: <message>`.
**Auto-refetch** on `phase` or `last_error_ts` change (skip first render — v2 Task 13 pattern).
**Ordering:** parser preserves file order (chronological); reverse in the component before rendering (newest first).

### Steps

- [ ] **Step 1 — Write failing tests.**

  Create `observatory/web-src/src/inspector/sections/Appendix.test.tsx`:

  ```tsx
  import { describe, it, expect, vi, afterEach } from 'vitest';
  import { render, cleanup, fireEvent } from '@testing-library/react';
  import * as rest from '../../api/rest';
  import { Appendix } from './Appendix';

  afterEach(() => { cleanup(); vi.restoreAllMocks(); });

  describe('Appendix', () => {
    it('renders entries newest-first', async () => {
      vi.spyOn(rest, 'fetchAppendix').mockResolvedValue(
        '## 2026-04-22T10:00:00Z — sleep\n\nfirst entry body\n\n## 2026-04-22T12:00:00Z — sleep\n\nsecond entry body\n',
      );
      const { container, findByText } = render(<Appendix name="pfc" phase="wake" lastErrorTs={null} />);
      await findByText(/second entry body/);
      const text = container.textContent ?? '';
      expect(text.indexOf('second entry body')).toBeLessThan(text.indexOf('first entry body'));
    });

    it('shows empty state on 404', async () => {
      vi.spyOn(rest, 'fetchAppendix').mockRejectedValue(new rest.RestError(404, 'missing'));
      const { findByText } = render(<Appendix name="fresh" phase="wake" lastErrorTs={null} />);
      expect(await findByText(/No appendix yet — region hasn't slept\./i)).toBeTruthy();
    });

    it('surfaces non-404 errors inline', async () => {
      vi.spyOn(rest, 'fetchAppendix').mockRejectedValue(new rest.RestError(403, 'sandbox'));
      const { findByText } = render(<Appendix name="pfc" phase="wake" lastErrorTs={null} />);
      expect(await findByText(/Failed:\s*sandbox/i)).toBeTruthy();
    });

    it('reload triggers refetch', async () => {
      const spy = vi.spyOn(rest, 'fetchAppendix').mockResolvedValue('## 2026-04-22T10:00:00Z — sleep\n\nfirst');
      const { findByText, getByText } = render(<Appendix name="pfc" phase="wake" lastErrorTs={null} />);
      await findByText(/first/);
      spy.mockResolvedValue('## 2026-04-22T11:00:00Z — sleep\n\nsecond');
      fireEvent.click(getByText(/reload/i));
      await findByText(/second/);
    });
  });
  ```

- [ ] **Step 2 — Run to verify failure.** Expected: FAILED.

- [ ] **Step 3 — Implement `Appendix.tsx`.**

  Create `observatory/web-src/src/inspector/sections/Appendix.tsx`:

  ```tsx
  import { useEffect, useRef } from 'react';
  import { useRegionAppendix } from '../useRegionAppendix';
  import { parseAppendix } from './parseAppendix';
  import { fmtBytes } from '../format';

  export function Appendix({
    name,
    phase,
    lastErrorTs,
  }: {
    name: string;
    phase: string;
    lastErrorTs: string | null;
  }) {
    const { loading, error, data, reload } = useRegionAppendix(name);

    const firstRef = useRef(true);
    useEffect(() => {
      if (firstRef.current) { firstRef.current = false; return; }
      reload();
    }, [phase, lastErrorTs, reload]);

    const entries = data == null ? [] : parseAppendix(data).reverse();
    const sizeLabel = data ? `${fmtBytes(data.length)} · ${entries.length} entries` : '';

    return (
      <details open className="border-t border-[rgba(80,84,96,.35)]">
        <summary className="cursor-pointer px-3 py-1 text-[11px] flex items-center gap-2">
          <span className="font-medium">Appendix <span className="opacity-60">(rolling)</span></span>
          <span className="opacity-60 font-mono text-[10px]">{sizeLabel}</span>
          <button
            onClick={(e) => { e.preventDefault(); e.stopPropagation(); reload(); }}
            className="ml-auto text-[10px] opacity-70 hover:opacity-100"
            title="Reload"
          >
            reload
          </button>
        </summary>
        <div className="px-3 pb-2 max-h-[360px] overflow-y-auto">
          {loading && <div className="h-6 bg-[rgba(255,255,255,.04)] rounded animate-pulse" />}
          {error && <div className="text-[11px] text-[#ff8a88]">Failed: {error.message}</div>}
          {!loading && !error && data === '' && (
            <div className="text-[11px] opacity-70">No appendix yet — region hasn't slept.</div>
          )}
          {!loading && !error && entries.length > 0 && entries.map((e, i) => (
            <div key={i} className="mb-2">
              <div className="flex gap-2 items-baseline">
                <span className="font-mono text-[10px] opacity-60">{e.ts || '—'}</span>
                {e.trigger && (
                  <span className="text-[11px] px-1 rounded bg-[rgba(255,255,255,.06)]">{e.trigger}</span>
                )}
              </div>
              <pre className="font-mono text-[10px] whitespace-pre-wrap opacity-85 mt-1">{e.body}</pre>
            </div>
          ))}
        </div>
      </details>
    );
  }
  ```

- [ ] **Step 4 — Relabel `Prompt.tsx`.**

  Open `observatory/web-src/src/inspector/sections/Prompt.tsx`. In the summary, change the section title to `Prompt (DNA)` and keep the existing byte-size rendering next to it. Match the existing size-label pattern already in the file — do not duplicate state.

- [ ] **Step 5 — Mount `<Appendix />` in `Inspector.tsx`.**

  Read `observatory/web-src/src/inspector/Inspector.tsx`. In the section list, immediately after the Prompt mount, insert:

  ```tsx
  <Appendix name={name} phase={stats.phase} lastErrorTs={stats.last_error_ts} />
  ```

  (Use the exact prop names Prompt receives — read the file first.)

- [ ] **Step 6 — Run tests + typecheck.**

  ```
  cd observatory/web-src && npx vitest run inspector/ && npx tsc -b
  ```

- [ ] **Step 7 — Commit.**

  ```bash
  git add observatory/web-src/src/inspector/
  git commit -m "$(cat <<'EOF'
  observatory: inspector Appendix section + Prompt DNA relabel (v3 task 8)

  Appendix mounts directly below Prompt in the inspector slide-over.
  Uses useRegionAppendix (404 -> data:''); renders parsed entries
  newest-first with timestamp + trigger tag + monospace body. Empty
  state fires on 404 ('No appendix yet - region has not slept');
  non-404 errors surface as the standard red Failed row. Auto-refetch
  on phase/last_error_ts change (skip first render, v2 Task 13 pattern).
  Prompt summary relabeled to 'Prompt (DNA)' to reflect post-ecd8a94
  immutability.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 9 — HUD: `SystemMetrics` tile + `SelfState` replacement + store raw `retained` map

**Files:**
- Create: `observatory/web-src/src/hud/SystemMetrics.tsx`
- Create: `observatory/web-src/src/hud/SystemMetrics.test.tsx`
- Create: `observatory/web-src/src/hud/SelfState.tsx`
- Create: `observatory/web-src/src/hud/SelfState.test.tsx`
- Delete: `observatory/web-src/src/hud/SelfPanel.tsx`
- Modify: `observatory/web-src/src/hud/Hud.tsx`
- Modify: `observatory/web-src/src/store.ts`
- Modify: `observatory/web-src/src/store.test.ts`

### Context for implementer

Per spec §10, two new HUD tiles. Read `glia/metrics.py::build_compute_payload`, `build_tokens_payload`, `build_region_health_payload` to confirm exact schemas before coding.

**`ambient.self`** is populated by Task 2 from four retained topics — SelfState reads `store.ambient.self` directly.

**`hive/system/metrics/*`** is retained but the store's v2 `ambient` projection doesn't include it. Add a raw `retained: Record<string, unknown>` field that keeps the full retained payload map (keyed by topic). `applySnapshot` + `applyRetained` both populate it.

### Steps

- [ ] **Step 1 — Add `retained` raw map to store (TDD).**

  Append to `observatory/web-src/src/store.test.ts`:

  ```typescript
  it('retained map captures snapshot + live updates', () => {
    const store = createStore();
    store.getState().applySnapshot({
      regions: {}, recent: [], server_version: 't',
      retained: { 'hive/system/metrics/compute': { payload: { total_cpu_pct: 42 } } },
    });
    expect(store.getState().retained['hive/system/metrics/compute']).toEqual({ total_cpu_pct: 42 });
    store.getState().applyRetained('hive/system/metrics/tokens', { total_input_tokens: 10 });
    expect(store.getState().retained['hive/system/metrics/tokens']).toEqual({ total_input_tokens: 10 });
  });
  ```

- [ ] **Step 2 — Extend store.**

  In `store.ts`:

  ```typescript
  type State = {
    // existing fields …
    retained: Record<string, unknown>;
  };

  // In createStore:
  retained: {},
  applySnapshot: (s) => set({
    regions: s.regions,
    envelopes: s.recent,
    envelopesReceivedTotal: s.recent.length,
    ambient: extractAmbient(s.retained),
    retained: Object.fromEntries(
      Object.entries(s.retained).map(([k, v]) => [k, (v as { payload?: unknown }).payload ?? null]),
    ),
  }),
  applyRetained: (topic, payload) => {
    // existing ambient update body …
    set({ retained: { ...get().retained, [topic]: payload } });
  },
  ```

- [ ] **Step 3 — Run store test.** Expected: pass.

- [ ] **Step 4 — Write failing `SystemMetrics` tests.**

  Create `observatory/web-src/src/hud/SystemMetrics.test.tsx`:

  ```tsx
  import { describe, it, expect, afterEach } from 'vitest';
  import { render, cleanup } from '@testing-library/react';
  import { SystemMetrics } from './SystemMetrics';
  import { useStore } from '../store';

  afterEach(() => { cleanup(); useStore.setState({ retained: {} }); });

  describe('SystemMetrics', () => {
    it('renders CPU + mem from compute topic', () => {
      useStore.setState({ retained: { 'hive/system/metrics/compute': { total_cpu_pct: 42.7, total_mem_mb: 1024 } } });
      const { getByText } = render(<SystemMetrics />);
      expect(getByText(/42\.7%/)).toBeTruthy();
      expect(getByText(/1024 MB/)).toBeTruthy();
    });

    it('renders token totals', () => {
      useStore.setState({ retained: { 'hive/system/metrics/tokens': { total_input_tokens: 1234, total_output_tokens: 5678 } } });
      const { getByText } = render(<SystemMetrics />);
      expect(getByText(/1234/)).toBeTruthy();
      expect(getByText(/5678/)).toBeTruthy();
    });

    it('renders heatmap cells from region_health', () => {
      useStore.setState({ retained: { 'hive/system/metrics/region_health': {
        per_region: { pfc: 'alive', amygdala: 'stale', acc: 'dead' },
      } } });
      const { container } = render(<SystemMetrics />);
      expect(container.querySelectorAll('[data-testid="health-cell"]').length).toBe(3);
    });

    it('shows dashes when topic missing', () => {
      const { getByText } = render(<SystemMetrics />);
      expect(getByText(/CPU\s+—/i)).toBeTruthy();
    });
  });
  ```

- [ ] **Step 5 — Implement `SystemMetrics`.**

  Create `observatory/web-src/src/hud/SystemMetrics.tsx`:

  ```tsx
  import { useStore } from '../store';

  type Compute = { total_cpu_pct?: number; total_mem_mb?: number };
  type Tokens = { total_input_tokens?: number; total_output_tokens?: number };
  type Health = { per_region?: Record<string, 'alive' | 'stale' | 'dead' | 'unknown'> };

  const HEALTH_COLOR = {
    alive: '#85d19a',
    stale: '#d6b85a',
    dead: '#d66a6a',
    unknown: 'rgba(136,140,152,.35)',
  };

  export function SystemMetrics() {
    const compute = useStore((s) => s.retained['hive/system/metrics/compute'] as Compute | undefined);
    const tokens = useStore((s) => s.retained['hive/system/metrics/tokens'] as Tokens | undefined);
    const health = useStore((s) => s.retained['hive/system/metrics/region_health'] as Health | undefined);

    const regions = Object.entries(health?.per_region ?? {});

    return (
      <div className="p-3 bg-hive-panel/80 backdrop-blur rounded-md max-w-xs text-[11px]">
        <div className="text-[10px] tracking-widest opacity-60 uppercase mb-1">Metrics</div>
        <div className="flex gap-4 font-mono text-[11px]">
          <span>CPU {compute?.total_cpu_pct != null ? `${compute.total_cpu_pct.toFixed(1)}%` : '—'}</span>
          <span>Mem {compute?.total_mem_mb != null ? `${Math.round(compute.total_mem_mb)} MB` : '—'}</span>
        </div>
        <div className="flex gap-4 font-mono text-[11px] mt-1">
          <span>In {tokens?.total_input_tokens ?? '—'}</span>
          <span>Out {tokens?.total_output_tokens ?? '—'}</span>
        </div>
        <div className="mt-2 flex flex-wrap gap-[2px]">
          {regions.map(([name, status]) => (
            <div
              key={name}
              data-testid="health-cell"
              title={`${name} · ${status}`}
              style={{
                width: 10,
                height: 10,
                background: HEALTH_COLOR[status] ?? HEALTH_COLOR.unknown,
              }}
            />
          ))}
        </div>
      </div>
    );
  }
  ```

- [ ] **Step 6 — Write failing `SelfState` tests.**

  Create `observatory/web-src/src/hud/SelfState.test.tsx`:

  ```tsx
  import { describe, it, expect, afterEach } from 'vitest';
  import { render, cleanup, fireEvent } from '@testing-library/react';
  import { SelfState } from './SelfState';
  import { useStore } from '../store';

  afterEach(() => { cleanup(); useStore.setState({ ambient: { modulators: {}, self: {} } }); });

  describe('SelfState', () => {
    it('identity tab default, renders identity text', () => {
      useStore.setState({ ambient: { modulators: {}, self: { identity: 'I am Hive.' } } });
      const { getByText } = render(<SelfState />);
      expect(getByText(/I am Hive\./)).toBeTruthy();
    });

    it('switches to values tab', () => {
      useStore.setState({ ambient: { modulators: {}, self: { identity: 'x', values: ['curiosity', 'care'] } } });
      const { getByText } = render(<SelfState />);
      fireEvent.click(getByText(/^Values$/));
      expect(getByText(/curiosity/)).toBeTruthy();
      expect(getByText(/care/)).toBeTruthy();
    });

    it('empty state per tab', () => {
      useStore.setState({ ambient: { modulators: {}, self: {} } });
      const { getByText } = render(<SelfState />);
      expect(getByText(/No data yet — mPFC hasn't published\./i)).toBeTruthy();
    });
  });
  ```

- [ ] **Step 7 — Implement `SelfState`.**

  Create `observatory/web-src/src/hud/SelfState.tsx`:

  ```tsx
  import { useState } from 'react';
  import { useStore } from '../store';

  type Tab = 'identity' | 'values' | 'personality' | 'autobio';
  const TABS: Array<{ id: Tab; label: string }> = [
    { id: 'identity', label: 'Identity' },
    { id: 'values', label: 'Values' },
    { id: 'personality', label: 'Personality' },
    { id: 'autobio', label: 'Autobio' },
  ];

  function renderBody(tab: Tab, self: ReturnType<typeof useStore.getState>['ambient']['self']) {
    let v: unknown;
    if (tab === 'identity') v = self.identity;
    if (tab === 'values') v = self.values;
    if (tab === 'personality') v = self.personality;
    if (tab === 'autobio') v = self.autobiographical_index;
    if (v === undefined || v === '' || v === null) {
      return <div className="text-xs opacity-60">No data yet — mPFC hasn't published.</div>;
    }
    if (typeof v === 'string') return <div className="text-sm leading-snug">{v}</div>;
    if (Array.isArray(v)) {
      if (tab === 'autobio') {
        return (
          <ul className="text-xs leading-snug list-none space-y-0.5">
            {(v as Array<{ ts?: string; headline?: string }>).slice(0, 20).map((e, i) => (
              <li key={i} className="font-mono">
                <span className="opacity-60">{e.ts ?? '—'}</span> · {e.headline ?? JSON.stringify(e).slice(0, 80)}
              </li>
            ))}
            {v.length > 20 && <li className="opacity-60 text-[10px]">{v.length - 20} more…</li>}
          </ul>
        );
      }
      return (
        <ul className="text-xs leading-snug list-disc list-inside">
          {(v as unknown[]).map((x, i) => <li key={i}>{typeof x === 'string' ? x : JSON.stringify(x)}</li>)}
        </ul>
      );
    }
    if (typeof v === 'object') {
      return (
        <ul className="text-xs leading-snug list-none space-y-0.5 font-mono">
          {Object.entries(v as Record<string, unknown>).map(([k, val]) => (
            <li key={k}>
              <span className="opacity-60">{k}</span> · {typeof val === 'object' ? JSON.stringify(val) : String(val)}
            </li>
          ))}
        </ul>
      );
    }
    return <div className="text-sm">{String(v)}</div>;
  }

  export function SelfState() {
    const self = useStore((s) => s.ambient.self);
    const [tab, setTab] = useState<Tab>('identity');

    return (
      <div className="p-3 bg-hive-panel/80 backdrop-blur rounded-md max-w-xs">
        <div className="text-[10px] tracking-widest opacity-60 uppercase mb-1">Self</div>
        <div className="flex gap-2 mb-2 text-[11px]">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={[
                'pb-0.5',
                tab === t.id ? 'border-b border-[rgba(230,232,238,.9)] text-[rgba(230,232,238,.95)]' : 'opacity-55',
              ].join(' ')}
            >
              {t.label}
            </button>
          ))}
        </div>
        {renderBody(tab, self)}
      </div>
    );
  }
  ```

- [ ] **Step 8 — Update `Hud.tsx`; delete `SelfPanel.tsx`.**

  Open `observatory/web-src/src/hud/Hud.tsx`. Replace:

  ```tsx
  import { SelfState } from './SelfState';
  import { SystemMetrics } from './SystemMetrics';
  import { Modulators } from './Modulators';
  import { Counters } from './Counters';

  export function Hud() {
    return (
      <div className="fixed top-3 left-3 flex flex-col gap-2 z-20">
        <SelfState />
        <SystemMetrics />
        <Modulators />
        <Counters />
      </div>
    );
  }
  ```

  Delete `observatory/web-src/src/hud/SelfPanel.tsx`.

- [ ] **Step 9 — Run tests + typecheck.**

  ```
  cd observatory/web-src && rm -f src/hud/SelfPanel.tsx && npx vitest run hud/ store.test.ts && npx tsc -b
  ```

- [ ] **Step 10 — Commit.**

  ```bash
  git add -A observatory/web-src/src/hud/ observatory/web-src/src/store.ts observatory/web-src/src/store.test.ts
  git commit -m "$(cat <<'EOF'
  observatory: HUD — SystemMetrics tile + SelfState replacement (v3 task 9)

  SystemMetrics reads retained hive/system/metrics/{compute,tokens,
  region_health} via new store.retained map. SelfState replaces
  SelfPanel.tsx with four tabs (Identity / Values / Personality /
  Autobio). Hud.tsx renders SelfState > SystemMetrics > Modulators >
  Counters top-to-bottom.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 10 — Messages section: JsonTree row expand + `pendingEnvelopeKey` consumption

**Files:**
- Modify: `observatory/web-src/src/inspector/sections/Messages.tsx`
- Modify: `observatory/web-src/src/inspector/Messages.test.tsx`

### Context for implementer

v2 Task 14 shipped Messages with an 80-char payload preview. v3 Task 10 adds:

1. **Chevron expand per row.** Same `JsonTree` component used by v2 Stm + v3 Firehose. Expand state keyed by `${observed_at}|${topic}` (existing v2 key shape).
2. **`pendingEnvelopeKey` consumption.** When `pendingEnvelopeKey` changes to a non-null value matching a row's identity key, scroll it into view + auto-expand, then clear the key.

**Do not break v2 auto-scroll-to-bottom** for new envelopes. The pending-key scroll is a one-shot override.

### Steps

- [ ] **Step 1 — Add failing tests to `Messages.test.tsx`.**

  Follow the existing v2 test shape. Add:

  ```tsx
  it('chevron expands row to JsonTree view', () => {
    // seed one envelope, render, click chevron, assert JsonTree output visible
  });

  it('pendingEnvelopeKey causes scroll + auto-expand then clears the key', async () => {
    // seed envelopes; setState({ pendingEnvelopeKey: matching-key })
    // render; await waitFor expanded + key === null
  });
  ```

  Use the existing store/fixture helpers already present in `Messages.test.tsx`.

- [ ] **Step 2 — Run to verify failure.** Expected: FAILED.

- [ ] **Step 3 — Implement changes in `Messages.tsx`.**

  ```tsx
  import { useEffect, useRef } from 'react';
  import { JsonTree } from './JsonTree';

  export function Messages(/* existing props */) {
    // existing filter + autoscroll + incremental-scan unchanged
    const pendingKey = useStore((s) => s.pendingEnvelopeKey);
    const setPendingKey = useStore((s) => s.setPendingEnvelopeKey);
    const expandedRowIds = useStore((s) => s.expandedRowIds);
    const toggleRowExpand = useStore((s) => s.toggleRowExpand);
    const rowRefs = useRef(new Map<string, HTMLDivElement>());

    useEffect(() => {
      if (!pendingKey) return;
      const node = rowRefs.current.get(pendingKey);
      if (node) {
        node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        if (!expandedRowIds.has(pendingKey)) toggleRowExpand(pendingKey);
      }
      setPendingKey(null);
    }, [pendingKey, expandedRowIds, toggleRowExpand, setPendingKey]);

    return (
      /* existing wrapper */
      /* for each row: */
      <div
        key={id}
        ref={(n) => { if (n) rowRefs.current.set(id, n); else rowRefs.current.delete(id); }}
        /* existing row classes */
      >
        {/* existing timestamp/source/topic/preview rendering */}
        <button onClick={(e) => { e.stopPropagation(); toggleRowExpand(id); }}>
          {expandedRowIds.has(id) ? '▾' : '▸'}
        </button>
        {expandedRowIds.has(id) && (
          <div className="pl-6 py-1 text-[10px]">
            <JsonTree value={env.envelope} />
          </div>
        )}
      </div>
    );
  }
  ```

  (The exact integration depends on the current `Messages.tsx` — read it first and splice in without breaking the auto-scroll or filter paths.)

- [ ] **Step 4 — Run tests + typecheck.** Expected: pass.

- [ ] **Step 5 — Commit.**

  ```bash
  git add observatory/web-src/src/inspector/
  git commit -m "$(cat <<'EOF'
  observatory: Messages — JsonTree expand + pendingEnvelopeKey (v3 task 10)

  Row chevron expands full envelope JSON via shared JsonTree component
  (same instance used by v2 Stm + v3 Firehose). pendingEnvelopeKey
  consumption: when the store field is set to a row identity key
  ({observed_at}|{topic}), scroll the row into view and auto-expand,
  then clear the key. v2 auto-scroll-to-bottom for new envelopes stays
  intact - pending-key scroll is a one-shot override.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 11 — Integration, verification, HANDOFF closure

**Files:**
- Modify: `observatory/tests/component/test_end_to_end.py`
- Modify: `observatory/HANDOFF.md`
- Append: `observatory/memory/decisions.md`

### Context for implementer

No production code changes. Final task:

1. Extend component E2E to cover `/appendix`.
2. Run full unit + component + frontend suites + ruff + production build + smoke test.
3. Bump `HANDOFF.md` with a v3 row + changelog entry.

### Steps

- [ ] **Step 1 — Extend component E2E.**

  Open `observatory/tests/component/test_end_to_end.py`. Add a test that:
  - Creates a temp regions dir with one region that has `memory/appendices/rolling.md`.
  - Boots FastAPI pointed at it + testcontainers mosquitto.
  - Hits `GET /api/regions/<name>/appendix`, asserts 200 + body.

  Follow v2's `test_config_redaction_and_handlers_tree` pattern for the seed-temp-regions-dir setup.

- [ ] **Step 2 — Run full backend suites.**

  ```
  python -m pytest observatory/tests/unit/ -q
  python -m pytest observatory/tests/component/ -m component -v
  python -m ruff check observatory/
  ```
  Expected: all unit pass, 3 component pass (v1 pub→ws + v2 config-redaction + v3 appendix), ruff clean.

- [ ] **Step 3 — Run full frontend suite + build.**

  ```
  cd observatory/web-src && npx vitest run && npx tsc -b && npm run build
  ```
  Expected: all green; `observatory/web/` emitted.

- [ ] **Step 4 — Smoke test the static mount.**

  ```
  .venv/Scripts/python.exe -m observatory &
  sleep 3
  curl -s http://127.0.0.1:8765/api/health
  curl -s http://127.0.0.1:8765/api/regions/prefrontal_cortex/appendix -o appendix.tmp -w "%{http_code}\n"
  curl -s -o - http://127.0.0.1:8765/ | head -c 100
  kill %1
  ```

  Expected: health 200, appendix 404 (fresh region — no rolling.md yet), HTML index head.

- [ ] **Step 5 — Update `observatory/HANDOFF.md`.**

  Bump `Last updated`, add v3 tasks 1–11 to progress table (commits SHAs), add suite snapshot, add changelog row.

- [ ] **Step 6 — Append to `observatory/memory/decisions.md`.**

  One entry per non-obvious implementer call from Tasks 1–10 (following existing numbering).

- [ ] **Step 7 — Commit.**

  ```bash
  git add observatory/tests/component/ observatory/HANDOFF.md observatory/memory/decisions.md
  git commit -m "$(cat <<'EOF'
  observatory: v3 ships (task 11)

  Verification-only. Full suite green (unit + component + vitest + ruff
  + build + smoke). Component E2E extended to cover /appendix via seeded
  temp regions dir + real FastAPI mount + testcontainers mosquitto.
  HANDOFF bumped with v3 ship details.

  Canonical resume prompt pivots to: continue observatory v4.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Self-review notes

**Spec coverage:**
- §2 scope items 1-8 → Tasks 1-10.
- §3 wire audit → informational only.
- §4 dock → Task 4.
- §5 Firehose → Task 5.
- §6 Topics → Task 6.
- §7 Metacog → Task 7.
- §8 interaction model → implemented across Tasks 4-7 via `selectRegionFromRow`; consumed by Task 10.
- §9 Appendix → Task 8 (backend route in Task 1).
- §10 HUD → Task 9.
- §11 Messages upgrade → Task 10.
- §12 store → Task 2 + Task 9 Step 2.
- §13 file layout → matches File Structure above.
- §14 testing → every task starts with a red test.
- §15 performance → flagged in Tasks 5/6 implementation notes.
- §16 open questions → implementer discretion; decisions.md capture on resolution.
- §17 non-goals → no task touches them.

**Placeholder scan:** no "TBD"/"TODO". Task 10 Step 1 has abbreviated test bodies that reference the existing v2 `Messages.test.tsx` shape — acceptable because the implementer should follow the neighbour tests, not invent a new pattern.

**Type consistency:** `selectRegionFromRow({regionName, envelopeKey})` identical across Tasks 4, 5, 6, 7. `TopicStat` defined + consumed in Task 6. `AppendixEntry` defined Task 3, used Task 8. Store additions from Task 2 consumed by every later task exactly as declared. Task 9 adds the `retained` field with no collisions against Task 2's additions.
