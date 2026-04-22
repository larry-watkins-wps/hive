# Observatory v3 — Task 1 implementer prompt

You are an implementer subagent. You own **exactly one task** end-to-end: implementation, tests, verification, commit. When done, report status (`DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`) with the commit SHA and a short summary.

Use `superpowers:test-driven-development`. Red → green → refactor. Every step below is non-negotiable unless you explicitly flag a spec/plan drift and justify.

**Working directory:** `C:\repos\hive` (the Hive repo root). All paths below are repo-root-relative.

**Python invocation:** use `.venv/Scripts/python.exe` (Windows venv). `python` on bare PATH does not have pytest/ruff.

---

## Task

Add a sandboxed `/api/regions/{name}/appendix` REST route that serves `regions/<name>/memory/appendices/rolling.md`. Fresh regions that have never slept legitimately lack this file — the route returns 404 in that case.

### Authoritative references

1. **Spec §9** (authoritative — plan conflicts lose to spec):
   - `observatory/docs/specs/2026-04-22-observatory-v3-design.md` lines 241–292.
2. **Plan Task 1:** `observatory/docs/plans/2026-04-22-observatory-v3-plan.md` lines 129–303.

---

## Plan Task 1 — verbatim

```
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

  Confirm the `reader_fixture` defined at the top of `test_region_reader.py` sets up `good_region` under a tmpdir — v2 Tasks 1-3 already added it.

- [ ] **Step 2 — Run to verify failure.** Expected: 4 FAILED with `AttributeError: 'RegionReader' object has no attribute 'read_appendix'`.

- [ ] **Step 3 — Implement `read_appendix`.** After `read_config` (around line 89):

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

- [ ] **Step 4 — Run reader tests.** Expected: all 4 PASS.

- [ ] **Step 5 — Write failing API tests.** In `test_api_regions_v2.py`:

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

- [ ] **Step 6 — Run to verify failure.** Expected: 3 FAILED.

- [ ] **Step 7 — Add the `/appendix` route.** In `observatory/api.py`, under `get_prompt`:

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

- [ ] **Step 8 — Run full test suite + ruff.**

      python -m pytest observatory/tests/unit/ -q
      python -m ruff check observatory/

  Expected: all green.

- [ ] **Step 9 — Commit.** HEREDOC per the plan.
```

---

## Plan drifts you MUST correct (verified against current files)

The plan's verbatim test code references fixtures that **do not exist in the current codebase**. You must adapt the test style to match the existing patterns. These are not optional — blindly pasting the plan's code will fail.

### Drift A — `reader_fixture` does not exist; use `regions_root: Path`

The only fixture in `observatory/tests/unit/conftest.py` is:

```python
@pytest.fixture()
def regions_root(tmp_path: Path) -> Path:
    root = tmp_path / "regions"
    region = root / "testregion"
    (region / "memory").mkdir(parents=True)
    (region / "handlers").mkdir()
    (region / "prompt.md").write_text("# hello from testregion\n", encoding="utf-8")
    # … plus stm.json, subscriptions.yaml, config.yaml, handlers/on_wake.py
    return root
```

The fixture seeds a region named **`testregion`**, not `good_region`. Use `testregion` throughout.

Existing reader tests are **module-level functions**, not classes (see `test_read_prompt_happy_path`, `test_missing_file_returns_404`, etc.). Keep that style — add four new module-level functions, not a `TestReadAppendix` class:

```python
def test_read_appendix_happy_path(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    appendix_dir = regions_root / "testregion" / "memory" / "appendices"
    appendix_dir.mkdir(parents=True, exist_ok=True)
    (appendix_dir / "rolling.md").write_text(
        "## 2026-04-22T10:00:00Z - sleep\n\nLearned that topic X ...\n",
        encoding="utf-8",
    )
    assert "topic X" in reader.read_appendix("testregion")


def test_read_appendix_missing_returns_404(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    with pytest.raises(SandboxError) as ei:
        reader.read_appendix("testregion")
    assert ei.value.code == 404  # noqa: PLR2004 — HTTP status under test


def test_read_appendix_invalid_region_name_returns_404(regions_root: Path) -> None:
    reader = RegionReader(regions_root)
    with pytest.raises(SandboxError) as ei:
        reader.read_appendix("../evil")
    assert ei.value.code == 404  # noqa: PLR2004 — HTTP status under test


def test_read_appendix_oversize_returns_413(
    regions_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    appendix_dir = regions_root / "testregion" / "memory" / "appendices"
    appendix_dir.mkdir(parents=True, exist_ok=True)
    (appendix_dir / "rolling.md").write_text("aaaa", encoding="utf-8")
    monkeypatch.setattr("observatory.region_reader.MAX_FILE_BYTES", 2)
    reader = RegionReader(regions_root)
    with pytest.raises(SandboxError) as ei:
        reader.read_appendix("testregion")
    assert ei.value.code == 413  # noqa: PLR2004 — HTTP status under test
```

Note the `# noqa: PLR2004` comments — the existing suite uses these on HTTP-status integer literals.

### Drift B — `seeded_app` does not exist; use the `client: TestClient` fixture

`test_api_regions_v2.py` already defines a `client: TestClient` fixture at module level (lines 22-44). It builds the app with `regions_root` + seeds `testregion` into the registry via `app.state.registry.apply_heartbeat("testregion", {"phase": "wake"})`.

Existing API tests are **module-level functions**, not classes. Follow the same pattern. Translate the plan's three class-based tests into module-level functions:

```python
def test_appendix_happy(client: TestClient, regions_root: Path) -> None:
    appendix_dir = regions_root / "testregion" / "memory" / "appendices"
    appendix_dir.mkdir(parents=True, exist_ok=True)
    (appendix_dir / "rolling.md").write_text(
        "## 2026-04-22T10:00:00Z - sleep\n\nbody\n", encoding="utf-8"
    )
    r = client.get("/api/regions/testregion/appendix")
    assert r.status_code == 200  # noqa: PLR2004
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"].startswith("text/plain")
    assert "body" in r.text


def test_appendix_404_when_missing(client: TestClient) -> None:
    r = client.get("/api/regions/testregion/appendix")
    assert r.status_code == 404  # noqa: PLR2004
    body = r.json()
    assert body["error"] == "not_found"


def test_appendix_404_when_region_unknown(client: TestClient) -> None:
    r = client.get("/api/regions/unknown/appendix")
    assert r.status_code == 404  # noqa: PLR2004
    assert r.json()["error"] == "not_found"
```

The plan's verbatim Step 6 expected "3 FAILED" — with the `client` fixture refactor, expect only `test_appendix_happy` + `test_appendix_404_when_missing` to fail on the route (both produce 404 with `detail={"error":"not_found",...}` because the endpoint doesn't exist yet, which is a route-not-registered 404 — pytest distinguishes via message/fields). `test_appendix_404_when_region_unknown` might fortuitously pass pre-impl because FastAPI's own "Not Found" 404 arrives with a different body shape; adjust expectations accordingly during the red phase. The goal of red-phase is *any* failure that confirms the test is meaningful; after green everything passes.

### Drift C — route placement

Drop the new route right after `get_prompt` in `observatory/api.py` (lines 65-76). This keeps the static-vs-JSON response_class pairs grouped: `/prompt` and `/appendix` both return `PlainTextResponse`.

---

## Existing-contract surface (read these before writing)

- `observatory/region_reader.py` — `SandboxError`, `_validate()`, `read_prompt()`, `read_stm()`, `read_subscriptions()`, `read_config()`, `list_handlers()`, `MAX_FILE_BYTES = 2 * 1024 * 1024`. `_validate()` already emits 404 on missing, 403 on traversal/symlink/escape/null-byte, 413 on oversize, with a canonical `observatory.region_read_denied` log event.
- `observatory/api.py` — `_ERROR_KIND` maps SandboxError.code → error kind; `_error_detail()`, `_ensure_region()`, `_reader()`, `_NO_STORE = {"Cache-Control": "no-store"}`; existing `build_router()` registers 5 routes.
- `observatory/tests/unit/conftest.py` — `regions_root` fixture (seeds `testregion` under tmpdir).
- `observatory/tests/unit/test_region_reader.py` — existing module-level test pattern.
- `observatory/tests/unit/test_api_regions_v2.py` — existing module-level test pattern + `client` fixture.

## Gotchas

- **`noqa: PLR2004`** on HTTP-status integer literals in assertions (existing suite does this; ruff's `magic-value-comparison` rule bites otherwise).
- **Windows path-separators:** all `_validate()` inputs are POSIX strings. Do not pass `os.path.join("memory", "appendices", "rolling.md")` — pass the literal `"memory/appendices/rolling.md"` exactly as in other reader methods.
- **`pytest.raises(SandboxError) as ei`** — the existing style is `ei.value.code`, not `exc.value.code`. Stay consistent with siblings.
- **Oversize test:** the plan's version writes `MAX_FILE_BYTES + 1` bytes upfront then checks. The existing `test_oversize_returns_413` instead uses `monkeypatch.setattr(..., MAX_FILE_BYTES, 8)` and a small file. Either works; pick whichever is simpler. (My suggested version above uses monkeypatch to keep the test fast.)
- **`@dataclass(frozen=True) class HandlerEntry`** is unrelated to appendix — do not touch it.

## Verification gates (must all pass before committing)

```
.venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q
.venv/Scripts/python.exe -m ruff check observatory/
```

Expected: **all 96 unit tests pass (92 prior + 4 new reader tests)** + 2 skipped (prior symlink skips), ruff clean.

Also confirm the 3 new API tests land in `test_api_regions_v2.py` module (so total suite goes from 92 → 99 passing: 4 reader + 3 API).

## Commit

One commit per the plan. HEREDOC:

```bash
git add observatory/region_reader.py observatory/api.py observatory/tests/unit/test_region_reader.py observatory/tests/unit/test_api_regions_v2.py
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

## Report format

Respond with:

1. **Status:** `DONE` / `DONE_WITH_CONCERNS` / `NEEDS_CONTEXT` / `BLOCKED`.
2. **Commit SHA:** (from `git rev-parse HEAD`).
3. **Files touched:** list.
4. **Test delta:** before/after counts (unit tests + which new ones).
5. **Any drift from plan beyond A/B/C above** — describe and justify.
6. **Any concerns** (for `DONE_WITH_CONCERNS`).
