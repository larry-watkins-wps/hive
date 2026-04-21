# Implementer prompt — Observatory v1, Task 9: Frontend scaffolding

## Context

You are a fresh implementer subagent executing **Task 9** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–8 shipped with review-fixes. Full observatory backend suite is **67 unit + 1 component passing**, ruff clean. HEAD is `774fe44`.

Task 9 is a **language-stack switch**. Everything before this was Python/pytest/ruff. Task 9 creates the frontend project — Vite + React + TypeScript + Tailwind — under `observatory/web-src/`, building to `observatory/web/` (gitignored). The goal is purely infrastructure: prove `vite dev`, `vite build`, and FastAPI's static mount of `observatory/web/` all work before Tasks 10–16 wire real state management and the 3D scene.

This Task 9 must create **exactly the scaffolding the plan specifies and nothing more**: a placeholder HUD rectangle, no scene yet. Tasks 10–16 build the real frontend iteratively.

## Authoritative documents (read first)

- **Plan (Task 9):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 9: Frontend scaffolding` (line 1895). Complete code blocks for every file are verbatim in the plan.
- **Sub-project guide:** `observatory/CLAUDE.md` — scope boundaries and execution discipline.
- **Top-level guide:** `CLAUDE.md` at repo root — Windows caveats.
- **Dockerfile shape target:** `observatory/Dockerfile` already expects `observatory/web-src/package.json`, `observatory/web-src/package-lock.json`, and a `npm run build` that outputs to `observatory/web/`. Task 9 makes these materialize.
- **Spec (for static-mount context):** `observatory/docs/specs/2026-04-20-observatory-design.md` §5 — FastAPI serves `observatory/web/` at `/`; verify this is already implemented in `observatory/service.py` (it is, from Task 7; do NOT modify service.py in Task 9).

## Your scope

Execute plan Steps 1–12, in order:

1. Create `observatory/web-src/package.json` (verbatim from plan).
2. Create `observatory/web-src/vite.config.ts` (verbatim).
3. Create `observatory/web-src/tsconfig.json` (verbatim).
4. Create `observatory/web-src/tsconfig.node.json` (verbatim).
5. Create `observatory/web-src/tailwind.config.ts` (verbatim).
6. Create `observatory/web-src/postcss.config.js` (verbatim).
7. Create `observatory/web-src/index.html` (verbatim).
8. Create `observatory/web-src/src/index.css` (verbatim).
9. Create `observatory/web-src/src/main.tsx` (verbatim).
10. Create `observatory/web-src/src/App.tsx` (verbatim).
11. Run `npm install` then `npm run build` inside `observatory/web-src/`.
12. Commit with the plan's HEREDOC (Step 12).

You are NOT doing Task 10 scaffolding (store.ts, ws.ts, rest.ts, vitest config, tests). Stop at Task 9.

## Critical concerns & pre-approved guidance

### 1. Use the plan's code blocks verbatim

The plan gives complete, copy-ready contents for every file. Use them exactly. Do not:
- Upgrade dependency versions beyond what the plan pins (some dep versions in the plan are deliberately older to match a known-compatible set; upgrading e.g. `three` or `@react-three/fiber` could break Tasks 10–16).
- Add linting/prettier/eslint configs (out of scope).
- Add tests (out of scope — Task 10 introduces vitest).
- Touch any Python file.
- Modify `observatory/service.py` or any backend module.
- Modify `observatory/.gitignore` — it already lists `web/` and `node_modules/`.

If you notice a typo or bug in a plan code block that you believe is load-bearing, **STOP and flag it in `observatory/memory/decisions.md`** rather than silently fixing. Spec-compliance review will check this.

### 2. `npm install` on Windows

You are on Windows 11, bash shell (git-bash/WSL-ish). Steps:

```bash
cd observatory/web-src
npm install
npm run build
```

`npm install` will generate `observatory/web-src/package-lock.json` (required — Dockerfile's `COPY observatory/web-src/package-lock.json* ./` expects it). Commit it.

Do NOT `npm ci` — there's no lockfile yet. `npm install` creates one.

Node/npm should already be installed on the host. If not, surface the error; do not try to install Node yourself.

Expected outputs after `npm run build`:
- `observatory/web/index.html`
- `observatory/web/assets/index-*.js`
- `observatory/web/assets/index-*.css`

The `observatory/web/` directory is gitignored — do NOT commit built assets.

### 3. `package-lock.json` — DO commit

Even though `node_modules/` is gitignored, `package-lock.json` MUST be committed. It pins transitive deps so Dockerfile's `npm ci` step (Tasks 10+ when the image builds) is reproducible.

### 4. Plan-code drift you may encounter

Historical pattern: plan code blocks occasionally have small issues that surface during execution. Specifically watch for:
- **TypeScript strictness:** `tsconfig.json` has `noUnusedLocals: true` and `noUnusedParameters: true`. The plan's minimal `App.tsx` has no unused symbols, so it should compile. If it doesn't, read the actual error — don't paper over it.
- **Tailwind v3 vs v4:** the plan pins `tailwindcss: ^3.4.0`. v4 has different config syntax. Do NOT upgrade.
- **ESM vs CJS:** `"type": "module"` in package.json means all `.js` files (including `postcss.config.js`) are ESM. The plan's postcss config uses `export default` — correct for ESM.
- **React 18 vs 19:** plan pins React 18.3.x. If npm warns about peer deps from `@react-three/*`, that's expected — React 18 is intentional.

If `npm run build` fails, DO NOT commit. Diagnose the failure, fix it minimally (prefer plan-faithful fixes), and log the divergence in `decisions.md` as a plan-code drift entry.

### 5. `observatory/memory/decisions.md` entries

After the task, append at least one entry:
- `2026-04-21 — Task 9 dependency resolution` — note the resolved versions `npm install` picked (react 18.3.x patch, three 0.163.x, etc.). Useful for reproducibility if Tasks 10–16 hit a dep-compat issue.

Add more entries for anything non-obvious you discovered.

### 6. Directory layout

Final state after Task 9:

```
observatory/web-src/
├── package.json
├── package-lock.json          ← generated by npm install; COMMIT
├── vite.config.ts
├── tsconfig.json
├── tsconfig.node.json
├── tailwind.config.ts
├── postcss.config.js
├── index.html
├── node_modules/              ← gitignored
└── src/
    ├── main.tsx
    ├── App.tsx
    └── index.css
observatory/web/               ← gitignored; regenerated by vite build
├── index.html
└── assets/
```

### 7. Commit discipline

One commit for Task 9 per Principle XII. Stage only:
- All files under `observatory/web-src/` EXCEPT `node_modules/` (already gitignored).
- Any `observatory/memory/decisions.md` updates.
- Do NOT stage `observatory/web/` (gitignored).
- Do NOT stage anything outside `observatory/`.

Use the plan's Step 12 HEREDOC commit message verbatim:

```
observatory: frontend scaffolding (task 9)

Vite + React + TypeScript + Tailwind. Builds to observatory/web/
(gitignored). Dev server proxies /api and /ws to 127.0.0.1:8765.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Stage explicitly: `git add observatory/web-src/ observatory/memory/decisions.md`. Do NOT use `git add -A`.

## Verification gate — MUST pass before commit

```bash
# From repo root:
ls observatory/web-src/package-lock.json       # must exist
ls observatory/web/index.html                  # must exist (vite build output)
cat observatory/web-src/package.json | head -5 # sanity check

# Python suite must remain clean — Task 9 should touch zero Python:
python -m pytest observatory/tests/unit/ -q    # expect 67 passed
python -m ruff check observatory/              # expect clean
```

If any of the above fail, do NOT commit — diagnose first.

## What you'll deliver back

A short written report covering:
1. Confirmation each plan step 1–12 was executed.
2. The actual resolved versions `npm install` chose for the top-level deps (react, three, vite, tailwindcss, typescript).
3. Any plan-code drift you encountered and how you resolved it.
4. The commit SHA you landed.
5. Output of the verification commands above.
6. Any follow-up threads worth logging.

Do NOT paraphrase or summarize away unexpected events — surface them. The spec-compliance reviewer will cross-check this report against your commit.
