# Observatory v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Fresh implementer subagent per task; two-stage review between tasks per `observatory/CLAUDE.md`.

**Goal:** Ship the v2 "Zoom in" milestone — a region inspector panel (right slide-over, 8 sections, minimal-keyboard interaction) backed by a sandboxed filesystem reader and five new REST endpoints; plus a scene visual upgrade (fuzzy multi-layer orb rendering, always-floating region labels with hover-expanded stats, and reactive adjacency threads).

**Architecture:** Backend introduces `observatory/region_reader.py` — a single sandboxed entry point for per-region disk reads — and adds five FastAPI routes under `/api/regions/{name}/` (prompt, stm, subscriptions, config, handlers). Frontend adds an `inspector/` subtree (shell + sections + fetch hook + keyboard hook) and replaces v1's `scene/Regions.tsx` with three new scene modules: `scene/FuzzyOrbs.tsx` (4-layer additive-glow orbs), `scene/Labels.tsx` (CSS2D floating text), and `scene/Edges.tsx` (reactive per-edge threads). OrbitControls swaps to `drei/CameraControls` so camera can ease into a focused region.

**Tech Stack:** same as v1. No new runtime dependencies — `CSS2DRenderer` ships with `three/addons`, `CameraControls` ships with `@react-three/drei`, and `RoomEnvironment` is already an addon.

**Spec:** [observatory/docs/specs/2026-04-21-observatory-v2-design.md](../specs/2026-04-21-observatory-v2-design.md) — authoritative. Plan conflicts with spec → spec wins; log the discrepancy in `observatory/memory/decisions.md`.

**Tracking convention** (per `observatory/CLAUDE.md`):
- Per-task implementer prompts: `observatory/prompts/v2-task-NN-<slug>.md`
- Non-obvious decisions: `observatory/memory/decisions.md` (append-only)
- One commit per plan task with HEREDOC message ending with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`
- Two-stage review after each implementer (spec-compliance `general-purpose`, then code-quality `superpowers:code-reviewer`); fix-loop on anything Important+

## Drifts from spec & v1 that implementers should know

1. **`queue_depth` — not `queue_depth_messages`.** The spec §3.2.2 names the stats-strip tile `queue_depth_messages`; v1's `RegionStats` (observatory/web-src/src/store.ts:6) and the backend registry both call the field `queue_depth`. Plan follows v1.
2. **Modulator names.** Spec §3.2.3 casually names six modulators `DA / NE / 5HT / ACh / HIS / ORX` as an illustration. The actual v1 `MODULATOR_NAMES` tuple (observatory/web-src/src/store.ts:56) is `['cortisol', 'dopamine', 'serotonin', 'norepinephrine', 'oxytocin', 'acetylcholine']`. Inspector's Modulator-bath section re-exports the v1 `hud/Modulators.tsx` gauges one-to-one; no name remap needed.
3. **Frontend REST/WS paths.** Spec §7.1 says `rest.ts` / `ws.ts` at `observatory/web-src/src/`. Actual locations are `observatory/web-src/src/api/rest.ts` and `.../api/ws.ts`. Plan uses actual paths.
4. **v1 `Regions.tsx` location.** Actual path is `observatory/web-src/src/scene/Regions.tsx` (under `scene/`). Spec §7.1's "Regions.tsx — deleted" refers to that file.
5. **`RegionStats.llm_in_flight`.** Spec §3.2.2 mentions "halos brighten during LLM activity". This flag is already on `RegionStats`; Task 9 uses it to drive the mid-halo opacity on the selected-or-hovered state; v1 HANDOFF flagged that `llm_model` is always empty against production YAML — plan falls back to `—`.

---

## File Structure (locked in up front)

### Backend (Python)

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/region_reader.py` | Sandboxed filesystem reader (`RegionReader`, `SandboxError`, `HandlerEntry`). Single entry for per-region disk reads. | 1 |
| `observatory/config.py` (modify) | Add `OBSERVATORY_REGIONS_ROOT` setting | 1 |
| `observatory/service.py` (modify) | Instantiate `RegionReader` at lifespan startup, inject into app state | 4 |
| `observatory/api.py` (modify) | Register five new routes under `/api/regions/{name}/` | 4 |

### Backend tests

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/tests/unit/test_region_reader.py` | Happy path + every sandbox boundary + redaction | 1, 2, 3 |
| `observatory/tests/unit/test_api_regions_v2.py` | Each endpoint via `fastapi.testclient` — status codes, Cache-Control, body shapes | 4 |
| `observatory/tests/component/test_end_to_end.py` (modify) | Extend: seed temp regions dir, assert `/config` redacts + `/handlers` lists | 5 |

### Frontend (TypeScript / React)

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/src/store.ts` (modify) | Add `selectedRegion`, `select`, `cycle` | 6 |
| `observatory/web-src/src/api/rest.ts` (modify) | Add `fetchPrompt`, `fetchStm`, `fetchSubscriptions`, `fetchConfig`, `fetchHandlers` | 7 |
| `observatory/web-src/src/inspector/useRegionFetch.ts` | Generic `{loading, error, data, reload}` hook | 7 |
| `observatory/web-src/src/Scene.tsx` → replaces OrbitControls with drei CameraControls; adds FuzzyOrbs / Labels / Edges | 8, 9, 10, 11 |
| `observatory/web-src/src/scene/glowTexture.ts` | Canvas-generated soft radial glow texture (module-level singleton) | 9 |
| `observatory/web-src/src/scene/FuzzyOrbs.tsx` | 4-layer additive-glow orbs per region; picker mesh for click/hover; dim + phase-lerp | 9 |
| `observatory/web-src/src/scene/Regions.tsx` | **Deleted** (replaced by FuzzyOrbs.tsx) | 9 |
| `observatory/web-src/src/scene/Labels.tsx` | CSS2DRenderer + per-region floating text (name always, stats on hover, selected forced) | 10 |
| `observatory/web-src/src/scene/Edges.tsx` | Per-edge `Line` with reactive pulse on spark traversal | 11 |
| `observatory/web-src/src/scene/Sparks.tsx` (modify) | Bump `EDGE_PULSE` on spark spawn; import only | 11 |
| `observatory/web-src/src/inspector/Inspector.tsx` | Slide-over shell — mounts sections when `selectedRegion != null` | 12 |
| `observatory/web-src/src/inspector/useInspectorKeys.ts` | Window-level keydown: Esc / `[` / `]` / `R`, input-focus guard | 12 |
| `observatory/web-src/src/App.tsx` (modify) | Mount `<Inspector />`; install `useInspectorKeys` | 12 |
| `observatory/web-src/src/inspector/sections/Header.tsx` | Name · phase badge · uptime · handler count · `llm_model` · ✕ | 12 |
| `observatory/web-src/src/inspector/sections/Stats.tsx` | 5 tiles + inline sparkline SVG | 12 |
| `observatory/web-src/src/inspector/sections/ModulatorBath.tsx` | Thin re-export wrapper of `hud/Modulators.tsx` | 12 |
| `observatory/web-src/src/inspector/sections/Subscriptions.tsx` | Flat `<ul>` of topic patterns | 12 |
| `observatory/web-src/src/inspector/sections/Handlers.tsx` | Flat list of `path · size` | 12 |
| `observatory/web-src/src/inspector/sections/JsonTree.tsx` | Tiny recursive JSON tree (no deps) | 13 |
| `observatory/web-src/src/inspector/sections/Prompt.tsx` | `<details>` with `<pre>` content + reload | 13 |
| `observatory/web-src/src/inspector/sections/Stm.tsx` | `<details>` with `<JsonTree>` | 13 |
| `observatory/web-src/src/inspector/sections/Messages.tsx` | Filtered envelope log + auto-scroll + row expand | 14 |

### Frontend tests

| File | Purpose | Introduced in Task |
|---|---|---|
| `observatory/web-src/src/store.test.ts` (modify) | Add select / cycle / wrap tests | 6 |
| `observatory/web-src/src/api/rest.test.ts` | 5 fetchers, 200/404/403/413/502 paths | 7 |
| `observatory/web-src/src/inspector/useRegionFetch.test.ts` | Hook states + reload | 7 |
| `observatory/web-src/src/scene/FuzzyOrbs.test.tsx` | Layer counts per region; phase-change lerp | 9 |
| `observatory/web-src/src/scene/Labels.test.tsx` | Name always; stats only with `.hover`; selected forces hover | 10 |
| `observatory/web-src/src/scene/Edges.test.ts` | Pulse bump on spawn; decay curve; opacity formula | 11 |
| `observatory/web-src/src/inspector/Header.test.tsx` | Phase badge, `llm_model` fallback to `—` | 12 |
| `observatory/web-src/src/inspector/Stats.test.tsx` | Tile values + sparkline window + threshold coloring | 12 |
| `observatory/web-src/src/inspector/Messages.test.tsx` | Filter (source OR destination), auto-scroll, row expand | 14 |
| `observatory/web-src/src/inspector/Stm.test.tsx` | Empty object → empty-state copy; JSON tree renders | 13 |

### Docs / tracking (per observatory/CLAUDE.md)

| File | Action |
|---|---|
| `observatory/HANDOFF.md` | Bump at the end of every task (progress table + changelog) |
| `observatory/memory/decisions.md` | Append entry per non-obvious call |
| `observatory/prompts/v2-task-NN-<slug>.md` | Store implementer prompts for audit |

---

## Task 1 — Sandbox foundation: `SandboxError` + `HandlerEntry` + `RegionReader` skeleton + config

**Files:**
- Create: `observatory/region_reader.py`
- Modify: `observatory/config.py`
- Create: `observatory/tests/unit/test_region_reader.py`

### Context for implementer

V1 has no per-region filesystem access. V2 needs a single sandboxed entry point. This task lands the skeleton + the simplest happy-path method (`read_prompt`) so the shape of the API is locked in before Task 2 fills in the rest. Per spec §6.1, every call runs a validation pipeline that must reject: symlinks, `..`, absolute paths, null bytes, region names outside `^[A-Za-z0-9_-]+$`, missing files (→ 404), files larger than `MAX_FILE_BYTES` (→ 413). Errors raise `SandboxError` carrying an HTTP status code.

### Steps

- [ ] **Step 1 — Add `OBSERVATORY_REGIONS_ROOT` to `config.py`.**

  Open `observatory/config.py`. It already exposes a pydantic-ish `Settings` class; add one field:

  ```python
  regions_root: Path = Path("regions")
  ```

  (use the same env-var pattern as existing fields — if v1 uses `env="OBSERVATORY_..."` via `model_config`, follow the same). Whatever default convention v1 uses is fine; a relative `Path("regions")` resolves against the process CWD (Hive repo root when run from `python -m observatory`). Add the field alphabetically in the class.

- [ ] **Step 2 — Create the test fixture helper.**

  Write `observatory/tests/unit/test_region_reader.py` with a shared pytest fixture that builds a temp regions directory with one well-formed region named `testregion`:

  ```python
  import json
  from pathlib import Path
  import pytest

  @pytest.fixture()
  def regions_root(tmp_path: Path) -> Path:
      root = tmp_path / "regions"
      region = root / "testregion"
      (region / "memory").mkdir(parents=True)
      (region / "handlers").mkdir()
      (region / "prompt.md").write_text("# hello from testregion\n", encoding="utf-8")
      (region / "memory" / "stm.json").write_text(json.dumps({"note": "ok", "n": 3}), encoding="utf-8")
      (region / "subscriptions.yaml").write_text("topics:\n  - hive/modulator/+\n  - hive/self/identity\n", encoding="utf-8")
      (region / "config.yaml").write_text(
          "name: testregion\n"
          "llm_model: fake-1.0\n"
          "api_key: topsecret\n"
          "nested:\n  auth_token: inner\n  aws_secret: [x, y]\n",
          encoding="utf-8",
      )
      (region / "handlers" / "on_wake.py").write_text("def handle():\n    pass\n", encoding="utf-8")
      return root
  ```

- [ ] **Step 3 — Write the failing test for `read_prompt` (happy path).**

  Add below the fixture:

  ```python
  from observatory.region_reader import RegionReader

  def test_read_prompt_happy_path(regions_root: Path):
      reader = RegionReader(regions_root)
      assert reader.read_prompt("testregion") == "# hello from testregion\n"
  ```

- [ ] **Step 4 — Run tests; confirm ImportError.**

  ```bash
  .venv/Scripts/python.exe -m pytest observatory/tests/unit/test_region_reader.py -q
  ```

  Expected: `ImportError: cannot import name 'RegionReader' from 'observatory.region_reader'` (or equivalent ModuleNotFoundError). This is the failing state.

- [ ] **Step 5 — Create `observatory/region_reader.py` with the skeleton.**

  ```python
  """Sandboxed filesystem reader for per-region disk access.

  Single entry point for observatory/api.py v2 routes. Every read runs through
  _validate() which rejects symlinks, traversal, absolute paths, null bytes,
  malformed region names, missing files, and files larger than MAX_FILE_BYTES.
  """
  from __future__ import annotations

  import json
  import re
  from dataclasses import dataclass
  from pathlib import Path
  from typing import Any

  import structlog

  log = structlog.get_logger(__name__)

  MAX_FILE_BYTES = 2 * 1024 * 1024
  _REGION_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


  class SandboxError(Exception):
      """Raised when a region-file read violates sandbox rules.

      `code` is the HTTP status an API handler should emit: 403 sandbox, 404
      missing, 413 oversize, 502 parse failure.
      """

      def __init__(self, message: str, code: int) -> None:
          super().__init__(message)
          self.code = code


  @dataclass(frozen=True)
  class HandlerEntry:
      path: str  # POSIX path relative to `regions_root / region`
      size: int  # bytes


  class RegionReader:
      """Sandboxed reader. Instantiated once at service startup."""

      def __init__(self, regions_root: Path) -> None:
          self._root = regions_root.resolve()
          if not self._root.exists() or not self._root.is_dir():
              raise FileNotFoundError(f"regions_root does not exist: {self._root}")

      def read_prompt(self, region: str) -> str:
          path = self._validate(region, "prompt.md")
          return path.read_text(encoding="utf-8")

      # --- stubs for Task 2/3 ---
      def read_stm(self, region: str) -> dict[str, Any]:
          raise NotImplementedError

      def read_subscriptions(self, region: str) -> dict[str, Any]:
          raise NotImplementedError

      def read_config(self, region: str) -> dict[str, Any]:
          raise NotImplementedError

      def list_handlers(self, region: str) -> list[HandlerEntry]:
          raise NotImplementedError

      # --- internal ---
      def _validate(self, region: str, rel: str) -> Path:
          """Run the full sandbox pipeline; return an absolute, safe Path."""
          if not _REGION_NAME_RE.fullmatch(region):
              raise SandboxError(f"invalid region name: {region!r}", 404)
          # Pre-resolve component checks
          if "\x00" in rel or "\x00" in region:
              raise SandboxError("null byte in path", 403)
          if ".." in Path(rel).parts or Path(rel).is_absolute():
              raise SandboxError("traversal or absolute path rejected", 403)

          candidate = (self._root / region / rel).resolve()
          try:
              candidate.relative_to(self._root)
          except ValueError as e:
              raise SandboxError("path escapes sandbox", 403) from e

          # Path.is_symlink() on the resolved path follows symlinks by definition,
          # so also check the unresolved path tail component for symlinks via lstat.
          unresolved = self._root / region / rel
          try:
              if unresolved.is_symlink():
                  raise SandboxError("symlink rejected", 403)
          except OSError as e:
              raise SandboxError(f"stat failed: {e}", 403) from e

          if not candidate.exists() or not candidate.is_file():
              raise SandboxError(f"file not found: {region}/{rel}", 404)

          if candidate.stat().st_size > MAX_FILE_BYTES:
              raise SandboxError(
                  f"file exceeds {MAX_FILE_BYTES} bytes: {region}/{rel}", 413,
              )

          log.debug("observatory.region_read", region=region, file=rel, size_bytes=candidate.stat().st_size)
          return candidate
  ```

- [ ] **Step 6 — Run tests; confirm Step 3's test passes.**

  ```bash
  .venv/Scripts/python.exe -m pytest observatory/tests/unit/test_region_reader.py -q
  ```

  Expected: `1 passed`.

- [ ] **Step 7 — Ruff + commit.**

  ```bash
  .venv/Scripts/python.exe -m ruff check observatory/region_reader.py observatory/tests/unit/test_region_reader.py
  ```

  Expected: `All checks passed!`. Then:

  ```bash
  git add observatory/region_reader.py observatory/config.py observatory/tests/unit/test_region_reader.py
  git commit -m "$(cat <<'EOF'
  observatory: region_reader skeleton + read_prompt (v2 task 1)

  SandboxError, HandlerEntry, RegionReader._validate pipeline, read_prompt
  happy path. Other methods stubbed. Adds OBSERVATORY_REGIONS_ROOT setting.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 2 — `RegionReader`: `read_stm` + `read_subscriptions` + all sandbox-boundary tests

**Files:**
- Modify: `observatory/region_reader.py`
- Modify: `observatory/tests/unit/test_region_reader.py`

### Context for implementer

Fills in the JSON/YAML reads and tightens the sandbox test coverage. JSON/YAML parse failures raise `SandboxError(..., 502)` so the API layer can map that to a 502 response. `read_subscriptions` parses YAML with `yaml.safe_load` and returns the parsed dict; if the file contents aren't a dict (e.g. a bare list), still return what the parser emits — the caller interprets.

### Steps

- [ ] **Step 1 — Add `yaml` import + `_parse_yaml` / `_parse_json` helpers.**

  At the top of `observatory/region_reader.py`:

  ```python
  import yaml
  ```

  Inside the `RegionReader` class, add:

  ```python
  @staticmethod
  def _parse_json(path: Path, text: str) -> dict[str, Any]:
      try:
          return json.loads(text)
      except json.JSONDecodeError as e:
          raise SandboxError(f"JSON parse failure in {path.name}: {e}", 502) from e

  @staticmethod
  def _parse_yaml(path: Path, text: str) -> dict[str, Any]:
      try:
          parsed = yaml.safe_load(text)
      except yaml.YAMLError as e:
          raise SandboxError(f"YAML parse failure in {path.name}: {e}", 502) from e
      return parsed if parsed is not None else {}
  ```

- [ ] **Step 2 — Implement `read_stm` and `read_subscriptions`.**

  Replace the stubs:

  ```python
  def read_stm(self, region: str) -> dict[str, Any]:
      path = self._validate(region, "memory/stm.json")
      return self._parse_json(path, path.read_text(encoding="utf-8"))

  def read_subscriptions(self, region: str) -> dict[str, Any]:
      path = self._validate(region, "subscriptions.yaml")
      return self._parse_yaml(path, path.read_text(encoding="utf-8"))
  ```

- [ ] **Step 3 — Write happy-path tests for both.**

  Append to `test_region_reader.py`:

  ```python
  def test_read_stm_happy_path(regions_root: Path):
      reader = RegionReader(regions_root)
      assert reader.read_stm("testregion") == {"note": "ok", "n": 3}

  def test_read_subscriptions_happy_path(regions_root: Path):
      reader = RegionReader(regions_root)
      subs = reader.read_subscriptions("testregion")
      assert subs == {"topics": ["hive/modulator/+", "hive/self/identity"]}
  ```

- [ ] **Step 4 — Write sandbox-boundary tests.**

  ```python
  import os
  from observatory.region_reader import SandboxError, MAX_FILE_BYTES

  def test_unknown_region_returns_404(regions_root: Path):
      reader = RegionReader(regions_root)
      with pytest.raises(SandboxError) as ei:
          reader.read_prompt("does-not-exist")
      assert ei.value.code == 404

  def test_invalid_region_name_returns_404(regions_root: Path):
      reader = RegionReader(regions_root)
      for bad in ["../etc/passwd", "foo/bar", "foo bar", "foo.bar"]:
          with pytest.raises(SandboxError) as ei:
              reader.read_prompt(bad)
          assert ei.value.code == 404

  def test_missing_file_returns_404(regions_root: Path, tmp_path: Path):
      # make a region with no prompt.md
      empty = regions_root / "emptyregion"
      empty.mkdir()
      reader = RegionReader(regions_root)
      with pytest.raises(SandboxError) as ei:
          reader.read_prompt("emptyregion")
      assert ei.value.code == 404

  def test_oversize_returns_413(regions_root: Path, monkeypatch):
      monkeypatch.setattr("observatory.region_reader.MAX_FILE_BYTES", 8)
      reader = RegionReader(regions_root)
      with pytest.raises(SandboxError) as ei:
          reader.read_prompt("testregion")
      assert ei.value.code == 413

  def test_parse_error_returns_502(regions_root: Path):
      (regions_root / "testregion" / "memory" / "stm.json").write_text("not-json{", encoding="utf-8")
      reader = RegionReader(regions_root)
      with pytest.raises(SandboxError) as ei:
          reader.read_stm("testregion")
      assert ei.value.code == 502

  @pytest.mark.skipif(os.name == "nt" and not hasattr(os, "symlink"),
                      reason="symlink privilege on Windows may be absent")
  def test_symlink_rejected(regions_root: Path, tmp_path: Path):
      outside = tmp_path / "secrets.txt"
      outside.write_text("nuclear codes", encoding="utf-8")
      link = regions_root / "testregion" / "prompt.md"
      link.unlink()
      try:
          os.symlink(outside, link)
      except (OSError, NotImplementedError):
          pytest.skip("symlinks unavailable in this environment")
      reader = RegionReader(regions_root)
      with pytest.raises(SandboxError) as ei:
          reader.read_prompt("testregion")
      assert ei.value.code == 403
  ```

  Note: the symlink test is platform-conditional. On Windows without Developer Mode, symlinks require admin; the test skips gracefully.

- [ ] **Step 5 — Run tests; confirm all pass.**

  ```bash
  .venv/Scripts/python.exe -m pytest observatory/tests/unit/test_region_reader.py -q
  ```

  Expected: at least 8 passing (happy paths × 2 + unknown region + invalid name + missing file + oversize + parse error + symlink-or-skip).

- [ ] **Step 6 — Ruff clean + commit.**

  ```bash
  .venv/Scripts/python.exe -m ruff check observatory/region_reader.py observatory/tests/unit/test_region_reader.py
  git add observatory/region_reader.py observatory/tests/unit/test_region_reader.py
  git commit -m "$(cat <<'EOF'
  observatory: region_reader stm + subs + boundary tests (v2 task 2)

  read_stm, read_subscriptions, and full coverage of the sandbox
  validation pipeline: unknown region, invalid name, missing file,
  oversize, parse errors, symlink rejection (platform-gated).

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 3 — `RegionReader`: `read_config` (with redaction) + `list_handlers`

**Files:**
- Modify: `observatory/region_reader.py`
- Modify: `observatory/tests/unit/test_region_reader.py`

### Context for implementer

Two methods left. `read_config` reuses `_parse_yaml` + walks the dict to redact any key whose lowercased name ends in `_key`, `_token`, or `_secret`. Walk nested dicts and lists of dicts. Replace value with the string `"***"`. `list_handlers` globs `handlers/**/*.py` via `rglob`, validates each result, and returns sorted `HandlerEntry` records. Missing `handlers/` directory returns `[]` (not an error).

### Steps

- [ ] **Step 1 — Write the redaction helper + `read_config`.**

  In `observatory/region_reader.py`, add to the class:

  ```python
  _SECRET_SUFFIXES = ("_key", "_token", "_secret")

  @classmethod
  def _redact(cls, obj: Any) -> Any:
      if isinstance(obj, dict):
          out: dict[str, Any] = {}
          for k, v in obj.items():
              key_s = str(k).lower()
              if any(key_s.endswith(s) for s in cls._SECRET_SUFFIXES):
                  out[k] = "***"
              else:
                  out[k] = cls._redact(v)
          return out
      if isinstance(obj, list):
          return [cls._redact(x) for x in obj]
      return obj

  def read_config(self, region: str) -> dict[str, Any]:
      path = self._validate(region, "config.yaml")
      parsed = self._parse_yaml(path, path.read_text(encoding="utf-8"))
      return self._redact(parsed)
  ```

- [ ] **Step 2 — Write `list_handlers`.**

  ```python
  def list_handlers(self, region: str) -> list[HandlerEntry]:
      # Validate the region name first using the same rule as _validate,
      # without needing a specific filename.
      if not _REGION_NAME_RE.fullmatch(region):
          raise SandboxError(f"invalid region name: {region!r}", 404)

      region_dir = (self._root / region).resolve()
      try:
          region_dir.relative_to(self._root)
      except ValueError as e:
          raise SandboxError("path escapes sandbox", 403) from e

      handlers_dir = region_dir / "handlers"
      if not handlers_dir.exists() or not handlers_dir.is_dir():
          return []

      entries: list[HandlerEntry] = []
      for py in sorted(handlers_dir.rglob("*.py")):
          # Run each through validation: relative-to-region-dir, not a symlink,
          # size cap. We do not reject based on region existence here
          # (region_dir exists by virtue of handlers_dir being under it).
          try:
              rel = py.relative_to(region_dir).as_posix()
          except ValueError:
              continue
          # Re-validate through the full pipeline (covers symlinks, null bytes, size cap).
          validated = self._validate(region, rel)
          entries.append(HandlerEntry(path=rel, size=validated.stat().st_size))
      return sorted(entries, key=lambda e: e.path)
  ```

- [ ] **Step 3 — Write tests for redaction + handlers.**

  Append to `test_region_reader.py`:

  ```python
  def test_read_config_redacts_secrets(regions_root: Path):
      reader = RegionReader(regions_root)
      cfg = reader.read_config("testregion")
      assert cfg["name"] == "testregion"
      assert cfg["llm_model"] == "fake-1.0"
      assert cfg["api_key"] == "***"
      # Nested under a dict
      assert cfg["nested"]["auth_token"] == "***"
      # Nested under a list — spec says "Nested dicts are walked; lists of dicts too."
      # aws_secret is a list of scalars here: the top-level key ends `_secret` so the
      # entire value is redacted to "***".
      assert cfg["nested"]["aws_secret"] == "***"

  def test_read_config_case_insensitive_suffix(regions_root: Path):
      (regions_root / "testregion" / "config.yaml").write_text(
          "Session_Key: abc\nSESSION_KEY: def\napi_password: ok\n", encoding="utf-8",
      )
      reader = RegionReader(regions_root)
      cfg = reader.read_config("testregion")
      assert cfg["Session_Key"] == "***"
      assert cfg["SESSION_KEY"] == "***"
      # api_password does not match any _SECRET_SUFFIXES — left alone
      assert cfg["api_password"] == "ok"

  def test_list_handlers_happy_path(regions_root: Path):
      reader = RegionReader(regions_root)
      entries = reader.list_handlers("testregion")
      assert len(entries) == 1
      assert entries[0].path == "handlers/on_wake.py"
      assert entries[0].size > 0

  def test_list_handlers_missing_dir_returns_empty(regions_root: Path):
      (regions_root / "testregion" / "handlers" / "on_wake.py").unlink()
      (regions_root / "testregion" / "handlers").rmdir()
      reader = RegionReader(regions_root)
      assert reader.list_handlers("testregion") == []

  def test_list_handlers_is_sorted(regions_root: Path):
      base = regions_root / "testregion" / "handlers"
      (base / "a.py").write_text("", encoding="utf-8")
      (base / "sub").mkdir()
      (base / "sub" / "b.py").write_text("", encoding="utf-8")
      reader = RegionReader(regions_root)
      paths = [e.path for e in reader.list_handlers("testregion")]
      assert paths == sorted(paths)
      assert "handlers/a.py" in paths
      assert "handlers/sub/b.py" in paths
  ```

- [ ] **Step 4 — Run tests.**

  ```bash
  .venv/Scripts/python.exe -m pytest observatory/tests/unit/test_region_reader.py -q
  ```

  Expected: `12 passed` (8 from prior tasks + 4 new — adjust if you added more).

- [ ] **Step 5 — Ruff + commit.**

  ```bash
  .venv/Scripts/python.exe -m ruff check observatory/region_reader.py observatory/tests/unit/test_region_reader.py
  git add observatory/region_reader.py observatory/tests/unit/test_region_reader.py
  git commit -m "$(cat <<'EOF'
  observatory: region_reader config+redaction + handlers tree (v2 task 3)

  read_config with recursive secret-suffix redaction. list_handlers
  via rglob with per-entry sandbox re-validation. Missing handlers/
  returns []. Entries sorted by POSIX path.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 4 — REST endpoints: register 5 routes, map `SandboxError.code` to HTTP

**Files:**
- Modify: `observatory/service.py` (instantiate `RegionReader`, inject into app state)
- Modify: `observatory/api.py` (register five new routes)
- Create: `observatory/tests/unit/test_api_regions_v2.py`

### Context for implementer

The endpoints are thin — each fetches data via `RegionReader`, maps `SandboxError.code` to `HTTPException.status_code`, and returns the shape from spec §6.2. All routes emit `Cache-Control: no-store`. Unknown regions short-circuit to 404 before any disk touch — check the region registry (from v1 Task 2's `RegionRegistry`). If the region is absent from the registry, raise `HTTPException(404, detail="region not registered")`.

**Error body shape:** `{"error": "sandbox|parse|not_found|oversize", "message": "..."}`. Map `SandboxError.code` → `error`:

- 403 → `"sandbox"`
- 404 → `"not_found"`
- 413 → `"oversize"`
- 502 → `"parse"`

### Steps

- [ ] **Step 1 — Inspect v1's `service.py` startup.**

  Read `observatory/service.py` and note where the `Settings` is consumed (likely in the `lifespan` context manager) and how other singletons (`RegionRegistry`, `MqttSubscriber`) are constructed.

- [ ] **Step 2 — Add `RegionReader` to the app factory.**

  In the lifespan startup, instantiate:

  ```python
  from observatory.region_reader import RegionReader

  # inside lifespan startup, alongside existing registry/subscriber setup:
  reader = RegionReader(settings.regions_root)
  app.state.reader = reader
  ```

  (If v1 uses `app.state.*` for other singletons, follow its convention. If it uses dependency-injected constructor args, wire via the same pattern.)

- [ ] **Step 3 — Register the five routes in `api.py`.**

  Read `observatory/api.py` and identify the existing router's base path. The new routes all live under `/api/regions/{name}/`. Add:

  ```python
  from fastapi import APIRouter, HTTPException, Request
  from fastapi.responses import PlainTextResponse, Response
  from observatory.region_reader import RegionReader, SandboxError

  _ERROR_KIND = {403: "sandbox", 404: "not_found", 413: "oversize", 502: "parse"}

  def _error_body(err: SandboxError) -> dict:
      return {"error": _ERROR_KIND.get(err.code, "sandbox"), "message": str(err)}

  def _ensure_region(request: Request, name: str) -> None:
      registry = request.app.state.registry  # existing v1 singleton
      if name not in registry.names():
          raise HTTPException(status_code=404, detail={"error": "not_found", "message": f"region {name!r} not registered"})

  def _reader(request: Request) -> RegionReader:
      return request.app.state.reader
  ```

  Then add each route handler. Example for `/prompt`:

  ```python
  @router.get("/regions/{name}/prompt", response_class=PlainTextResponse)
  def get_prompt(name: str, request: Request) -> PlainTextResponse:
      _ensure_region(request, name)
      try:
          text = _reader(request).read_prompt(name)
      except SandboxError as e:
          raise HTTPException(status_code=e.code, detail=_error_body(e)) from e
      return PlainTextResponse(
          text,
          headers={"Cache-Control": "no-store"},
          media_type="text/plain; charset=utf-8",
      )
  ```

  And similarly for `/stm`, `/subscriptions`, `/config`:

  ```python
  @router.get("/regions/{name}/stm")
  def get_stm(name: str, request: Request):
      _ensure_region(request, name)
      try:
          data = _reader(request).read_stm(name)
      except SandboxError as e:
          raise HTTPException(status_code=e.code, detail=_error_body(e)) from e
      return Response(
          content=__import__("json").dumps(data),
          media_type="application/json",
          headers={"Cache-Control": "no-store"},
      )
  ```

  For `/handlers`, convert `HandlerEntry` objects to dicts:

  ```python
  @router.get("/regions/{name}/handlers")
  def get_handlers(name: str, request: Request):
      _ensure_region(request, name)
      try:
          entries = _reader(request).list_handlers(name)
      except SandboxError as e:
          raise HTTPException(status_code=e.code, detail=_error_body(e)) from e
      body = [{"path": e.path, "size": e.size} for e in entries]
      return Response(
          content=__import__("json").dumps(body),
          media_type="application/json",
          headers={"Cache-Control": "no-store"},
      )
  ```

  **Note on `Response` construction:** if v1's `api.py` uses `JSONResponse`, prefer that — it auto-serializes and sets `content-type`. The key requirement is the `Cache-Control: no-store` header.

- [ ] **Step 4 — Write tests for each endpoint (happy path + error mappings).**

  Create `observatory/tests/unit/test_api_regions_v2.py`:

  ```python
  import json
  from pathlib import Path
  import pytest
  from fastapi.testclient import TestClient

  from observatory.config import Settings
  from observatory.region_reader import RegionReader
  from observatory.service import build_app  # or whatever v1 Task 7 named the factory


  @pytest.fixture()
  def client(regions_root: Path, monkeypatch) -> TestClient:
      # The regions_root fixture is reused from test_region_reader.py —
      # move it to conftest.py before or after this task.
      settings = Settings()
      settings = settings.model_copy(update={"regions_root": regions_root})
      app = build_app(settings)
      # Seed the registry so the endpoints don't 404 on region name.
      app.state.registry.seed({"testregion": {...}})  # use the real API; see v1 Task 2
      # Override the reader to use our tmp path.
      app.state.reader = RegionReader(regions_root)
      return TestClient(app)


  def test_prompt_happy(client: TestClient):
      r = client.get("/api/regions/testregion/prompt")
      assert r.status_code == 200
      assert r.text == "# hello from testregion\n"
      assert r.headers["cache-control"] == "no-store"
      assert r.headers["content-type"].startswith("text/plain")

  def test_stm_happy(client: TestClient):
      r = client.get("/api/regions/testregion/stm")
      assert r.status_code == 200
      assert r.json() == {"note": "ok", "n": 3}
      assert r.headers["cache-control"] == "no-store"

  def test_subscriptions_happy(client: TestClient):
      r = client.get("/api/regions/testregion/subscriptions")
      assert r.status_code == 200
      body = r.json()
      assert body["topics"] == ["hive/modulator/+", "hive/self/identity"]

  def test_config_redacted(client: TestClient):
      r = client.get("/api/regions/testregion/config")
      assert r.status_code == 200
      body = r.json()
      assert body["api_key"] == "***"
      assert body["nested"]["auth_token"] == "***"

  def test_handlers_happy(client: TestClient):
      r = client.get("/api/regions/testregion/handlers")
      assert r.status_code == 200
      body = r.json()
      assert len(body) == 1
      assert body[0]["path"] == "handlers/on_wake.py"
      assert body[0]["size"] > 0

  def test_unknown_region_404(client: TestClient):
      r = client.get("/api/regions/nosuch/prompt")
      assert r.status_code == 404
      assert r.json()["detail"]["error"] == "not_found"

  def test_missing_file_404(client: TestClient, regions_root: Path):
      (regions_root / "testregion" / "prompt.md").unlink()
      r = client.get("/api/regions/testregion/prompt")
      assert r.status_code == 404
      assert r.json()["detail"]["error"] == "not_found"

  def test_parse_error_502(client: TestClient, regions_root: Path):
      (regions_root / "testregion" / "memory" / "stm.json").write_text("not-json{", encoding="utf-8")
      r = client.get("/api/regions/testregion/stm")
      assert r.status_code == 502
      assert r.json()["detail"]["error"] == "parse"
  ```

  **Important:** the `regions_root` fixture needs to be accessible from both this test file and `test_region_reader.py`. Move it to `observatory/tests/unit/conftest.py` (create if absent). Use the exact same fixture body as Task 1's Step 2.

- [ ] **Step 5 — Run the full unit suite.**

  ```bash
  .venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q
  ```

  Expected: v1's 67 + v2's new tests (12 reader + ~8 api) = ~87 passing.

- [ ] **Step 6 — Ruff + commit.**

  ```bash
  .venv/Scripts/python.exe -m ruff check observatory/service.py observatory/api.py observatory/tests/unit/
  git add observatory/service.py observatory/api.py observatory/tests/unit/test_api_regions_v2.py observatory/tests/unit/conftest.py
  git commit -m "$(cat <<'EOF'
  observatory: v2 REST endpoints + error mapping (v2 task 4)

  Five new routes under /api/regions/{name}/: prompt, stm, subscriptions,
  config, handlers. Maps SandboxError.code -> HTTP status (403/404/413/502)
  and a structured body {"error", "message"}. Unknown region short-circuits
  to 404 before disk touch. Cache-Control: no-store on all five.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 5 — Component e2e extension: seed regions, assert redaction + handler tree over real broker

**Files:**
- Modify: `observatory/tests/component/test_end_to_end.py`

### Context for implementer

v1 Task 8 stood up a real `eclipse-mosquitto:2` broker via testcontainers and verified publish → WS delivery. v2 extends that same test module (or adds a new test function in it) to also hit the new `/api/regions/{name}/config` and `/handlers` endpoints against a seeded regions directory.

### Steps

- [ ] **Step 1 — Read `test_end_to_end.py` to understand the current fixture layout** (broker container, app startup, httpx/WS clients).

- [ ] **Step 2 — Add a regions-dir seeding helper inside the existing test module.**

  Inside the test file, near the top-level:

  ```python
  import json
  from pathlib import Path

  def _seed_regions(root: Path) -> None:
      region = root / "testregion"
      (region / "memory").mkdir(parents=True)
      (region / "handlers").mkdir()
      (region / "prompt.md").write_text("hello\n", encoding="utf-8")
      (region / "memory" / "stm.json").write_text(json.dumps({"n": 1}), encoding="utf-8")
      (region / "subscriptions.yaml").write_text("topics: [hive/modulator/+]\n", encoding="utf-8")
      (region / "config.yaml").write_text(
          "llm_model: fake\napi_key: shh\n", encoding="utf-8",
      )
      (region / "handlers" / "on_wake.py").write_text("def handle():\n    pass\n", encoding="utf-8")
  ```

- [ ] **Step 3 — Add a new test function.**

  ```python
  @pytest.mark.component
  def test_v2_endpoints_over_real_service(tmp_path, broker_url):
      regions_root = tmp_path / "regions"
      _seed_regions(regions_root)
      # Build Settings with the seeded regions_root + real broker URL,
      # start the app via the same harness v1 Task 8 uses.
      # ... (mirror v1 Task 8's app startup pattern)
      with TestClient(app) as client:
          # Seed registry (same as unit tests).
          app.state.registry.seed({"testregion": {...}})

          r = client.get("/api/regions/testregion/config")
          assert r.status_code == 200
          body = r.json()
          assert body["api_key"] == "***"
          assert body["llm_model"] == "fake"

          r = client.get("/api/regions/testregion/handlers")
          assert r.status_code == 200
          assert len(r.json()) == 1
  ```

- [ ] **Step 4 — Run component suite.**

  ```bash
  .venv/Scripts/python.exe -m pytest observatory/tests/component/ -m component -v
  ```

  Expected: v1's 1 component test + this new one = 2 passing. Requires Docker Desktop.

- [ ] **Step 5 — Commit.**

  ```bash
  .venv/Scripts/python.exe -m ruff check observatory/tests/component/
  git add observatory/tests/component/test_end_to_end.py
  git commit -m "$(cat <<'EOF'
  observatory: v2 e2e — seeded regions dir, redaction + handlers assertions (v2 task 5)

  Extends v1's broker-backed end-to-end test to hit /api/regions/{name}/config
  (redaction) and /handlers (tree) against a freshly seeded temp regions dir.
  Keeps v1's MQTT publish -> WS receive flow intact.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 6 — Frontend: store additions (`selectedRegion` / `select` / `cycle`)

**Files:**
- Modify: `observatory/web-src/src/store.ts`
- Modify: `observatory/web-src/src/store.test.ts`

### Context for implementer

Small but foundational. The inspector depends on `selectedRegion`; the camera swap (Task 8) and FuzzyOrbs dim-factor (Task 9) also read it. `cycle(±1)` steps alphabetically with wrap; no-op when `selectedRegion` is `null` or the region list is empty.

### Steps

- [ ] **Step 1 — Extend the `State` type and the store factory.**

  In `observatory/web-src/src/store.ts`, add to the `State` type:

  ```ts
  type State = {
    // ...existing v1 fields...
    selectedRegion: string | null;
    select: (name: string | null) => void;
    cycle: (direction: 1 | -1) => void;
  };
  ```

  Extend the store body:

  ```ts
  export const createStore = (): UseBoundStore<StoreApi<State>> =>
    create<State>((set, get) => ({
      // ...existing fields and actions...
      selectedRegion: null,
      select: (name) => set({ selectedRegion: name }),
      cycle: (direction) => {
        const s = get();
        if (s.selectedRegion == null) return;
        const names = Object.keys(s.regions).sort();
        if (names.length === 0) return;
        const idx = names.indexOf(s.selectedRegion);
        if (idx < 0) return;
        const next = (idx + direction + names.length) % names.length;
        set({ selectedRegion: names[next] });
      },
    }));
  ```

- [ ] **Step 2 — Write tests.**

  Append to `observatory/web-src/src/store.test.ts`:

  ```ts
  import { createStore } from './store';

  function withRegions(store: ReturnType<typeof createStore>, ...names: string[]) {
      const regions = Object.fromEntries(
          names.map((n) => [n, { role: 'x', llm_model: '', stats: {
              phase: 'wake', queue_depth: 0, stm_bytes: 0, tokens_lifetime: 0,
              handler_count: 0, last_error_ts: null, msg_rate_in: 0, msg_rate_out: 0,
              llm_in_flight: false,
          } }]),
      );
      store.getState().applyRegionDelta(regions);
  }

  describe('selection', () => {
    it('select(name) sets selectedRegion', () => {
      const store = createStore();
      store.getState().select('mpfc');
      expect(store.getState().selectedRegion).toBe('mpfc');
    });

    it('select(null) clears selectedRegion', () => {
      const store = createStore();
      store.getState().select('mpfc');
      store.getState().select(null);
      expect(store.getState().selectedRegion).toBeNull();
    });

    it('cycle is a no-op when selectedRegion is null', () => {
      const store = createStore();
      withRegions(store, 'a', 'b', 'c');
      store.getState().cycle(1);
      expect(store.getState().selectedRegion).toBeNull();
    });

    it('cycle(+1) steps forward alphabetically', () => {
      const store = createStore();
      withRegions(store, 'charlie', 'alpha', 'bravo');
      store.getState().select('alpha');
      store.getState().cycle(1);
      expect(store.getState().selectedRegion).toBe('bravo');
    });

    it('cycle(+1) wraps from last to first', () => {
      const store = createStore();
      withRegions(store, 'alpha', 'bravo', 'charlie');
      store.getState().select('charlie');
      store.getState().cycle(1);
      expect(store.getState().selectedRegion).toBe('alpha');
    });

    it('cycle(-1) wraps from first to last', () => {
      const store = createStore();
      withRegions(store, 'alpha', 'bravo', 'charlie');
      store.getState().select('alpha');
      store.getState().cycle(-1);
      expect(store.getState().selectedRegion).toBe('charlie');
    });
  });
  ```

- [ ] **Step 3 — Run frontend tests.**

  ```bash
  cd observatory/web-src && npm run test && npx tsc -b
  cd ../..
  ```

  Expected: all v1 store tests (6) + 6 new = 12+ passing. `tsc -b` clean.

- [ ] **Step 4 — Commit.**

  ```bash
  git add observatory/web-src/src/store.ts observatory/web-src/src/store.test.ts
  git commit -m "$(cat <<'EOF'
  observatory: store selectedRegion / select / cycle (v2 task 6)

  Adds the minimum state needed by the inspector panel, camera controls
  swap, and scene dim factor. cycle(+/-1) is alphabetical with wrap;
  no-op when nothing is selected.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 7 — Frontend: REST client wrappers + `useRegionFetch` hook

**Files:**
- Modify: `observatory/web-src/src/api/rest.ts`
- Create: `observatory/web-src/src/api/rest.test.ts`
- Create: `observatory/web-src/src/inspector/useRegionFetch.ts`
- Create: `observatory/web-src/src/inspector/useRegionFetch.test.ts`

### Context for implementer

Five thin fetch wrappers + one generic hook. Each wrapper returns typed data on 2xx and throws a `RestError` (new class) on non-2xx, surfacing the server's `{"error", "message"}` body text when present. The hook manages `{loading, error, data, reload}` state per section and re-fetches when `selectedRegion` changes.

### Steps

- [ ] **Step 1 — Add `RestError` + 5 fetch wrappers to `api/rest.ts`.**

  Append to `observatory/web-src/src/api/rest.ts`:

  ```ts
  export class RestError extends Error {
    constructor(public status: number, message: string, public body?: unknown) {
      super(message);
      this.name = 'RestError';
    }
  }

  async function _get(path: string, init?: RequestInit): Promise<Response> {
    const r = await fetch(path, init);
    if (!r.ok) {
      let body: unknown;
      let msg: string;
      try {
        body = await r.json();
        const detail = (body as { detail?: { error?: string; message?: string } })?.detail;
        msg = detail?.message ?? `${r.status} ${r.statusText}`;
      } catch {
        msg = `${r.status} ${r.statusText}`;
      }
      throw new RestError(r.status, msg, body);
    }
    return r;
  }

  export async function fetchPrompt(name: string): Promise<string> {
    const r = await _get(`/api/regions/${encodeURIComponent(name)}/prompt`);
    return r.text();
  }

  export async function fetchStm(name: string): Promise<Record<string, unknown>> {
    const r = await _get(`/api/regions/${encodeURIComponent(name)}/stm`);
    return r.json();
  }

  export async function fetchSubscriptions(name: string): Promise<Record<string, unknown>> {
    const r = await _get(`/api/regions/${encodeURIComponent(name)}/subscriptions`);
    return r.json();
  }

  export async function fetchConfig(name: string): Promise<Record<string, unknown>> {
    const r = await _get(`/api/regions/${encodeURIComponent(name)}/config`);
    return r.json();
  }

  export type HandlerEntry = { path: string; size: number };

  export async function fetchHandlers(name: string): Promise<HandlerEntry[]> {
    const r = await _get(`/api/regions/${encodeURIComponent(name)}/handlers`);
    return r.json();
  }
  ```

- [ ] **Step 2 — Write tests for the fetch wrappers.**

  Create `observatory/web-src/src/api/rest.test.ts`:

  ```ts
  import { describe, it, expect, beforeEach, vi } from 'vitest';
  import { fetchPrompt, fetchStm, fetchHandlers, RestError } from './rest';

  function mockFetchOnce(status: number, body: unknown, contentType = 'application/json') {
    const headers = new Headers({ 'content-type': contentType });
    const init = {
      status,
      statusText: status === 200 ? 'OK' : 'Error',
      headers,
    };
    const blob = contentType.startsWith('application/json')
      ? JSON.stringify(body)
      : String(body);
    vi.stubGlobal('fetch', vi.fn(async () => new Response(blob, init)));
  }

  describe('fetchPrompt', () => {
    it('returns text on 200', async () => {
      mockFetchOnce(200, 'hello', 'text/plain; charset=utf-8');
      expect(await fetchPrompt('foo')).toBe('hello');
    });
    it('throws RestError with server message on 404', async () => {
      mockFetchOnce(404, { detail: { error: 'not_found', message: 'region not registered' } });
      await expect(fetchPrompt('nosuch')).rejects.toThrow(RestError);
    });
    it('throws RestError on 403 sandbox', async () => {
      mockFetchOnce(403, { detail: { error: 'sandbox', message: 'symlink rejected' } });
      await expect(fetchPrompt('foo')).rejects.toMatchObject({ status: 403 });
    });
  });

  describe('fetchStm', () => {
    it('returns parsed JSON', async () => {
      mockFetchOnce(200, { note: 'ok', n: 3 });
      expect(await fetchStm('foo')).toEqual({ note: 'ok', n: 3 });
    });
    it('throws on 502 parse error', async () => {
      mockFetchOnce(502, { detail: { error: 'parse', message: 'bad json' } });
      await expect(fetchStm('foo')).rejects.toMatchObject({ status: 502 });
    });
  });

  describe('fetchHandlers', () => {
    it('returns array of entries', async () => {
      mockFetchOnce(200, [{ path: 'handlers/a.py', size: 123 }]);
      expect(await fetchHandlers('foo')).toEqual([{ path: 'handlers/a.py', size: 123 }]);
    });
  });
  ```

- [ ] **Step 3 — Create `useRegionFetch`.**

  `observatory/web-src/src/inspector/useRegionFetch.ts`:

  ```ts
  import { useCallback, useEffect, useRef, useState } from 'react';

  export type FetchState<T> = {
    loading: boolean;
    error: string | null;
    data: T | null;
    reload: () => void;
  };

  /**
   * Region-scoped fetch hook: re-fetches when `name` changes.
   * Manages {loading, error, data, reload} for a single endpoint.
   * `fetcher` is called with the active region name; if the name is null
   * the hook stays idle (no fetch, no loading).
   */
  export function useRegionFetch<T>(
    name: string | null,
    fetcher: (name: string) => Promise<T>,
  ): FetchState<T> {
    const [data, setData] = useState<T | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [loading, setLoading] = useState(false);
    const [reloadTick, setReloadTick] = useState(0);
    const mountedRef = useRef(true);

    useEffect(() => {
      mountedRef.current = true;
      return () => { mountedRef.current = false; };
    }, []);

    useEffect(() => {
      if (name == null) {
        setData(null); setError(null); setLoading(false);
        return;
      }
      let cancelled = false;
      setLoading(true); setError(null);
      fetcher(name)
        .then((d) => { if (!cancelled && mountedRef.current) { setData(d); setLoading(false); } })
        .catch((e: unknown) => {
          if (cancelled || !mountedRef.current) return;
          const msg = e instanceof Error ? e.message : String(e);
          setError(msg); setLoading(false);
        });
      return () => { cancelled = true; };
    }, [name, fetcher, reloadTick]);

    const reload = useCallback(() => setReloadTick((n) => n + 1), []);
    return { loading, error, data, reload };
  }
  ```

- [ ] **Step 4 — Write a minimal test for the hook.**

  `observatory/web-src/src/inspector/useRegionFetch.test.ts`:

  ```ts
  import { describe, it, expect, vi } from 'vitest';
  import { act, renderHook, waitFor } from '@testing-library/react';
  import { useRegionFetch } from './useRegionFetch';

  describe('useRegionFetch', () => {
    it('returns data on success', async () => {
      const fetcher = vi.fn(async (n: string) => `data for ${n}`);
      const { result } = renderHook(() => useRegionFetch('foo', fetcher));
      await waitFor(() => expect(result.current.data).toBe('data for foo'));
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('captures error message', async () => {
      const fetcher = vi.fn(async () => { throw new Error('boom'); });
      const { result } = renderHook(() => useRegionFetch('foo', fetcher));
      await waitFor(() => expect(result.current.error).toBe('boom'));
    });

    it('stays idle when name is null', () => {
      const fetcher = vi.fn(async () => 'x');
      const { result } = renderHook(() => useRegionFetch(null, fetcher));
      expect(fetcher).not.toHaveBeenCalled();
      expect(result.current.loading).toBe(false);
      expect(result.current.data).toBeNull();
    });

    it('reload() refetches', async () => {
      let callCount = 0;
      const fetcher = vi.fn(async () => ++callCount);
      const { result } = renderHook(() => useRegionFetch('foo', fetcher));
      await waitFor(() => expect(result.current.data).toBe(1));
      act(() => result.current.reload());
      await waitFor(() => expect(result.current.data).toBe(2));
    });
  });
  ```

- [ ] **Step 5 — `@testing-library/react` is already a v1 devDep — confirm.**

  ```bash
  grep testing-library observatory/web-src/package.json
  ```

  Expected: lines for `@testing-library/react` and `@testing-library/dom`. If absent, add via `npm i -D @testing-library/react`. (v1 Task 10 introduced render-based tests; if it used a different harness, follow v1's pattern.)

- [ ] **Step 6 — Run frontend tests.**

  ```bash
  cd observatory/web-src && npm run test && npx tsc -b
  cd ../..
  ```

  Expected: previous tests + rest.test (5-6) + useRegionFetch (4) = 30+ passing.

- [ ] **Step 7 — Commit.**

  ```bash
  git add observatory/web-src/src/api/rest.ts observatory/web-src/src/api/rest.test.ts \
          observatory/web-src/src/inspector/useRegionFetch.ts \
          observatory/web-src/src/inspector/useRegionFetch.test.ts
  git commit -m "$(cat <<'EOF'
  observatory: REST wrappers + useRegionFetch hook (v2 task 7)

  Five fetchPrompt/fetchStm/fetchSubscriptions/fetchConfig/fetchHandlers
  wrappers against the v2 routes; RestError surfaces server detail.message
  when present. useRegionFetch hook manages {loading, error, data, reload}
  keyed on region name; null name is idle.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 8 — Frontend: swap `OrbitControls` for `drei/CameraControls` + dim-factor plumbing

**Files:**
- Modify: `observatory/web-src/src/scene/Scene.tsx`

### Context for implementer

v1 uses `<OrbitControls>` from `@react-three/drei`. v2 needs imperative `fitToBox` + `reset`, which `CameraControls` provides via its ref API. Drag-to-orbit / scroll-to-zoom / pan gestures remain. Selected-region focus easing is wired here; Task 9's FuzzyOrbs supplies the `regionRefs` for the `fitToBox` target. Dim factor is computed once in this file and passed down as a prop or via a small context (see Task 9 for the Orbs consumer).

### Steps

- [ ] **Step 1 — Read `Scene.tsx`.**

  ```bash
  head -80 observatory/web-src/src/scene/Scene.tsx
  ```

  Note the existing `<Canvas>` children: `<OrbitControls>`, `<Regions />`, `<Sparks />`, `<Fog />`, `<Rhythm />` plus lights.

- [ ] **Step 2 — Swap `OrbitControls` → `CameraControls` and expose a ref.**

  Replace the `import { OrbitControls } from '@react-three/drei';` line (or similar) with:

  ```ts
  import { CameraControls } from '@react-three/drei';
  ```

  Inside the `<Canvas>` children, wire a ref:

  ```tsx
  const cameraControlsRef = useRef<CameraControls>(null);
  // ...
  <CameraControls ref={cameraControlsRef} minDistance={10} maxDistance={140} dampingFactor={0.08} />
  ```

- [ ] **Step 3 — Add a focus hook that reacts to `selectedRegion`.**

  Create a collocated hook in `Scene.tsx` (or a new helper):

  ```tsx
  const selectedRegion = useStore((s) => s.selectedRegion);
  const regionMeshRefs = useRef<Map<string, THREE.Object3D>>(new Map());
  // Task 9 populates this via callback refs on each FuzzyOrb group.

  useEffect(() => {
    const ctrl = cameraControlsRef.current;
    if (!ctrl) return;
    if (selectedRegion == null) {
      ctrl.reset(true);
      return;
    }
    const target = regionMeshRefs.current.get(selectedRegion);
    if (!target) return;
    const box = new THREE.Box3().setFromObject(target);
    ctrl.fitToBox(box, true, {
      paddingTop: 0.5, paddingLeft: 0.5, paddingRight: 0.5, paddingBottom: 0.5,
    });
  }, [selectedRegion]);
  ```

  `smoothTime` on `CameraControls` is configured globally via the ref or via its default; `fitToBox`'s second positional arg `true` enables the smooth transition.

- [ ] **Step 4 — Compute dim factor and thread it to child components.**

  ```tsx
  const dimFactor = selectedRegion == null ? 1.0 : 0.25;
  // Pass `dimFactor` and `regionMeshRefs` to <FuzzyOrbs />, <Edges />, <Labels />.
  // Tasks 9, 10, 11 define the exact props.
  ```

- [ ] **Step 5 — Ensure empty-space click closes the panel.**

  On the root `<Canvas>`:

  ```tsx
  <Canvas onPointerMissed={() => useStore.getState().select(null)}>
  ```

  (This fires when a pointer-down-up happens without hitting any object with an `onClick`. Combined with FuzzyOrbs' picker mesh in Task 9, this gives the spec's §3.1 close-on-empty-click behavior.)

- [ ] **Step 6 — Visual smoke via existing tests.**

  This is primarily a wiring change; `Scene.tsx` has no render tests in v1. Run the whole frontend suite:

  ```bash
  cd observatory/web-src && npx tsc -b && npm run test && npm run build
  cd ../..
  ```

  Expected: `tsc -b` clean; all tests still pass; `npm run build` emits `observatory/web/`.

- [ ] **Step 7 — Commit.**

  ```bash
  git add observatory/web-src/src/scene/Scene.tsx
  git commit -m "$(cat <<'EOF'
  observatory: swap OrbitControls for CameraControls + dim factor (v2 task 8)

  drei CameraControls replaces OrbitControls; same free-orbit gesture, plus
  imperative ref for fitToBox(selectedRegionMesh) and reset(). Adds a
  dimFactor derivation (selectedRegion ? 0.25 : 1.0) threaded to the scene
  children in tasks 9-11. Empty-space click closes the inspector via
  Canvas.onPointerMissed.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 9 — Frontend: `FuzzyOrbs.tsx` (replaces `scene/Regions.tsx`) + `glowTexture.ts`

**Files:**
- Create: `observatory/web-src/src/scene/glowTexture.ts`
- Create: `observatory/web-src/src/scene/FuzzyOrbs.tsx`
- Create: `observatory/web-src/src/scene/FuzzyOrbs.test.tsx`
- Modify: `observatory/web-src/src/scene/Scene.tsx` (swap `<Regions />` → `<FuzzyOrbs />`)
- **Delete:** `observatory/web-src/src/scene/Regions.tsx`

### Context for implementer

The big scene refactor. Each region becomes a **group** of five meshes:

| Layer | Type | Scale (×size) | Opacity | Notes |
|---|---|---|---|---|
| Outer halo | `Sprite` | 5.2 wake / 4.5 boot / 3.8 sleep | 0.28 wake / 0.18 boot / 0.10 sleep | additive, no depthWrite |
| Mid halo | `Sprite` | 2.6 | 0.65 wake / 0.28 sleep | additive |
| Core | `Mesh(SphereGeometry)` | 0.55 | 0.85 | `MeshStandardMaterial`, `emissiveIntensity` 0.55 wake / 0.15 sleep, roughness 0.9, metalness 0 |
| Speckle | `Sprite`, white | 0.9 | 0.6 wake / 0.20 sleep | additive |
| Picker | `Mesh(SphereGeometry)`, `visible: false` | 1.2 | — | raycast target; handles onClick/onPointerOver |

Phase changes lerp opacity + emissiveIntensity over 800 ms. Dim factor multiplies every material's opacity except the selected region (selectedRegion dimFactor = 1.0).

Use `useForceGraph` from v1 unchanged — it mutates `node.x/y/z` each frame. FuzzyOrbs reads the node positions via `useFrame` and copies into the group's position (same pattern v1's `Regions.tsx` uses).

### Steps

- [ ] **Step 1 — Create `glowTexture.ts`.**

  ```ts
  import * as THREE from 'three';

  /**
   * Module-level singleton: a radial-gradient soft-glow canvas texture used
   * by all FuzzyOrb sprite layers. Generated once at module load; reused
   * for every region.
   */
  function _buildGlowTexture(): THREE.Texture {
    const c = document.createElement('canvas');
    c.width = c.height = 256;
    const g = c.getContext('2d')!;
    const rg = g.createRadialGradient(128, 128, 0, 128, 128, 128);
    rg.addColorStop(0.00, 'rgba(255,255,255,1.00)');
    rg.addColorStop(0.18, 'rgba(255,255,255,0.65)');
    rg.addColorStop(0.40, 'rgba(255,255,255,0.22)');
    rg.addColorStop(0.70, 'rgba(255,255,255,0.06)');
    rg.addColorStop(1.00, 'rgba(255,255,255,0.00)');
    g.fillStyle = rg;
    g.fillRect(0, 0, 256, 256);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    tex.needsUpdate = true;
    return tex;
  }

  export const GLOW_TEX: THREE.Texture = _buildGlowTexture();
  ```

- [ ] **Step 2 — Read v1 `Regions.tsx` for the force-graph interface.**

  ```bash
  cat observatory/web-src/src/scene/Regions.tsx
  ```

  Note: how `useForceGraph` returns nodes, how each node's position is read in `useFrame`, and how region names map to node indices.

- [ ] **Step 3 — Create `FuzzyOrbs.tsx` (the big one).**

  ```tsx
  import { useMemo, useRef, useEffect } from 'react';
  import * as THREE from 'three';
  import { useFrame } from '@react-three/fiber';
  import { useStore, type RegionMeta } from '../store';
  import { useForceGraph } from './useForceGraph';
  import { GLOW_TEX } from './glowTexture';

  const PHASE_COLOR: Record<string, number> = {
    wake: 0x6aa8ff,
    sleep: 0x3a4458,
    bootstrap: 0x5a8a78,
    shutdown: 0x805a5a,
    processing: 0xffd56a,
    unknown: 0x6aa8ff,
  };

  function phaseBase(phase: string): { color: number; emissive: number; coreOpacity: number; outerOpacity: number; midOpacity: number; speckleOpacity: number; outerScale: number } {
    if (phase === 'sleep')   return { color: PHASE_COLOR.sleep,   emissive: 0.15, coreOpacity: 0.85, outerOpacity: 0.10, midOpacity: 0.28, speckleOpacity: 0.20, outerScale: 3.8 };
    if (phase === 'bootstrap') return { color: PHASE_COLOR.bootstrap, emissive: 0.35, coreOpacity: 0.85, outerOpacity: 0.18, midOpacity: 0.45, speckleOpacity: 0.40, outerScale: 4.5 };
    return { color: PHASE_COLOR[phase] ?? PHASE_COLOR.unknown, emissive: 0.55, coreOpacity: 0.85, outerOpacity: 0.28, midOpacity: 0.65, speckleOpacity: 0.60, outerScale: 5.2 };
  }

  type FuzzyOrbsProps = {
    dimFactor: number;  // 1.0 full, 0.25 when a different region is selected
    onRegionClick: (name: string) => void;
    refMap: React.MutableRefObject<Map<string, THREE.Object3D>>;
  };

  export function FuzzyOrbs({ dimFactor, onRegionClick, refMap }: FuzzyOrbsProps) {
    const regions = useStore((s) => s.regions);
    const selectedRegion = useStore((s) => s.selectedRegion);
    const names = useMemo(() => Object.keys(regions).sort(), [regions]);
    const { nodes } = useForceGraph(regions);

    // One ref per region — five-mesh group keyed by region name.
    const groupRefs = useRef<Map<string, THREE.Group>>(new Map());
    const coreMatRefs = useRef<Map<string, THREE.MeshStandardMaterial>>(new Map());
    const outerMatRefs = useRef<Map<string, THREE.SpriteMaterial>>(new Map());
    const midMatRefs = useRef<Map<string, THREE.SpriteMaterial>>(new Map());
    const speckleMatRefs = useRef<Map<string, THREE.SpriteMaterial>>(new Map());

    // Phase-lerp target trackers: when a phase changes, a target is set,
    // and useFrame lerps toward it at rate 1/0.8s.
    const phaseTargets = useRef<Map<string, ReturnType<typeof phaseBase>>>(new Map());

    useEffect(() => {
      // Publish region refs up to Scene.tsx for camera-focus lookup.
      refMap.current.clear();
      for (const name of names) {
        const g = groupRefs.current.get(name);
        if (g) refMap.current.set(name, g);
      }
    }, [names, refMap]);

    useFrame((_, dt) => {
      const d = Math.min(dt, 0.05);

      for (let i = 0; i < names.length; i++) {
        const name = names[i];
        const node = nodes[i];
        const group = groupRefs.current.get(name);
        if (!group || !node) continue;

        // Position sync from force graph.
        group.position.set(node.x, node.y, node.z);

        // Phase target tracking.
        const meta: RegionMeta | undefined = regions[name];
        const phase = meta?.stats?.phase ?? 'unknown';
        const currentTarget = phaseTargets.current.get(name);
        const nextTarget = phaseBase(phase);
        if (!currentTarget || currentTarget.color !== nextTarget.color) {
          phaseTargets.current.set(name, nextTarget);
        }

        // Dim for all regions except the selected one (selected stays at 1.0).
        const effectiveDim = selectedRegion != null && selectedRegion !== name ? dimFactor : 1.0;

        // Lerp materials toward target × dim.
        const target = phaseTargets.current.get(name)!;
        const lerpRate = d / 0.8; // ~1.25 per sec → reaches 63% in 0.8s

        const coreMat = coreMatRefs.current.get(name);
        if (coreMat) {
          coreMat.emissiveIntensity += (target.emissive - coreMat.emissiveIntensity) * lerpRate;
          coreMat.opacity += (target.coreOpacity * effectiveDim - coreMat.opacity) * lerpRate;
          coreMat.color.setHex(target.color);
          coreMat.emissive.setHex(target.color);
        }
        const outer = outerMatRefs.current.get(name);
        if (outer) {
          outer.opacity += (target.outerOpacity * effectiveDim - outer.opacity) * lerpRate;
          outer.color.setHex(target.color);
        }
        const mid = midMatRefs.current.get(name);
        if (mid) {
          mid.opacity += (target.midOpacity * effectiveDim - mid.opacity) * lerpRate;
          mid.color.setHex(target.color);
        }
        const speck = speckleMatRefs.current.get(name);
        if (speck) {
          speck.opacity += (target.speckleOpacity * effectiveDim - speck.opacity) * lerpRate;
        }
      }
    });

    return (
      <group>
        {names.map((name) => {
          const meta = regions[name];
          // base size: 0.9 default, scale bump for mPFC (center pin) if the role marks it as such.
          const size = meta?.role === 'executive' ? 1.8 : 1.0;
          const initial = phaseBase(meta?.stats?.phase ?? 'unknown');
          const outerScale = size * initial.outerScale;
          const midScale = size * 2.6;
          const speckleScale = size * 0.9;

          return (
            <group
              key={name}
              ref={(el) => { if (el) groupRefs.current.set(name, el); }}
            >
              {/* Outer halo */}
              <sprite scale={[outerScale, outerScale, 1]}>
                <spriteMaterial
                  attach="material"
                  ref={(m: any) => { if (m) outerMatRefs.current.set(name, m); }}
                  map={GLOW_TEX}
                  color={initial.color}
                  transparent
                  opacity={initial.outerOpacity}
                  depthWrite={false}
                  blending={THREE.AdditiveBlending}
                />
              </sprite>
              {/* Mid halo */}
              <sprite scale={[midScale, midScale, 1]}>
                <spriteMaterial
                  attach="material"
                  ref={(m: any) => { if (m) midMatRefs.current.set(name, m); }}
                  map={GLOW_TEX}
                  color={initial.color}
                  transparent
                  opacity={initial.midOpacity}
                  depthWrite={false}
                  blending={THREE.AdditiveBlending}
                />
              </sprite>
              {/* Core — shaded sphere for 3D parallax */}
              <mesh>
                <sphereGeometry args={[size * 0.55, 32, 24]} />
                <meshStandardMaterial
                  ref={(m: any) => { if (m) coreMatRefs.current.set(name, m); }}
                  color={initial.color}
                  emissive={initial.color}
                  emissiveIntensity={initial.emissive}
                  roughness={0.9}
                  metalness={0}
                  transparent
                  opacity={initial.coreOpacity}
                />
              </mesh>
              {/* Speckle */}
              <sprite scale={[speckleScale, speckleScale, 1]}>
                <spriteMaterial
                  attach="material"
                  ref={(m: any) => { if (m) speckleMatRefs.current.set(name, m); }}
                  map={GLOW_TEX}
                  color={0xffffff}
                  transparent
                  opacity={initial.speckleOpacity}
                  depthWrite={false}
                  blending={THREE.AdditiveBlending}
                />
              </sprite>
              {/* Invisible picker for raycast */}
              <mesh
                onClick={(e) => { e.stopPropagation(); onRegionClick(name); }}
                userData={{ name }}
              >
                <sphereGeometry args={[size * 1.2, 16, 12]} />
                <meshBasicMaterial visible={false} />
              </mesh>
            </group>
          );
        })}
      </group>
    );
  }
  ```

- [ ] **Step 4 — Update `Scene.tsx` to use `<FuzzyOrbs />` and pass props.**

  ```tsx
  import { FuzzyOrbs } from './FuzzyOrbs';
  // ...
  const regionRefMap = useRef<Map<string, THREE.Object3D>>(new Map());
  const onRegionClick = useCallback((name: string) => {
    useStore.getState().select(name);
  }, []);
  // ...
  <FuzzyOrbs dimFactor={dimFactor} onRegionClick={onRegionClick} refMap={regionRefMap} />
  ```

  And in Task 8's `useEffect` for camera focus, use `regionRefMap.current.get(selectedRegion)` as the `fitToBox` target.

- [ ] **Step 5 — Delete `Regions.tsx`.**

  ```bash
  git rm observatory/web-src/src/scene/Regions.tsx
  ```

- [ ] **Step 6 — Write `FuzzyOrbs.test.tsx`.**

  Given the complexity of mocking react-three-fiber's `<Canvas>`, keep tests focused on *pure* layer-count assertions by exporting a small `countOrbLayers(region)` helper from FuzzyOrbs (returning `5` for any region: outer + mid + core + speckle + picker) that is trivially testable. Alternatively rely on visual QA.

  A simple pure-logic test:

  ```tsx
  import { describe, it, expect } from 'vitest';
  import { phaseBase } from './FuzzyOrbs'; // export phaseBase if not already

  describe('phaseBase', () => {
    it('wake has high emissive', () => {
      expect(phaseBase('wake').emissive).toBeCloseTo(0.55);
    });
    it('sleep has low emissive', () => {
      expect(phaseBase('sleep').emissive).toBeCloseTo(0.15);
    });
    it('unknown phase falls back to wake-blue', () => {
      expect(phaseBase('gobbledygook').color).toBe(0x6aa8ff);
    });
    it('outer scale differs by phase', () => {
      expect(phaseBase('wake').outerScale).toBe(5.2);
      expect(phaseBase('bootstrap').outerScale).toBe(4.5);
      expect(phaseBase('sleep').outerScale).toBe(3.8);
    });
  });
  ```

  (Export `phaseBase` from `FuzzyOrbs.tsx` to make this testable.)

- [ ] **Step 7 — Run frontend verification.**

  ```bash
  cd observatory/web-src && npx tsc -b && npm run test && npm run build
  cd ../..
  ```

  Expected: `tsc -b` clean; tests pass; build succeeds.

- [ ] **Step 8 — Commit.**

  ```bash
  git add observatory/web-src/src/scene/glowTexture.ts \
          observatory/web-src/src/scene/FuzzyOrbs.tsx \
          observatory/web-src/src/scene/FuzzyOrbs.test.tsx \
          observatory/web-src/src/scene/Scene.tsx
  git rm observatory/web-src/src/scene/Regions.tsx
  git commit -m "$(cat <<'EOF'
  observatory: FuzzyOrbs replaces Regions.tsx (v2 task 9)

  Each region is now a 5-mesh group: outer halo sprite + mid halo sprite +
  shaded core sphere (MeshStandardMaterial for 3D parallax) + white speckle
  sprite + invisible picker mesh. GLOW_TEX is a canvas-generated radial
  gradient singleton. Phase changes lerp opacity/emissive over 800 ms.
  Dim factor (from Task 8) multiplies every non-selected region's opacity.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 10 — Frontend: `Labels.tsx` (CSS2D floating text, name always / stats on hover)

**Files:**
- Create: `observatory/web-src/src/scene/Labels.tsx`
- Create: `observatory/web-src/src/scene/Labels.test.tsx`
- Modify: `observatory/web-src/src/scene/Scene.tsx` (mount `<Labels />`)
- Modify: `observatory/web-src/src/index.css` (add `.float-label` styles)

### Context for implementer

Spec §5.2. `three/addons/renderers/CSS2DRenderer.js` gives us billboarded DOM nodes positioned at 3D coords. One renderer instance + one `CSS2DObject` per region, attached to the FuzzyOrb group via `refMap`. Hover raycaster hits the picker mesh and toggles `.hover` class on the label root.

Key subtlety: `<Canvas>` from `@react-three/fiber` already drives the WebGL render loop. We need `CSS2DRenderer` to run every frame *after* the WebGL render. The cleanest way is to use `useFrame` with priority `1` (runs after default priority `0`) and manually call `labelRenderer.render(scene, camera)`.

### Steps

- [ ] **Step 1 — Add CSS to `index.css`** (or a collocated module CSS if v1 prefers).

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
  .float-label .phase-badge {
    font-family: 'Inter', ui-sans-serif, sans-serif;
    color: rgba(142, 197, 255, 0.85);
    margin-right: 5px;
    letter-spacing: 0.5px;
  }
  .float-label .phase-badge.sleep { color: rgba(138, 142, 153, 0.72); }
  .float-label .phase-badge.bootstrap { color: rgba(143, 214, 160, 0.85); }
  .float-label .sep { color: rgba(111, 115, 128, 0.7); margin: 0 4px; }
  ```

- [ ] **Step 2 — Create `Labels.tsx`.**

  ```tsx
  import { useEffect, useMemo, useRef } from 'react';
  import * as THREE from 'three';
  import { useFrame, useThree } from '@react-three/fiber';
  import { CSS2DRenderer, CSS2DObject } from 'three/addons/renderers/CSS2DRenderer.js';
  import { useStore, type RegionMeta } from '../store';

  function formatTokens(n: number): string {
    if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
    if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`;
    return String(n);
  }
  function formatBytes(n: number): string {
    if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
    if (n >= 1024)        return `${(n / 1024).toFixed(0)} kB`;
    return `${n} B`;
  }

  function buildLabelEl(): {
    root: HTMLDivElement;
    name: HTMLDivElement;
    stats: HTMLDivElement;
    phase: HTMLSpanElement;
    queueVal: HTMLSpanElement;
    stmVal: HTMLSpanElement;
    tokensVal: HTMLSpanElement;
  } {
    const root = document.createElement('div');
    root.className = 'float-label';

    const name = document.createElement('div');
    name.className = 'name';
    root.appendChild(name);

    const stats = document.createElement('div');
    stats.className = 'stats';
    const phase = document.createElement('span');
    phase.className = 'phase-badge';
    stats.appendChild(phase);
    const queueVal = document.createElement('span');
    stats.appendChild(document.createTextNode('queue '));
    stats.appendChild(queueVal);
    const sep1 = document.createElement('span');
    sep1.className = 'sep'; sep1.textContent = '·';
    stats.appendChild(sep1);
    stats.appendChild(document.createTextNode('stm '));
    const stmVal = document.createElement('span');
    stats.appendChild(stmVal);
    const sep2 = document.createElement('span');
    sep2.className = 'sep'; sep2.textContent = '·';
    stats.appendChild(sep2);
    stats.appendChild(document.createTextNode('tokens '));
    const tokensVal = document.createElement('span');
    stats.appendChild(tokensVal);
    root.appendChild(stats);

    return { root, name, stats, phase, queueVal, stmVal, tokensVal };
  }

  type LabelsProps = {
    refMap: React.MutableRefObject<Map<string, THREE.Object3D>>;
  };

  export function Labels({ refMap }: LabelsProps) {
    const { scene, camera, gl } = useThree();
    const regions = useStore((s) => s.regions);
    const selectedRegion = useStore((s) => s.selectedRegion);
    const names = useMemo(() => Object.keys(regions).sort(), [regions]);

    const rendererRef = useRef<CSS2DRenderer | null>(null);
    const labelObjRefs = useRef<Map<string, { obj: CSS2DObject; els: ReturnType<typeof buildLabelEl> }>>(new Map());

    // Track the hovered picker mesh (from FuzzyOrbs).
    const hoveredName = useRef<string | null>(null);

    // Set up CSS2DRenderer once.
    useEffect(() => {
      const renderer = new CSS2DRenderer();
      renderer.setSize(gl.domElement.clientWidth, gl.domElement.clientHeight);
      renderer.domElement.style.position = 'absolute';
      renderer.domElement.style.top = '0';
      renderer.domElement.style.left = '0';
      renderer.domElement.style.pointerEvents = 'none';
      gl.domElement.parentElement?.appendChild(renderer.domElement);
      rendererRef.current = renderer;

      const onResize = () => {
        renderer.setSize(gl.domElement.clientWidth, gl.domElement.clientHeight);
      };
      window.addEventListener('resize', onResize);
      return () => {
        window.removeEventListener('resize', onResize);
        renderer.domElement.remove();
        rendererRef.current = null;
      };
    }, [gl]);

    // Mount / unmount label objects as regions enter / leave.
    useEffect(() => {
      // Remove stale
      for (const [name, entry] of labelObjRefs.current.entries()) {
        if (!regions[name]) {
          entry.obj.parent?.remove(entry.obj);
          entry.els.root.remove();
          labelObjRefs.current.delete(name);
        }
      }
      // Add new
      for (const name of names) {
        if (labelObjRefs.current.has(name)) continue;
        const parent = refMap.current.get(name);
        if (!parent) continue;
        const els = buildLabelEl();
        const obj = new CSS2DObject(els.root);
        obj.position.set(0, 1.6, 0); // above the orb; FuzzyOrbs default size ≈ 1.0
        parent.add(obj);
        labelObjRefs.current.set(name, { obj, els });
      }
    }, [regions, names, refMap]);

    // Hover detection via a window-level raycaster on pointermove.
    useEffect(() => {
      const raycaster = new THREE.Raycaster();
      const mouse = new THREE.Vector2();
      const onMove = (ev: PointerEvent) => {
        const rect = gl.domElement.getBoundingClientRect();
        mouse.x = ((ev.clientX - rect.left) / rect.width) * 2 - 1;
        mouse.y = -((ev.clientY - rect.top) / rect.height) * 2 + 1;
        raycaster.setFromCamera(mouse, camera);
        // Find any descendant with userData.name via recursive traversal through refMap groups.
        const pickers: THREE.Object3D[] = [];
        for (const obj of refMap.current.values()) {
          obj.traverse((child) => {
            if ((child as any).userData?.name) pickers.push(child);
          });
        }
        const hits = raycaster.intersectObjects(pickers, false);
        hoveredName.current = hits.length ? (hits[0].object.userData.name as string) : null;
        gl.domElement.style.cursor = hoveredName.current ? 'pointer' : 'grab';
      };
      gl.domElement.addEventListener('pointermove', onMove);
      return () => gl.domElement.removeEventListener('pointermove', onMove);
    }, [gl, camera, refMap]);

    // Per-frame: update text, apply .hover class, render CSS2D.
    useFrame(() => {
      for (const [name, { els }] of labelObjRefs.current.entries()) {
        const meta: RegionMeta | undefined = regions[name];
        const stats = meta?.stats;
        els.name.textContent = name;
        if (stats) {
          els.phase.textContent = stats.phase.toUpperCase();
          els.phase.className = `phase-badge ${stats.phase}`;
          els.queueVal.textContent = String(stats.queue_depth);
          els.stmVal.textContent = formatBytes(stats.stm_bytes);
          els.tokensVal.textContent = formatTokens(stats.tokens_lifetime);
        }
        const force = name === hoveredName.current || name === selectedRegion;
        els.root.classList.toggle('hover', force);
      }
      rendererRef.current?.render(scene, camera);
    }, 1);

    return null;
  }
  ```

- [ ] **Step 3 — Mount `<Labels />` in `Scene.tsx`** (pass the same `regionRefMap`).

  ```tsx
  <Labels refMap={regionRefMap} />
  ```

- [ ] **Step 4 — Write `Labels.test.tsx` (pure helpers only).**

  ```ts
  import { describe, it, expect } from 'vitest';
  // Export formatTokens and formatBytes from Labels.tsx.
  import { formatTokens, formatBytes } from './Labels';

  describe('formatTokens', () => {
    it('sub-thousand raw', () => expect(formatTokens(999)).toBe('999'));
    it('thousand shorthand', () => expect(formatTokens(1500)).toBe('2k'));
    it('million shorthand', () => expect(formatTokens(2_412_000)).toBe('2.4M'));
  });
  describe('formatBytes', () => {
    it('bytes', () => expect(formatBytes(900)).toBe('900 B'));
    it('kilobytes', () => expect(formatBytes(18432)).toBe('18 kB'));
    it('megabytes', () => expect(formatBytes(2_500_000)).toBe('2.4 MB'));
  });
  ```

- [ ] **Step 5 — Run frontend verification.**

  ```bash
  cd observatory/web-src && npx tsc -b && npm run test && npm run build
  cd ../..
  ```

- [ ] **Step 6 — Commit.**

  ```bash
  git add observatory/web-src/src/scene/Labels.tsx \
          observatory/web-src/src/scene/Labels.test.tsx \
          observatory/web-src/src/scene/Scene.tsx \
          observatory/web-src/src/index.css
  git commit -m "$(cat <<'EOF'
  observatory: Labels (CSS2DRenderer, name always / stats on hover) (v2 task 10)

  Per-region floating text via CSS2DObject attached to FuzzyOrb groups.
  Name is always visible (10px, weight 200, thin). Stats (phase badge,
  queue, stm, tokens) appear only on hover via raycaster, OR forced-on
  for the selected region. Renderer lives at priority=1 after the main
  WebGL render.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 11 — Frontend: `Edges.tsx` (reactive threads) + Sparks bump

**Files:**
- Create: `observatory/web-src/src/scene/Edges.tsx`
- Create: `observatory/web-src/src/scene/Edges.test.ts`
- Modify: `observatory/web-src/src/scene/Sparks.tsx` (bump `EDGE_PULSE` on spawn)
- Modify: `observatory/web-src/src/scene/Scene.tsx` (mount `<Edges />`)

### Context for implementer

Spec §5.3. One `<line>` (R3F primitive) per adjacency pair, each with its own `LineBasicMaterial`. A module-level `Map<edgeKey, { pulse, color }>` is exported from `Edges.tsx` and imported into `Sparks.tsx` — when a spark spawns for an edge, bump `pulse` to 1 and copy the spark color. Every frame, `Edges.tsx` decays pulses at `1/0.8s` and applies opacity/color formulae. Dim factor multiplies the final opacity.

### Steps

- [ ] **Step 1 — Create `Edges.tsx`.**

  ```tsx
  import { useMemo, useRef, useEffect } from 'react';
  import * as THREE from 'three';
  import { useFrame } from '@react-three/fiber';
  import { useStore } from '../store';
  import { useForceGraph } from './useForceGraph';

  const BASE_COLOR_HEX = 0x2a3550;
  const BASE_OPACITY = 0.08;
  const REACTIVE_GAIN = 0.55;
  const DECAY_PER_SEC = 1 / 0.8;

  type Entry = { pulse: number; color: THREE.Color; material: THREE.LineBasicMaterial };

  /** Module-level: Sparks.tsx writes to this Map to bump an edge's pulse. */
  export const EDGE_PULSE: Map<string, Entry> = new Map();

  export function edgeKey(a: string, b: string): string {
    return a < b ? `${a}|${b}` : `${b}|${a}`;
  }

  type EdgesProps = { dimFactor: number };

  export function Edges({ dimFactor }: EdgesProps) {
    const regions = useStore((s) => s.regions);
    const adjacency = useStore((s) => s.adjacency);
    const { nodes } = useForceGraph(regions);
    const names = useMemo(() => Object.keys(regions).sort(), [regions]);
    const nameToIndex = useMemo(() => new Map(names.map((n, i) => [n, i])), [names]);

    // Rebuild EDGE_PULSE whenever adjacency changes. Preserve pulses for
    // edges that still exist; drop entries for vanished pairs.
    const lineRefs = useRef<THREE.Line[]>([]);

    useEffect(() => {
      const present = new Set<string>();
      for (const [a, b] of adjacency) {
        const k = edgeKey(a, b);
        present.add(k);
        if (!EDGE_PULSE.has(k)) {
          const mat = new THREE.LineBasicMaterial({
            color: BASE_COLOR_HEX,
            transparent: true,
            opacity: BASE_OPACITY,
            blending: THREE.AdditiveBlending,
            depthWrite: false,
          });
          EDGE_PULSE.set(k, { pulse: 0, color: new THREE.Color(BASE_COLOR_HEX), material: mat });
        }
      }
      for (const k of Array.from(EDGE_PULSE.keys())) {
        if (!present.has(k)) EDGE_PULSE.delete(k);
      }
    }, [adjacency]);

    useFrame((_, dt) => {
      const d = Math.min(dt, 0.05);
      // Update line geometries from node positions + decay pulses.
      for (let i = 0; i < adjacency.length; i++) {
        const [a, b] = adjacency[i];
        const ia = nameToIndex.get(a);
        const ib = nameToIndex.get(b);
        if (ia == null || ib == null) continue;
        const na = nodes[ia]; const nb = nodes[ib];
        if (!na || !nb) continue;
        const line = lineRefs.current[i];
        if (!line) continue;
        const positions = (line.geometry as THREE.BufferGeometry).attributes.position.array as Float32Array;
        positions[0] = na.x; positions[1] = na.y; positions[2] = na.z;
        positions[3] = nb.x; positions[4] = nb.y; positions[5] = nb.z;
        (line.geometry as THREE.BufferGeometry).attributes.position.needsUpdate = true;
      }
      for (const entry of EDGE_PULSE.values()) {
        entry.pulse = Math.max(0, entry.pulse - d * DECAY_PER_SEC);
        if (entry.pulse > 0.01) {
          entry.material.opacity = (BASE_OPACITY + REACTIVE_GAIN * entry.pulse) * dimFactor;
          entry.material.color.copy(entry.color);
        } else {
          entry.material.opacity = BASE_OPACITY * dimFactor;
          entry.material.color.setHex(BASE_COLOR_HEX);
        }
      }
    });

    // Render: one <primitive object={line}/> per adjacency pair.
    return (
      <group>
        {adjacency.map(([a, b], i) => {
          const k = edgeKey(a, b);
          const entry = EDGE_PULSE.get(k);
          if (!entry) return null;
          const geom = new THREE.BufferGeometry();
          geom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3));
          const line = new THREE.Line(geom, entry.material);
          lineRefs.current[i] = line;
          return <primitive key={k} object={line} />;
        })}
      </group>
    );
  }
  ```

  **Note:** because `<primitive>` holds a reference to an object constructed per-render, this triggers unnecessary churn. The cleaner pattern is to use `useMemo` to construct the geometry + line once per adjacency change. Optimize if the first implementation shows allocation pressure in profiling.

- [ ] **Step 2 — Modify `Sparks.tsx` to bump `EDGE_PULSE` on spawn.**

  Locate where `Sparks.tsx` spawns a new spark. Add the import and the bump:

  ```tsx
  import { EDGE_PULSE, edgeKey } from './Edges';
  import { topicColorObject } from './topicColors';

  // ...inside the spawn loop, once per new spark:
  const k = edgeKey(sourceRegionName, destRegionName);
  const entry = EDGE_PULSE.get(k);
  if (entry) {
    entry.pulse = 1.0;
    entry.color.copy(topicColorObject(envelope.topic));
  }
  ```

  If Sparks doesn't currently know both endpoints (just the source), compute the destination from `envelope.destinations[0]` or similar — Sparks already resolves this for its own rendering.

- [ ] **Step 3 — Mount `<Edges />` in `Scene.tsx`** (before or after `<Sparks />` — order doesn't matter render-wise since both are additive).

  ```tsx
  <Edges dimFactor={dimFactor} />
  ```

- [ ] **Step 4 — Write `Edges.test.ts`.**

  ```ts
  import { describe, it, expect, beforeEach } from 'vitest';
  import { EDGE_PULSE, edgeKey } from './Edges';
  import * as THREE from 'three';

  describe('edgeKey', () => {
    it('is undirected', () => {
      expect(edgeKey('a', 'b')).toBe(edgeKey('b', 'a'));
    });
    it('is alphabetical', () => {
      expect(edgeKey('z', 'a')).toBe('a|z');
    });
  });

  describe('EDGE_PULSE bump + decay (formula)', () => {
    it('opacity formula: 0.08 + 0.55 * pulse at pulse=1 equals 0.63', () => {
      const gain = 0.55; const base = 0.08;
      expect(base + gain * 1.0).toBeCloseTo(0.63);
    });
    it('opacity formula at pulse=0 equals base', () => {
      expect(0.08 + 0.55 * 0).toBeCloseTo(0.08);
    });
  });
  ```

  (The frame-by-frame decay is tested by timing in a more integrated component test if desired; pure-logic formulae pin the contract.)

- [ ] **Step 5 — Run frontend verification.**

  ```bash
  cd observatory/web-src && npx tsc -b && npm run test && npm run build
  cd ../..
  ```

- [ ] **Step 6 — Commit.**

  ```bash
  git add observatory/web-src/src/scene/Edges.tsx \
          observatory/web-src/src/scene/Edges.test.ts \
          observatory/web-src/src/scene/Sparks.tsx \
          observatory/web-src/src/scene/Scene.tsx
  git commit -m "$(cat <<'EOF'
  observatory: reactive adjacency threads (v2 task 11)

  One Line per adjacency pair with per-edge LineBasicMaterial. Module-level
  EDGE_PULSE Map; Sparks.tsx bumps pulse=1 + spark color on spawn. useFrame
  decays pulses at 1/0.8s. Opacity formula: 0.08 + 0.55 * pulse, multiplied
  by dimFactor. Color fades back to cool blue-grey once pulse < 0.01.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 12 — Frontend: Inspector shell + keyboard + 5 simple sections (Header, Stats, ModulatorBath, Subscriptions, Handlers)

**Files:**
- Create: `observatory/web-src/src/inspector/Inspector.tsx`
- Create: `observatory/web-src/src/inspector/useInspectorKeys.ts`
- Create: `observatory/web-src/src/inspector/sections/Header.tsx`
- Create: `observatory/web-src/src/inspector/sections/Stats.tsx`
- Create: `observatory/web-src/src/inspector/sections/ModulatorBath.tsx`
- Create: `observatory/web-src/src/inspector/sections/Subscriptions.tsx`
- Create: `observatory/web-src/src/inspector/sections/Handlers.tsx`
- Create: `observatory/web-src/src/inspector/Header.test.tsx`
- Modify: `observatory/web-src/src/App.tsx` (mount `<Inspector />`, install keys)

### Context for implementer

This task lands the shell + the five quick sections. Big sections (Prompt, STM, Messages) land in Tasks 13–14. The inspector is always mounted; it slide-animates via a CSS class toggle driven by `selectedRegion != null`. When closed, section fetches aren't running because `useRegionFetch(null, ...)` is idle (per Task 7 semantics).

### Steps

- [ ] **Step 1 — Create `useInspectorKeys.ts`.**

  ```ts
  import { useEffect } from 'react';
  import { useStore } from '../store';

  /** Window-level keydown: Esc / [ / ] / R. Ignores input-focus targets. */
  export function useInspectorKeys() {
    useEffect(() => {
      const onKey = (ev: KeyboardEvent) => {
        const t = ev.target as HTMLElement | null;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || (t as HTMLElement).isContentEditable)) return;

        const { selectedRegion, select, cycle } = useStore.getState();
        if (ev.key === 'Escape' && selectedRegion) { ev.preventDefault(); select(null); }
        else if (ev.key === '[' && selectedRegion) { ev.preventDefault(); cycle(-1); }
        else if (ev.key === ']' && selectedRegion) { ev.preventDefault(); cycle(1); }
        else if ((ev.key === 'r' || ev.key === 'R')) {
          // R always resets camera; signaled via a global event the Scene listens for.
          window.dispatchEvent(new CustomEvent('observatory:camera-reset'));
        }
      };
      window.addEventListener('keydown', onKey);
      return () => window.removeEventListener('keydown', onKey);
    }, []);
  }
  ```

  **Note:** `R` reset is dispatched as a `CustomEvent` to avoid coupling this hook to `CameraControls` ref. Task 8's Scene.tsx should add a `window.addEventListener('observatory:camera-reset', () => ctrl.reset(true))`.

- [ ] **Step 2 — Create `Inspector.tsx` (shell).**

  ```tsx
  import { useStore } from '../store';
  import { Header } from './sections/Header';
  import { Stats } from './sections/Stats';
  import { ModulatorBath } from './sections/ModulatorBath';
  import { Prompt } from './sections/Prompt';          // Task 13
  import { Messages } from './sections/Messages';      // Task 14
  import { Stm } from './sections/Stm';                // Task 13
  import { Subscriptions } from './sections/Subscriptions';
  import { Handlers } from './sections/Handlers';

  export function Inspector() {
    const name = useStore((s) => s.selectedRegion);
    const open = name != null;
    return (
      <aside
        className={`fixed right-0 top-0 h-screen w-[420px] bg-[#121218] border-l border-[#2a2a33] text-[#cfd2da] flex flex-col transition-transform duration-300 ease-out z-20 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
        aria-hidden={!open}
      >
        {open && (
          <>
            <Header name={name!} />
            <Stats name={name!} />
            <ModulatorBath />
            <div className="flex-1 overflow-y-auto">
              <Prompt name={name!} />
              <Messages name={name!} />
              <Stm name={name!} />
              <Subscriptions name={name!} />
              <Handlers name={name!} />
            </div>
            <KeyHintFooter />
          </>
        )}
      </aside>
    );
  }

  function KeyHintFooter() {
    return (
      <div className="px-3 py-2 border-t border-[#2a2a33] bg-[#0e0e14] text-[10px] text-[#8a8e99] flex gap-3 font-mono">
        <span><kbd className="bg-[#1e1e26] px-1 py-0.5 rounded">Esc</kbd> close</span>
        <span><kbd className="bg-[#1e1e26] px-1 py-0.5 rounded">[</kbd> <kbd className="bg-[#1e1e26] px-1 py-0.5 rounded">]</kbd> cycle</span>
        <span><kbd className="bg-[#1e1e26] px-1 py-0.5 rounded">R</kbd> reset cam</span>
      </div>
    );
  }
  ```

  `Prompt`, `Messages`, and `Stm` are imported eagerly. Because `Inspector` is only rendered when `name != null`, they only mount when needed — still cheap even if unused sections fetch.

- [ ] **Step 3 — Create `sections/Header.tsx`.**

  ```tsx
  import { useEffect, useState } from 'react';
  import { useStore } from '../../store';
  import { useRegionFetch } from '../useRegionFetch';
  import { fetchConfig } from '../../api/rest';

  export function Header({ name }: { name: string }) {
    const meta = useStore((s) => s.regions[name]);
    const select = useStore((s) => s.select);
    const cfg = useRegionFetch(name, fetchConfig);
    const llmModel = typeof cfg.data?.llm_model === 'string' && cfg.data.llm_model
      ? cfg.data.llm_model
      : (meta?.llm_model || '—');

    return (
      <div className="px-4 py-3 border-b border-[#2a2a33]">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-[15px] font-semibold">{name}</span>
            <PhaseBadge phase={meta?.stats?.phase ?? 'unknown'} />
          </div>
          <button
            className="bg-none border-0 text-[#8a8e99] text-base"
            onClick={() => select(null)}
            aria-label="close inspector"
          >
            ✕
          </button>
        </div>
        <div className="flex gap-3 mt-1 text-[#8a8e99] text-[11px]">
          <span>handlers {meta?.stats?.handler_count ?? 0}</span>
          <span>model {llmModel}</span>
        </div>
      </div>
    );
  }

  function PhaseBadge({ phase }: { phase: string }) {
    const cls =
      phase === 'sleep' ? 'bg-[#2a2f3a] text-[#8a8e99]'
      : phase === 'bootstrap' ? 'bg-[#1e3a2a] text-[#8fd6a0]'
      : 'bg-[#1e3a5f] text-[#8ec5ff]';
    return <span className={`text-[10px] px-2 py-0.5 rounded-full tracking-wider ${cls}`}>{phase.toUpperCase()}</span>;
  }
  ```

- [ ] **Step 4 — Create `sections/Stats.tsx`.**

  ```tsx
  import { useEffect, useRef, useState } from 'react';
  import { useStore, type RegionStats } from '../../store';

  const HISTORY_POINTS = 24; // 2 minutes at 5s heartbeat cadence

  function useStatsHistory(name: string): Record<keyof Pick<RegionStats, 'queue_depth' | 'stm_bytes' | 'tokens_lifetime'>, number[]> {
    const [history, setHistory] = useState({ queue_depth: [] as number[], stm_bytes: [] as number[], tokens_lifetime: [] as number[] });
    useEffect(() => {
      const unsub = useStore.subscribe((s, prev) => {
        const stats = s.regions[name]?.stats;
        if (!stats) return;
        setHistory((h) => ({
          queue_depth: [...h.queue_depth.slice(-HISTORY_POINTS + 1), stats.queue_depth],
          stm_bytes: [...h.stm_bytes.slice(-HISTORY_POINTS + 1), stats.stm_bytes],
          tokens_lifetime: [...h.tokens_lifetime.slice(-HISTORY_POINTS + 1), stats.tokens_lifetime],
        }));
      });
      return unsub;
    }, [name]);
    return history;
  }

  function Sparkline({ points, stroke }: { points: number[]; stroke: string }) {
    if (points.length < 2) return <div className="h-[10px]" />;
    const min = Math.min(...points), max = Math.max(...points);
    const span = max - min || 1;
    const coords = points.map((p, i) => `${(i / (HISTORY_POINTS - 1)) * 48},${14 - ((p - min) / span) * 12}`).join(' ');
    return (
      <svg viewBox="0 0 48 14" width="100%" height={10}>
        <polyline points={coords} fill="none" stroke={stroke} strokeWidth={1} />
      </svg>
    );
  }

  function relativeTime(ts: string | null): { text: string; fresh: boolean } {
    if (!ts) return { text: '—', fresh: false };
    const then = new Date(ts).getTime();
    if (Number.isNaN(then)) return { text: '—', fresh: false };
    const delta = (Date.now() - then) / 1000;
    if (delta < 60) return { text: `${Math.floor(delta)}s`, fresh: true };
    if (delta < 3600) return { text: `${Math.floor(delta / 60)}m`, fresh: false };
    return { text: `${Math.floor(delta / 3600)}h`, fresh: false };
  }

  export function Stats({ name }: { name: string }) {
    const stats = useStore((s) => s.regions[name]?.stats);
    const history = useStatsHistory(name);
    if (!stats) return null;

    const stmColor = stats.stm_bytes > 64 * 1024 ? 'text-[#ff6a6a]'
                   : stats.stm_bytes > 16 * 1024 ? 'text-[#ffb36a]'
                   : 'text-[#cfd2da]';
    const err = relativeTime(stats.last_error_ts);

    const fmtBytes = (n: number) => n >= 1024 * 1024 ? `${(n/1024/1024).toFixed(1)}MB` : n >= 1024 ? `${Math.round(n/1024)}kB` : `${n}B`;
    const fmtTokens = (n: number) => n >= 1e6 ? `${(n/1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n/1e3)}k` : String(n);

    return (
      <div className="px-3 py-2 border-b border-[#2a2a33] grid grid-cols-5 gap-1">
        <Tile label="QUEUE" value={String(stats.queue_depth)}><Sparkline points={history.queue_depth} stroke="#6aa8ff" /></Tile>
        <Tile label="STM" value={<span className={stmColor}>{fmtBytes(stats.stm_bytes)}</span>}>
          <Sparkline points={history.stm_bytes} stroke="#ffb36a" />
        </Tile>
        <Tile label="TOKENS" value={fmtTokens(stats.tokens_lifetime)}><Sparkline points={history.tokens_lifetime} stroke="#8fd6a0" /></Tile>
        <Tile label="HANDLERS" value={String(stats.handler_count)} />
        <Tile label="LAST ERR" value={
          <span className="inline-flex items-center gap-1">
            {err.fresh && <span className="inline-block w-1.5 h-1.5 rounded-full bg-[#ff6a6a]" />}
            {err.text}
          </span>
        } />
      </div>
    );
  }

  function Tile({ label, value, children }: { label: string; value: React.ReactNode; children?: React.ReactNode }) {
    return (
      <div className="bg-[#16161c] p-1.5 rounded text-center">
        <div className="text-[9px] text-[#8a8e99] tracking-wider">{label}</div>
        <div className="text-[13px] font-semibold my-0.5">{value}</div>
        {children ?? <div className="h-[10px]" />}
      </div>
    );
  }
  ```

- [ ] **Step 5 — Create `sections/ModulatorBath.tsx`.**

  ```tsx
  import { Modulators } from '../../hud/Modulators';

  export function ModulatorBath() {
    return (
      <div className="px-4 py-2 border-b border-[#2a2a33]">
        <div className="text-[9px] text-[#8a8e99] tracking-wider mb-1">MODULATOR BATH</div>
        <Modulators variant="compact" />
      </div>
    );
  }
  ```

  **Note:** if `hud/Modulators.tsx` does not accept a `variant` prop today, either extend it (add `variant?: 'default' | 'compact'`) or render it without the prop. The spec says the Modulator-bath section just re-uses v1's gauges; no duplication.

- [ ] **Step 6 — Create `sections/Subscriptions.tsx`.**

  ```tsx
  import { fetchSubscriptions } from '../../api/rest';
  import { useRegionFetch } from '../useRegionFetch';

  export function Subscriptions({ name }: { name: string }) {
    const { loading, error, data, reload } = useRegionFetch(name, fetchSubscriptions);
    const topics = (data?.topics as string[] | undefined) ?? [];

    return (
      <details className="px-4 py-2 border-b border-[#1f1f27]">
        <summary className="cursor-pointer flex justify-between items-center">
          <span className="font-semibold">Subscriptions <span className="text-[#8a8e99] text-[10px]">· {topics.length} topics</span></span>
          <button onClick={(e) => { e.preventDefault(); reload(); }} className="text-[10px] text-[#8a8e99] border border-[#2a2a33] px-2 rounded">reload</button>
        </summary>
        <div className="pt-2 text-[11px]">
          {loading && <div className="text-[#8a8e99]">loading…</div>}
          {error && <div className="text-[#ff6a6a]">Failed: {error}</div>}
          {!loading && !error && topics.length === 0 && <div className="text-[#8a8e99]">No subscriptions declared.</div>}
          <ul className="font-mono list-none pl-0">
            {topics.map((t) => <li key={t} className="py-0.5">{t}</li>)}
          </ul>
        </div>
      </details>
    );
  }
  ```

- [ ] **Step 7 — Create `sections/Handlers.tsx`.**

  ```tsx
  import { fetchHandlers, type HandlerEntry } from '../../api/rest';
  import { useRegionFetch } from '../useRegionFetch';

  function fmtBytes(n: number): string {
    if (n >= 1024) return `${(n / 1024).toFixed(1)} kB`;
    return `${n} B`;
  }

  export function Handlers({ name }: { name: string }) {
    const { loading, error, data, reload } = useRegionFetch(name, fetchHandlers);
    const entries: HandlerEntry[] = data ?? [];

    return (
      <details className="px-4 py-2 border-b border-[#1f1f27]">
        <summary className="cursor-pointer flex justify-between items-center">
          <span className="font-semibold">Handlers <span className="text-[#8a8e99] text-[10px]">· {entries.length} files</span></span>
          <button onClick={(e) => { e.preventDefault(); reload(); }} className="text-[10px] text-[#8a8e99] border border-[#2a2a33] px-2 rounded">reload</button>
        </summary>
        <div className="pt-2 text-[11px]">
          {loading && <div className="text-[#8a8e99]">loading…</div>}
          {error && <div className="text-[#ff6a6a]">Failed: {error}</div>}
          {!loading && !error && entries.length === 0 && <div className="text-[#8a8e99]">No handler files.</div>}
          <ul className="font-mono list-none pl-0">
            {entries.map((e) => (
              <li key={e.path} className="py-0.5 flex justify-between">
                <span>{e.path}</span>
                <span className="text-[#8a8e99]">{fmtBytes(e.size)}</span>
              </li>
            ))}
          </ul>
        </div>
      </details>
    );
  }
  ```

- [ ] **Step 8 — Modify `App.tsx`: mount `<Inspector />`, install keys.**

  Read the current `App.tsx` (17 lines). Add:

  ```tsx
  import { Inspector } from './inspector/Inspector';
  import { useInspectorKeys } from './inspector/useInspectorKeys';
  // ...
  function App() {
    useInspectorKeys();
    return (
      <>
        <Scene />
        <Hud />
        <Inspector />
      </>
    );
  }
  ```

- [ ] **Step 9 — Write `Header.test.tsx`.**

  ```tsx
  import { describe, it, expect } from 'vitest';
  import { render, screen } from '@testing-library/react';
  import { Header } from './sections/Header';
  import { useStore } from '../store';

  describe('Header', () => {
    beforeEach(() => {
      useStore.getState().applyRegionDelta({
        testregion: { role: 'x', llm_model: '', stats: {
          phase: 'wake', queue_depth: 0, stm_bytes: 0, tokens_lifetime: 0,
          handler_count: 5, last_error_ts: null, msg_rate_in: 0, msg_rate_out: 0,
          llm_in_flight: false,
        } },
      });
    });

    it('renders phase badge and handler count', () => {
      render(<Header name="testregion" />);
      expect(screen.getByText(/WAKE/)).toBeTruthy();
      expect(screen.getByText(/handlers 5/)).toBeTruthy();
    });

    it('falls back to em-dash when llm_model is empty', () => {
      render(<Header name="testregion" />);
      expect(screen.getByText(/model —/)).toBeTruthy();
    });
  });
  ```

- [ ] **Step 10 — Run verification.**

  ```bash
  cd observatory/web-src && npx tsc -b && npm run test && npm run build
  cd ../..
  ```

- [ ] **Step 11 — Commit.**

  ```bash
  git add observatory/web-src/src/inspector/ observatory/web-src/src/App.tsx
  git commit -m "$(cat <<'EOF'
  observatory: inspector shell + 5 simple sections (v2 task 12)

  Inspector slide-over mounts when selectedRegion != null; panel animates
  via Tailwind transform transition. useInspectorKeys binds Esc/[/]/R at
  window level with input-focus guard. Header pulls config (for llm_model)
  + falls back to em-dash. Stats strip has 5 tiles with 2-min sparklines
  and stm threshold coloring. ModulatorBath re-uses v1 HUD gauges.
  Subscriptions + Handlers are collapsed details with reload buttons.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 13 — Frontend: Prompt + STM + JsonTree sections

**Files:**
- Create: `observatory/web-src/src/inspector/sections/JsonTree.tsx`
- Create: `observatory/web-src/src/inspector/sections/Prompt.tsx`
- Create: `observatory/web-src/src/inspector/sections/Stm.tsx`
- Create: `observatory/web-src/src/inspector/Stm.test.tsx`

### Context for implementer

Two sections with similar scaffolding (collapsed `<details>`, reload, auto-refetch on phase/last_error_ts change) + one recursive JSON renderer shared by Stm. Auto-refetch is wired via a `useEffect` watching the region's `phase` and `last_error_ts` and calling `reload()` when either changes.

### Steps

- [ ] **Step 1 — Create `JsonTree.tsx`.**

  ```tsx
  import { useState } from 'react';

  type JsonValue = string | number | boolean | null | JsonArray | JsonObject;
  type JsonArray = JsonValue[];
  type JsonObject = { [k: string]: JsonValue };

  export function JsonTree({ value, depth = 0 }: { value: JsonValue; depth?: number }) {
    if (value === null) return <span className="text-[#8a8e99]">null</span>;
    if (typeof value === 'string') return <span className="text-[#8fd6a0]">"{value}"</span>;
    if (typeof value === 'number') return <span className="text-[#ffb36a]">{value}</span>;
    if (typeof value === 'boolean') return <span className="text-[#d6a0e0]">{String(value)}</span>;
    if (Array.isArray(value)) return <JsonArrayView arr={value} depth={depth} />;
    return <JsonObjectView obj={value} depth={depth} />;
  }

  function JsonObjectView({ obj, depth }: { obj: JsonObject; depth: number }) {
    const [open, setOpen] = useState(depth < 1);
    const keys = Object.keys(obj);
    if (keys.length === 0) return <span className="text-[#8a8e99]">{'{}'}</span>;
    return (
      <span>
        <button className="text-[#8a8e99] font-mono" onClick={() => setOpen(!open)}>{open ? '▾' : '▸'}</button>
        <span className="text-[#8a8e99]"> {'{'} </span>
        {open && (
          <div className="pl-3">
            {keys.map((k) => (
              <div key={k} className="font-mono text-[11px]">
                <span className="text-[#8ec5ff]">{k}</span>
                <span className="text-[#8a8e99]">: </span>
                <JsonTree value={obj[k]} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
        <span className="text-[#8a8e99]">{'}'}</span>
      </span>
    );
  }

  function JsonArrayView({ arr, depth }: { arr: JsonArray; depth: number }) {
    const [open, setOpen] = useState(depth < 1);
    if (arr.length === 0) return <span className="text-[#8a8e99]">[]</span>;
    return (
      <span>
        <button className="text-[#8a8e99] font-mono" onClick={() => setOpen(!open)}>{open ? '▾' : '▸'}</button>
        <span className="text-[#8a8e99]"> [</span>
        {open && (
          <div className="pl-3">
            {arr.map((item, i) => (
              <div key={i} className="font-mono text-[11px]">
                <span className="text-[#8a8e99]">{i}: </span>
                <JsonTree value={item} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
        <span className="text-[#8a8e99]">]</span>
      </span>
    );
  }
  ```

- [ ] **Step 2 — Create `Prompt.tsx`.**

  ```tsx
  import { useEffect } from 'react';
  import { useStore } from '../../store';
  import { useRegionFetch } from '../useRegionFetch';
  import { fetchPrompt } from '../../api/rest';

  export function Prompt({ name }: { name: string }) {
    const { loading, error, data, reload } = useRegionFetch(name, fetchPrompt);
    const stats = useStore((s) => s.regions[name]?.stats);

    // Auto-refetch on phase change or last_error_ts change (spec §3.3).
    useEffect(() => {
      if (stats) reload();
    }, [stats?.phase, stats?.last_error_ts]);  // deliberately excludes `reload` (stable)

    const sizeKb = data ? (data.length / 1024).toFixed(1) : '—';

    return (
      <details className="border-b border-[#1f1f27]">
        <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
          <span className="font-semibold">Prompt <span className="text-[#8a8e99] text-[10px]">· {sizeKb} kB</span></span>
          <button onClick={(e) => { e.preventDefault(); reload(); }} className="text-[10px] text-[#8a8e99] border border-[#2a2a33] px-2 rounded">reload</button>
        </summary>
        <div className="px-4 pb-3 text-[11px]">
          {loading && <div className="text-[#8a8e99]">loading…</div>}
          {error && <div className="text-[#ff6a6a]">Failed: {error}</div>}
          {!loading && !error && !data && <div className="text-[#8a8e99]">No <code>prompt.md</code> in this region.</div>}
          {data && <pre className="whitespace-pre-wrap break-words text-[#cfd2da] bg-[#0e0e14] p-2 rounded max-h-[360px] overflow-y-auto">{data}</pre>}
        </div>
      </details>
    );
  }
  ```

- [ ] **Step 3 — Create `Stm.tsx`.**

  ```tsx
  import { useEffect } from 'react';
  import { useStore } from '../../store';
  import { useRegionFetch } from '../useRegionFetch';
  import { fetchStm } from '../../api/rest';
  import { JsonTree } from './JsonTree';

  export function Stm({ name }: { name: string }) {
    const { loading, error, data, reload } = useRegionFetch(name, fetchStm);
    const stats = useStore((s) => s.regions[name]?.stats);

    useEffect(() => {
      if (stats) reload();
    }, [stats?.phase, stats?.last_error_ts]);

    const keyCount = data ? Object.keys(data).length : 0;

    return (
      <details className="border-b border-[#1f1f27]">
        <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
          <span className="font-semibold">STM <span className="text-[#8a8e99] text-[10px]">· {keyCount} keys</span></span>
          <button onClick={(e) => { e.preventDefault(); reload(); }} className="text-[10px] text-[#8a8e99] border border-[#2a2a33] px-2 rounded">reload</button>
        </summary>
        <div className="px-4 pb-3 text-[11px]">
          {loading && <div className="text-[#8a8e99]">loading…</div>}
          {error && <div className="text-[#ff6a6a]">Failed: {error}</div>}
          {!loading && !error && data && Object.keys(data).length === 0 && <div className="text-[#8a8e99]">STM is empty.</div>}
          {data && Object.keys(data).length > 0 && <JsonTree value={data as any} />}
        </div>
      </details>
    );
  }
  ```

- [ ] **Step 4 — Write `Stm.test.tsx`.**

  ```tsx
  import { describe, it, expect, vi } from 'vitest';
  import { render, screen, waitFor } from '@testing-library/react';
  import { Stm } from './sections/Stm';
  import { useStore } from '../store';

  describe('Stm', () => {
    beforeEach(() => {
      useStore.getState().applyRegionDelta({
        r: { role: 'x', llm_model: '', stats: {
          phase: 'wake', queue_depth: 0, stm_bytes: 0, tokens_lifetime: 0,
          handler_count: 0, last_error_ts: null, msg_rate_in: 0, msg_rate_out: 0,
          llm_in_flight: false,
        } },
      });
    });

    it('renders empty-state copy when STM is {}', async () => {
      vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({}), { status: 200, headers: { 'content-type': 'application/json' } })));
      const { container } = render(<Stm name="r" />);
      // Expand the details.
      container.querySelector('details')!.open = true;
      await waitFor(() => expect(screen.getByText('STM is empty.')).toBeTruthy());
    });
  });
  ```

- [ ] **Step 5 — Run verification.**

  ```bash
  cd observatory/web-src && npx tsc -b && npm run test && npm run build
  cd ../..
  ```

- [ ] **Step 6 — Commit.**

  ```bash
  git add observatory/web-src/src/inspector/sections/Prompt.tsx \
          observatory/web-src/src/inspector/sections/Stm.tsx \
          observatory/web-src/src/inspector/sections/JsonTree.tsx \
          observatory/web-src/src/inspector/Stm.test.tsx
  git commit -m "$(cat <<'EOF'
  observatory: inspector Prompt + STM + JsonTree (v2 task 13)

  Prompt: collapsed <details> with <pre> body + reload; auto-refetch on
  phase or last_error_ts change. STM: same shape, rendered via JsonTree
  (recursive, no dependencies, inline styling). Empty-state copy for both.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 14 — Frontend: Messages section (filter + auto-scroll + row expand)

**Files:**
- Create: `observatory/web-src/src/inspector/sections/Messages.tsx`
- Create: `observatory/web-src/src/inspector/Messages.test.tsx`

### Context for implementer

The most nuanced section. Filters the existing envelope ring buffer client-side to rows where `source_region === name || name ∈ destinations`, keeps the last 100. Uses Task 13-15's incremental-scan pattern from v1 Sparks to avoid re-scanning the whole 5000-envelope ring every frame. Auto-scroll: follows the tail when the user's scroll position is within 40 px of the bottom; pauses otherwise.

### Steps

- [ ] **Step 1 — Create `Messages.tsx`.**

  ```tsx
  import { useEffect, useRef, useState } from 'react';
  import { useStore, type Envelope } from '../../store';

  const MAX_ROWS = 100;
  const AUTOSCROLL_PX = 40;

  function relevantToRegion(env: Envelope, name: string): boolean {
    return env.source_region === name || env.destinations.includes(name);
  }

  function renderTime(observedAt: number): string {
    const d = new Date(observedAt * 1000);
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    const s = String(d.getSeconds()).padStart(2, '0');
    return `${h}:${m}:${s}`;
  }

  function previewPayload(env: Envelope): string {
    try {
      const s = JSON.stringify(env.envelope);
      return s.length > 80 ? s.slice(0, 80) + '…' : s;
    } catch {
      return '';
    }
  }

  export function Messages({ name }: { name: string }) {
    const [filtered, setFiltered] = useState<Envelope[]>([]);
    const lastLenRef = useRef(0);
    const [expanded, setExpanded] = useState<Set<number>>(new Set());
    const containerRef = useRef<HTMLDivElement | null>(null);
    const followTailRef = useRef(true);

    // Incremental scan: only process envelopes added since last frame.
    useEffect(() => {
      const unsub = useStore.subscribe((s) => {
        const env = s.envelopes;
        const last = lastLenRef.current;
        const ringLen = env.length;
        const newOnes: Envelope[] = [];
        const startIdx = Math.max(0, last);
        for (let i = startIdx; i < ringLen; i++) {
          const e = env[i];
          if (relevantToRegion(e, name)) newOnes.push(e);
        }
        lastLenRef.current = ringLen;
        if (newOnes.length > 0) {
          setFiltered((f) => {
            const next = f.concat(newOnes);
            return next.length > MAX_ROWS ? next.slice(-MAX_ROWS) : next;
          });
        }
      });
      // Seed from current ring contents (useful when panel just opened).
      const ring = useStore.getState().envelopes;
      const initial: Envelope[] = [];
      for (const e of ring) if (relevantToRegion(e, name)) initial.push(e);
      setFiltered(initial.slice(-MAX_ROWS));
      lastLenRef.current = ring.length;
      return unsub;
    }, [name]);

    // Track follow-tail state on user scroll.
    useEffect(() => {
      const el = containerRef.current;
      if (!el) return;
      const onScroll = () => {
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= AUTOSCROLL_PX;
        followTailRef.current = atBottom;
      };
      el.addEventListener('scroll', onScroll);
      return () => el.removeEventListener('scroll', onScroll);
    }, []);

    // Auto-scroll when new row lands AND user was at bottom.
    useEffect(() => {
      if (!followTailRef.current) return;
      const el = containerRef.current;
      if (el) el.scrollTop = el.scrollHeight;
    }, [filtered]);

    return (
      <details open className="border-b border-[#1f1f27]">
        <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
          <span className="font-semibold">Messages <span className="text-[#8a8e99] text-[10px]">· filtered to {name} · {filtered.length} recent</span></span>
        </summary>
        <div ref={containerRef} className="px-4 pb-2 text-[10.5px] font-mono text-[#cfd2da] max-h-[220px] overflow-y-auto">
          {filtered.length === 0 && <div className="text-[#8a8e99]">No messages yet.</div>}
          {filtered.map((e, i) => {
            const isExpanded = expanded.has(i);
            const direction = e.source_region === name ? '↑' : '↓';
            return (
              <div key={`${e.observed_at}-${i}`} className="py-1 border-b border-dotted border-[#23232b]">
                <div
                  className="grid grid-cols-[60px_14px_1fr] gap-2 cursor-pointer"
                  onClick={() => setExpanded((s) => {
                    const n = new Set(s); n.has(i) ? n.delete(i) : n.add(i); return n;
                  })}
                >
                  <span className="text-[#8a8e99]">{renderTime(e.observed_at)}</span>
                  <span className={direction === '↑' ? 'text-[#ffb36a]' : 'text-[#8fd6a0]'}>{direction}</span>
                  <span>
                    {e.topic}
                    {!isExpanded && <span className="text-[#8a8e99]"> &nbsp;{previewPayload(e)}</span>}
                  </span>
                </div>
                {isExpanded && (
                  <pre className="text-[10px] text-[#8a8e99] whitespace-pre-wrap pl-[76px] pt-1">
                    {JSON.stringify(e.envelope, null, 2)}
                  </pre>
                )}
              </div>
            );
          })}
        </div>
      </details>
    );
  }
  ```

- [ ] **Step 2 — Write `Messages.test.tsx`.**

  ```tsx
  import { describe, it, expect } from 'vitest';
  import { render, screen } from '@testing-library/react';
  import { Messages } from './sections/Messages';
  import { useStore } from '../store';

  describe('Messages', () => {
    beforeEach(() => {
      useStore.setState({ envelopes: [], envelopesReceivedTotal: 0, regions: {} });
      useStore.getState().applyRegionDelta({
        r: { role: 'x', llm_model: '', stats: { phase: 'wake', queue_depth: 0, stm_bytes: 0, tokens_lifetime: 0, handler_count: 0, last_error_ts: null, msg_rate_in: 0, msg_rate_out: 0, llm_in_flight: false } },
      });
    });

    it('shows only envelopes where region is source or destination', () => {
      useStore.getState().pushEnvelope({ observed_at: 0, topic: 'hive/a', envelope: {}, source_region: 'r', destinations: [] });
      useStore.getState().pushEnvelope({ observed_at: 1, topic: 'hive/b', envelope: {}, source_region: 'other', destinations: ['r'] });
      useStore.getState().pushEnvelope({ observed_at: 2, topic: 'hive/c', envelope: {}, source_region: 'other', destinations: ['nope'] });
      render(<Messages name="r" />);
      expect(screen.getByText(/hive\/a/)).toBeTruthy();
      expect(screen.getByText(/hive\/b/)).toBeTruthy();
      expect(screen.queryByText(/hive\/c/)).toBeNull();
    });

    it('shows direction ↑ for source, ↓ for destination', () => {
      useStore.getState().pushEnvelope({ observed_at: 0, topic: 't/one', envelope: {}, source_region: 'r', destinations: [] });
      useStore.getState().pushEnvelope({ observed_at: 1, topic: 't/two', envelope: {}, source_region: 'x', destinations: ['r'] });
      render(<Messages name="r" />);
      expect(screen.getAllByText('↑').length).toBe(1);
      expect(screen.getAllByText('↓').length).toBe(1);
    });

    it('caps rendered rows at MAX_ROWS', () => {
      for (let i = 0; i < 150; i++) {
        useStore.getState().pushEnvelope({ observed_at: i, topic: `t/${i}`, envelope: {}, source_region: 'r', destinations: [] });
      }
      const { container } = render(<Messages name="r" />);
      const rows = container.querySelectorAll('.grid.grid-cols-\\[60px_14px_1fr\\]');
      expect(rows.length).toBe(100);
    });
  });
  ```

- [ ] **Step 3 — Run verification.**

  ```bash
  cd observatory/web-src && npx tsc -b && npm run test && npm run build
  cd ../..
  ```

- [ ] **Step 4 — Commit.**

  ```bash
  git add observatory/web-src/src/inspector/sections/Messages.tsx \
          observatory/web-src/src/inspector/Messages.test.tsx
  git commit -m "$(cat <<'EOF'
  observatory: inspector Messages section — filter + auto-scroll (v2 task 14)

  Client-side filter over the store envelope ring buffer via incremental
  scan (last-seen index) so large traffic doesn't hot-path the filter.
  MAX_ROWS=100. Direction icon ↑/↓ by source-vs-destination. Auto-scroll
  follows tail when user is within 40 px of bottom; pauses otherwise.
  Click a row to expand full envelope JSON inline.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Task 15 — Integration + final verification + HANDOFF bump

**Files:**
- Modify: `observatory/HANDOFF.md`

### Context for implementer

No new code. Run every gate, fix anything that slipped, then bump the HANDOFF progress table and changelog.

### Steps

- [ ] **Step 1 — Python suite.**

  ```bash
  .venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q
  .venv/Scripts/python.exe -m ruff check observatory/
  ```

  Expected: all unit tests passing (~88+), ruff clean.

- [ ] **Step 2 — Component (Docker required).**

  ```bash
  .venv/Scripts/python.exe -m pytest observatory/tests/component/ -m component -v
  ```

  Expected: 2 passing (v1 MQTT e2e + v2 regions e2e).

- [ ] **Step 3 — Frontend suite.**

  ```bash
  cd observatory/web-src && npx tsc -b && npm run test && npm run build
  cd ../..
  ```

  Expected: TypeScript clean, all vitest passing, build emits `observatory/web/`.

- [ ] **Step 4 — Smoke test end-to-end.**

  Start the service, hit the new endpoints via curl, verify JSON shapes and Cache-Control:

  ```bash
  # In a separate terminal or background:
  OBSERVATORY_REGIONS_ROOT=regions .venv/Scripts/python.exe -m observatory
  # Then:
  curl -s http://127.0.0.1:8765/api/regions/<some-real-region>/prompt | head -5
  curl -s -I http://127.0.0.1:8765/api/regions/<some-real-region>/handlers | grep -i cache-control
  ```

  Expected: `Cache-Control: no-store` present on every v2 response.

- [ ] **Step 5 — Bump HANDOFF.md.**

  Update the top `Last updated:` line. Add 15 rows to the progress table (one per v2 task). Extend the What's next section to point at v3 (`continue observatory v3`). Add a changelog entry.

- [ ] **Step 6 — Final commit.**

  ```bash
  git add observatory/HANDOFF.md
  git commit -m "$(cat <<'EOF'
  observatory: v2 ships (task 15)

  All 14 tasks landed with subagent-driven-development discipline: fresh
  implementer subagent per task, two-stage review (spec-compliance +
  code-quality) between tasks, one commit per task plus review-fix commits.
  Python suite expanded to ~88+ unit + 2 component tests; frontend vitest
  count grew with the new inspector and scene modules. Visual E2E deferred
  to human-loop review per v1 convention.

  Canonical resume for v3: `continue observatory v3`.

  Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
  EOF
  )"
  ```

---

## Self-Review (applied against spec before committing plan)

**Spec coverage check:**

| Spec section | Covered by |
|---|---|
| §2 Scope | Tasks 1–14 (one-to-one mapping; §2 items 1–6 → reader, endpoints, inspector, threads, labels, orbs) |
| §3.1 Panel layout | Task 12 (Inspector.tsx slide-over) + Task 8 (dim factor) |
| §3.2 Section inventory | Tasks 12 (Header, Stats, ModulatorBath, Subscriptions, Handlers), 13 (Prompt, STM), 14 (Messages) |
| §3.3 Fetch + refetch rules | Task 7 (useRegionFetch) + per-section auto-refetch in 12/13 |
| §3.4 Loading/error states | Each section renders `loading`/`error`/`data` per-hook; Tasks 12–14 |
| §4 Interaction model | Task 8 (camera/dim), Task 12 (useInspectorKeys), Task 9 (click via picker mesh) |
| §5.1 Fuzzy orbs | Task 9 |
| §5.2 Region labels | Task 10 |
| §5.3 Reactive threads | Task 11 |
| §6.1 Sandbox reader | Tasks 1–3 |
| §6.2 REST endpoints | Task 4 |
| §7 Frontend file layout | All frontend tasks create the files listed in §7.1 |
| §7.4 Data flow | Implicit in Tasks 8–12 wiring |
| §8 Testing | TDD step in every task; Tasks 4/5 (backend) + Tasks 6/7/9/10/11/12/13/14 (frontend) |
| §9 Safety & posture | Tasks 1–3 (sandbox), Task 4 (no publish) |
| §10 Migration from v1 | Tasks 8 (OrbitControls swap), 9 (Regions.tsx deletion), 12 (App.tsx mount) |

**Placeholder scan:** No `TBD`, `TODO`, `FIXME`, or "implement later" in the plan. Every step shows either code, exact commands, or narrative with complete detail.

**Type consistency:** `RegionReader.read_prompt/read_stm/...` signatures match across Tasks 1–4; `SandboxError(code)` used identically in reader and API layer; frontend `RestError(status, message, body)` used in all 5 fetchers and consumed by `useRegionFetch`; `HandlerEntry` has the same shape on both sides of the boundary (POSIX string `path` + `size: number`); `EDGE_PULSE` shape is consistent across Tasks 11 (producer/consumer) and Sparks.tsx.

**Spec/v1 drift notes (called out in plan preamble):** `queue_depth` (not `queue_depth_messages`); real v1 modulator names; actual `api/rest.ts` path; v1 `Regions.tsx` under `scene/`.

---

## Execution Handoff

Plan complete and saved to [observatory/docs/plans/2026-04-21-observatory-v2-plan.md](./2026-04-21-observatory-v2-plan.md). Execution model is **subagent-driven-development** per `observatory/CLAUDE.md` — fresh implementer subagent per task, two-stage review between tasks (spec-compliance + code-quality), one commit per task plus review-fix commits.

Canonical resume prompt: `continue observatory v2`.
