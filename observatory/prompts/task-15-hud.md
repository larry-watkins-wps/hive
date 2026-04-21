# Implementer prompt — Observatory v1, Task 15: HUD (self panel + modulators + counters)

## Context

You are a fresh implementer subagent executing **Task 15** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–14 shipped with review-fixes. Backend suite: **67 unit + 1 component** passing, ruff clean. Frontend: **21 tests** passing, `tsc -b` + `vite build` clean. HEAD is `0c41ebb`.

Task 15 is **pure DOM overlay** — the first HUD work in the project. No three.js, no `useFrame`. Four React components (`SelfPanel`, `Modulators`, `Counters`, wrapper `Hud`) styled with Tailwind, layered above the `<Canvas>` via absolute positioning. Reads state from the zustand store using standard (reactive) selectors.

## Authoritative documents (read first)

- **Plan (Task 15):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 15:` at line 2970 (spans to line 3117). Complete code blocks verbatim.
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Store contract:** `observatory/web-src/src/store.ts` — `ambient.self` (identity / developmental_stage / age / felt_state), `ambient.modulators`, `regions`, `envelopes`.
- **Tailwind palette:** `observatory/web-src/tailwind.config.ts` — `hive.bg`, `hive.panel`, `hive.ink` defined in Task 9.
- **Timestamp semantics gotcha (CRITICAL — see §1):** `observatory/types.py:11` — `observed_at: float` is `time.monotonic()` **on the Python server**. `performance.now()` in the browser is also monotonic but from a **different origin** (page load vs. Python process start). They are NOT comparable. The plan's `Counters.tsx` has a subtle clock-origin bug.
- **Prior decisions log:** `observatory/memory/decisions.md` — entries 46–79 cover prior tasks; patterns you'll reference: Task 10's `MODULATOR_NAMES` type guard; Task 13+14's `useStore.getState()` non-reactive reads.

## Your scope

Execute plan Steps 1–6, in order:

1. Create `observatory/web-src/src/hud/SelfPanel.tsx` (verbatim).
2. Create `observatory/web-src/src/hud/Modulators.tsx` (verbatim).
3. Create `observatory/web-src/src/hud/Counters.tsx` — **WITH the pre-approved `observed_at` clock fix and setInterval re-subscription fix (§1 below).**
4. Create `observatory/web-src/src/hud/Hud.tsx` (verbatim).
5. Modify `observatory/web-src/src/App.tsx` — **preserve the Task 11 strict-mode safety comment** (§2 below).
6. Commit with plan Step 6 HEREDOC verbatim.

You are NOT doing Task 16 (final integration). Stop at Task 15.

## Critical concerns & pre-approved guidance

### 1. `Counters.tsx` — two bugs in the plan, pre-approved fix

Plan Step 3 has two problems:

**Bug A — Clock-origin mismatch on `observed_at`.** Plan line 3045–3046:

```tsx
const now = performance.now() / 1000;
const recent = envelopes.filter((e) => now - e.observed_at < 5).length;
```

`observed_at` is set by `observatory/mqtt_subscriber.py:168` via `time.monotonic()` — Python's process-local monotonic clock. `performance.now()` in the browser is also monotonic, but its epoch is page load (browser process start). These two clocks have unrelated origins. The subtraction produces garbage: either always zero or always huge, depending on which process started first.

**Bug B — `useEffect([envelopes])` tears down and rebuilds the `setInterval` on every envelope push** (~50–100 Hz under live traffic). That's clear/set churn for a 1-second cadence. Same class of subscription-drift bug Task 14 fixed in Rhythm.tsx.

**Pre-approved fix for both** — compute msg/s as a length-delta over a rolling window instead of filtering by timestamp, and use `useStore.getState()` non-reactively so the effect runs once:

```tsx
import { useStore } from '../store';
import { useEffect, useRef, useState } from 'react';

export function Counters() {
  const regions = useStore((s) => s.regions);
  const [rate, setRate] = useState(0);
  const samplesRef = useRef<number[]>([]);   // length samples, one per second, last 6 kept

  useEffect(() => {
    const id = setInterval(() => {
      const envs = useStore.getState().envelopes;
      samplesRef.current.push(envs.length);
      if (samplesRef.current.length > 6) samplesRef.current.shift();
      const earliest = samplesRef.current[0];
      const seconds = samplesRef.current.length - 1;
      setRate(seconds > 0 ? (envs.length - earliest) / seconds : 0);
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const totalTokens = Object.values(regions).reduce(
    (a, r: any) => a + (r.stats?.tokens_lifetime ?? 0),
    0,
  );
  return (
    <div className="flex gap-6 text-xs px-3 py-2 bg-hive-panel/80 backdrop-blur rounded-md">
      <div><span className="opacity-60">Tokens total: </span><span className="tabular-nums">{totalTokens}</span></div>
      <div><span className="opacity-60">Msg/s: </span><span className="tabular-nums">{rate.toFixed(1)}</span></div>
    </div>
  );
}
```

Key properties:
- Clock-agnostic — doesn't rely on cross-process timestamp comparison.
- The ring of 6 samples covers a 5-second window (6 snapshots ≈ 5 seconds of gaps at 1/s cadence).
- The setInterval runs exactly once (empty `[]` deps).
- `regions` is still selected reactively so `totalTokens` updates when region stats change.
- **Caveat:** if envelopes arrive in bursts, the per-second snapshot smooths the rate naturally — that's the desired semantic.
- **Caveat:** during the first second post-mount, `rate` stays at 0 until at least two samples accumulate. Acceptable.

Log as a Task 15 drift entry in `decisions.md` — cite `observatory/types.py:11` for the clock-origin reality and reference Task 14 entries 77–78 for the non-reactive-polling pattern.

### 2. App.tsx — preserve Task 11 strict-mode safety comment

Current `App.tsx` (post Task 11 review-fix) has this comment block above the `useEffect`:

```tsx
  // Strict-mode safe: connect() returns a cleanup that closes the socket; the
  // double mount/unmount in dev is absorbed by the reconnect guard in ws.ts.
  useEffect(() => connect(useStore), []);
```

Plan Step 5's `App.tsx` verbatim **does not show this comment**. The plan-verbatim is from an earlier draft. **Preserve the comment.** No other change to the `useEffect` line.

**Pre-approved full `App.tsx`:**

```tsx
import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { Hud } from './hud/Hud';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  // Strict-mode safe: connect() returns a cleanup that closes the socket; the
  // double mount/unmount in dev is absorbed by the reconnect guard in ws.ts.
  useEffect(() => connect(useStore), []);
  return (
    <div className="relative w-full h-full">
      <Scene />
      <Hud />
    </div>
  );
}
```

### 3. Other Task 15 details — verify but trust the plan

- **`SelfPanel.tsx`** — verbatim. `self.age ?? '—'` renders `—` when age is undefined. Tailwind `line-clamp-2` works (Tailwind 3.3+ built-in; we're on 3.4.19).
- **`Modulators.tsx`** — verbatim. `ORDER` is a tuple of six modulator names matching `MODULATOR_NAMES` from Task 10 (entry 55). `Gauge` component shows `value.toFixed(2)` — strings allocate per render but Modulators only re-renders when `mods` changes (rare).
- **`Hud.tsx`** — verbatim. Two `absolute`-positioned divs, `pointer-events-none` so clicks pass through to the Canvas below.

### 4. No new tests required

Plan adds no tests. HUD components are thin — snapshot testing would need `@testing-library/react` + `jsdom` which are not project deps. Don't add preemptively. Existing 21 frontend tests must remain green.

### 5. React strict-mode double-mount

Task 11's `App.tsx` handles this via the Task 10 WS reconnect guard. Task 15 adds the HUD as a sibling of `<Scene>` — same `<div className="relative w-full h-full">` container. No new concerns.

### 6. Commit discipline

One commit for Task 15. Stage only:
- `observatory/web-src/src/hud/SelfPanel.tsx`
- `observatory/web-src/src/hud/Modulators.tsx`
- `observatory/web-src/src/hud/Counters.tsx`
- `observatory/web-src/src/hud/Hud.tsx`
- `observatory/web-src/src/App.tsx`
- `observatory/memory/decisions.md`
- `observatory/prompts/task-15-hud.md`

Do NOT stage:
- `observatory/web/` (gitignored).
- Any Python files.

Use the plan's Step 6 HEREDOC verbatim:

```
observatory: HUD — self panel + modulator gauges + counters (task 15)

Fixed overlay: top-left shows identity / stage / age / felt_state and
six modulator gauges. Bottom strip shows total lifetime tokens across
regions and a 5-second rolling msg/s.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Stage explicitly (NOT `git add -A`):

```
git add observatory/web-src/src/hud/ \
        observatory/web-src/src/App.tsx \
        observatory/memory/decisions.md \
        observatory/prompts/task-15-hud.md
```

## Verification gate — MUST pass before commit

```bash
cd observatory/web-src
npx tsc -b                                                  # clean
npm run build                                               # vite build succeeds
npm run test                                                # 21/21 passed

cd /c/repos/hive
.venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q   # 67 passed
.venv/Scripts/python.exe -m ruff check observatory/             # clean
```

If any fail, DO NOT commit — diagnose first.

## What you'll deliver back

1. Confirmation each plan step 1–6 was executed with the two pre-approved deviations (Counters §1, App.tsx §2).
2. `npx tsc -b` output (empty = success).
3. `npm run build` output (bundle size; chunk-size warning expected).
4. `npm run test` output (21/21).
5. Any plan-code drift beyond §1/§2 you encountered.
6. Commit SHA.
7. Follow-up threads worth logging.

Do NOT summarize away unexpected events. Surface them.
