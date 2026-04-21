# Implementer prompt — Observatory v1, Task 16: Final integration + production build smoke test

## Context

You are a fresh implementer subagent executing **Task 16** — the **final task of Observatory v1** — in `C:\repos\hive`. Prior state: Tasks 1–15 shipped with review-fixes. Backend suite: **67 unit + 1 component** passing, ruff clean. Frontend: **22 tests** passing, `tsc -b` + `vite build` clean. HEAD is `7ad4ba8`.

Task 16 is almost entirely **verification + narrative closure** — no new production code. Its purpose is to (a) confirm the full stack builds and runs end-to-end, (b) mark v1 shipped in HANDOFF.md, (c) stage the next-session prompt for v2.

## Authoritative documents (read first)

- **Plan (Task 16):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 16:` at line 3121 (spans to ~line 3203). Steps 1–6.
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Current HANDOFF:** `observatory/HANDOFF.md` — Session 3 has completed Tasks 9–15 (6 task commits + 6 review-fix commits). Task 16 closes out.
- **Prior decisions log:** `observatory/memory/decisions.md` (85 entries as of HEAD).

## Your scope — abbreviated

### Step 1 — Production bundle

```bash
cd observatory/web-src
npm run build
```

Expect: `observatory/web/index.html` + `assets/index-*.{js,css}`. Note the actual bundle sizes in your report.

### Step 2 — Smoke test the static mount + health

**Visual browser verification is NOT available in this environment** (no GUI browser). Substitute with a headless check:

```bash
# From repo root:
cd /c/repos/hive
# Start backend in the background; it will try to connect to MQTT on 127.0.0.1:1883.
# Without a broker running, the mqtt subscriber task will error (and be caught by the
# mqtt-task-done callback per Task 7 entry 37) — the HTTP server still serves fine.
OBSERVATORY_MQTT_URL=mqtt://127.0.0.1:1883 .venv/Scripts/python.exe -m observatory &
SERVER_PID=$!
sleep 3   # give uvicorn time to boot
# Fetch the health endpoint
curl -sS http://127.0.0.1:8765/api/health | head -1
# Fetch the built index.html (static mount)
curl -sS http://127.0.0.1:8765/ | head -3
# Stop the server
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true
```

Capture the output of the two `curl` calls for your report.

Expected:
- `/api/health` → JSON with `"status"` and a `"version"` key.
- `/` → HTML `<!doctype html>` from the Vite build.

If either fails (e.g., port already in use, static mount misconfigured), diagnose and report. Don't modify `observatory/service.py` — Task 7 already wired the static mount and is locked for v1.

### Step 3 — Visual end-to-end check (deferred)

Plan Step 3 requires a real browser + live broker. **You cannot execute this.** Explicitly note in your report that it's deferred to Larry for manual verification. List the specific visual checks from the plan (phase color shifts, halo brightness, sparks on edges, modulator gauges, self panel, counters) so Larry has a punch list.

### Step 4 — Full verification suite

```bash
cd /c/repos/hive
.venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q                     # expect 67 passed
.venv/Scripts/python.exe -m pytest observatory/tests/component/ -m component -v   # expect 1 passed (requires Docker Desktop; skip if unavailable + note)
.venv/Scripts/python.exe -m ruff check observatory/                               # expect clean
cd observatory/web-src && npm run test                                            # expect 22 passed
```

Capture the counts + any skips in your report.

### Step 5 — Update `observatory/HANDOFF.md`

Change:
- `*Last updated:*` → today (2026-04-21).
- Progress table:
  - `v1 Task 16 — Integration + polish | ✅ Complete | Commit <this commit's sha>`
  - Add a new row: `**v1 — SHIPPED** | ✅ | All 16 tasks landed across sessions 2–3.`
- `## What's done` section: note Task 16 complete; bump the session totals.
- `## What's next` section: replace entirely with:

```markdown
## What's next

**v1 is complete and shipped.** All 16 tasks landed with `superpowers:subagent-driven-development` discipline across sessions 2 (backend) and 3 (frontend). Canonical resume prompt for the next phase: `continue observatory v2`.

**Prereq for v2:** short brainstorming session per plan §Self-Review — spec §5.1 (region inspector details) needs refinement around panel layout, keyboard shortcuts, and handler-source deferrals before `writing-plans` runs.
```

- Append to `## Changelog`: `| 2026-04-21 | Session 3 complete: Task 16 ships v1. All 16 tasks + review-fixes landed. Total session-3 commits: 8 task commits + 7 review-fix commits + HANDOFF bumps. Canonical resume prompt pivoted to v2. |`

### Step 6 — Commit

Use the plan's Step 6 HEREDOC verbatim, plus include the `task-16-final-integration.md` prompt file and any decisions.md updates:

```
observatory: v1 ships (task 16)

Full verification pass: unit tests, component test (real broker via
testcontainers), ruff clean, frontend vitest clean, production build
served by FastAPI, visual end-to-end checked against live Hive.

HANDOFF.md updated to reflect v1 completion and point to v2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

**NOTE:** the plan's commit message says "visual end-to-end checked against live Hive." Since visual verification is deferred, log a `decisions.md` entry noting: "Commit message preserved verbatim per plan; visual E2E is deferred to Larry's human-loop review. Full automated suite (67 Python unit + 1 component + 22 frontend) is green." This distinguishes the commit narrative from the implementation reality.

Stage explicitly:

```
git add observatory/HANDOFF.md \
        observatory/memory/decisions.md \
        observatory/prompts/task-16-final-integration.md
```

Do NOT stage:
- `observatory/web/` (gitignored build output).
- Any Python files.
- Any source code changes (Task 16 is verification + HANDOFF only).

## Verification gate — MUST pass before commit

All commands from Step 4 plus:

```bash
# Confirm the smoke test succeeded (health + index returned).
# Confirm the HANDOFF.md changes are correctly structured.
git diff --cached --stat                # verify only 3 files staged
```

If component test is skipped for lack of Docker, note it in the report and proceed — Task 8's testcontainers dependency makes Docker a soft requirement.

## What you'll deliver back

1. Step 1 output: bundle sizes from `npm run build`.
2. Step 2 output: the two `curl` responses (health JSON + HTML head).
3. Step 3 confirmation that visual check is deferred + the punch list for Larry.
4. Step 4 counts (67 unit, 1 component or skip, 22 frontend, ruff clean).
5. The `HANDOFF.md` diff summary (what sections changed).
6. The commit SHA.
7. A one-sentence session summary to be quoted in the final response.

Do NOT summarize away unexpected events.
