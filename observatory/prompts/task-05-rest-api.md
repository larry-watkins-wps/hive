# Implementer prompt — Observatory v1, Task 5: REST API `/api/health` + `/api/regions`

## Context

You are a fresh implementer subagent executing **Task 5** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–4 shipped with review-fixes. Full observatory suite at **47 passed**, ruff clean. HEAD is `a1d9536`.

Task 5 adds a minimal FastAPI router with two v1 endpoints:
- `GET /api/health` → `{"status": "ok", "version": "0.1.0"}`
- `GET /api/regions` → `{"regions": region_registry.to_json()}`

The router takes a `RegionRegistry` as a constructor arg (dependency injection). Tests use `httpx.AsyncClient` with `ASGITransport`. This is a small task — ~40 lines of code + ~40 lines of test.

## Authoritative documents (read first)

- **Plan (Task 5):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 5:` (~line 1219). Complete code blocks for Steps 1 (tests) and 3 (implementation).
- **Spec:** `observatory/docs/specs/2026-04-20-observatory-design.md` — §6 (API surface) lists `GET /api/health`, `GET /api/regions` as v1 endpoints. `/api/regions/{name}/prompt` and `/stm` are v2 (do NOT implement those here).
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Existing dependency:** `observatory/region_registry.py::RegionRegistry.to_json()` already exists — returns `{name: {role, llm_model, stats: {...}}}`. Do NOT modify it.
- **Existing module init:** `observatory/__init__.py` exposes `__version__ = "0.1.0"`.

## Your scope

Execute all 5 steps of Task 5 as written in the plan:

1. Write failing test `observatory/tests/unit/test_api.py` (2 async tests via `httpx.AsyncClient` + `ASGITransport`).
2. Run — confirm `ModuleNotFoundError`.
3. Implement `observatory/api.py` with `build_router(region_registry: RegionRegistry) -> APIRouter`.
4. Run — confirm tests pass.
5. Ruff clean; commit with plan's Step 5 HEREDOC.

## Important constraints

- **Python venv:** `source .venv/Scripts/activate` before pytest/ruff.
- **One commit** at task end with the plan's Step 5 HEREDOC ending `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>`. Stage only `observatory/api.py` and `observatory/tests/unit/test_api.py`. Optionally stage `observatory/memory/decisions.md` if you add a new entry, and `observatory/prompts/task-05-rest-api.md` (this file) for audit parity.
- **Scope boundary:** touch only the two Task 5 files. Do NOT modify other observatory files. Do NOT touch `region_template/`, `glia/`, `regions/`, `bus/`, `shared/`, `tools/`, top-level `tests/`, or `observatory/pyproject.toml`.
- **Ruff/lint:** workspace root owns config. Precedent: PLR2004 `# noqa` on magic numbers in tests (including `r.status_code == 200`), UP037 unquoted refs, PLC0415 on inline imports. Apply the same mechanical pattern.
- **TDD:** red-first.

## Known gotchas

- `httpx` v0.27+ requires `ASGITransport(app=app)` + `AsyncClient(transport=...)` — the plan's test imports already reflect this. Don't use deprecated `AsyncClient(app=app)`.
- The `build_router(region_registry=reg)` kwarg style is deliberate — keeps the dependency explicit. Don't introduce FastAPI `Depends()` here; the registry is a singleton created by the service factory in Task 7.
- `@router.get("/health")` with `prefix="/api"` yields the path `/api/health`. Tests should request `/api/health`, not `/health`.
- Return type annotations on the async route functions — the plan uses `-> dict`. Ruff may flag `ANN401` on the `dict` return, but the project's ruff config doesn't select `ANN`, so it should be fine. If it does flag, use `dict[str, Any]`.
- Do NOT add Pydantic response models — v1 scope is "return the dict". Response modeling is a v2 polish.

## What you must NOT do

- Do NOT implement Task 6 (WebSocket). That's a much bigger task and has its own turn.
- Do NOT add per-region REST endpoints (`/api/regions/{name}/prompt`, `/stm`) — those are v2.
- Do NOT modify `RegionRegistry` or any other existing observatory module.
- Do NOT use `git add -A`; stage explicit paths.

## Verification commands

```bash
source .venv/Scripts/activate
python -m pytest observatory/tests/unit/test_api.py -v
python -m ruff check observatory/
python -m pytest observatory/tests/unit/ -q        # expect 47 + 2 = 49 passed
```

## Report back (<200 words)

- Files created
- Test counts (new / full observatory suite)
- Ruff result
- Commit SHA + subject
- Any deviations + rationale (likely just mechanical `# noqa: PLR2004`)
- Anything worth flagging
