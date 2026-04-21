# Implementer prompt — Observatory v1, Task 14: Modulator fog + rhythm pulse

## Context

You are a fresh implementer subagent executing **Task 14** of the Observatory v1 plan in `C:\repos\hive`. Prior state: Tasks 1–13 shipped with review-fixes. Backend suite: **67 unit + 1 component** passing, ruff clean. Frontend: **21 tests** passing (5 store + 3 ws + 13 topicColors). HEAD is `b5e2e8e`.

Task 14 adds two scene-wide ambient channels:
1. **`ModulatorFog`** — weights the six modulator values (cortisol, dopamine, serotonin, norepinephrine, oxytocin, acetylcholine) into an RGB tint applied to `scene.fog` + `scene.background`.
2. **`RhythmPulse`** — scans recent envelopes for `hive/rhythm/{gamma,beta,theta}` and pulses the ambient light amplitude at a perceptually-scaled frequency.

## Authoritative documents (read first)

- **Plan (Task 14):** `observatory/docs/plans/2026-04-20-observatory-plan.md`, `### Task 14:` at line 2828 (spans to line 2965). Complete code blocks verbatim.
- **Sub-project guide:** `observatory/CLAUDE.md`.
- **Spec (modulator→scene semantics):** `observatory/docs/specs/2026-04-20-observatory-design.md` §4.5 — modulator palette + rhythm pulse semantics. The plan's `MODULATOR_HUES` + `WEIGHTS` tables should match spec §4.5.
- **Store contract:** `observatory/web-src/src/store.ts` — `ambient.modulators` is `Partial<Record<modulator_name, number>>`. `envelopes` is the 5000-cap ring.
- **Task 12/13 cache patterns to replicate:** `Regions.tsx` `PHASE_COLOR_CACHE` and `topicColors.ts` `COLOR_CACHE` — pre-built module-level caches of `Color` instances. See §1 and §2 below.
- **Prior decisions log:** `observatory/memory/decisions.md` — entries 63–72 are Tasks 12–13 and contain the drift patterns you'll need.

## Your scope

Execute plan Steps 1–4, in order:

1. Create `observatory/web-src/src/scene/Fog.tsx` (verbatim from plan EXCEPT §1 below).
2. Create `observatory/web-src/src/scene/Rhythm.tsx` (verbatim from plan EXCEPT §2 below).
3. Modify `observatory/web-src/src/scene/Scene.tsx` — add `<ModulatorFog />`, `<RhythmPulse lightRef={ambientRef} />`, and an `ambientRef` on `<ambientLight>`. **Preserve Tasks 11/12/13 `useMemo` memoization** (§3 below).
4. Commit with plan Step 4 HEREDOC verbatim.

You are NOT doing Task 15 (HUD). Stop at Task 14.

## Critical concerns & pre-approved guidance

### 1. `Fog.tsx` — eliminate per-frame `Color` allocations

Plan body allocates `new Color(0.03, 0.03, 0.07)` and `bg.clone()` **every frame**, plus assigns the new-every-frame `target` Color to `scene.background`. At 60 Hz that's 120 Color allocations/sec from Fog alone.

**Pre-approved fix:** hoist the base background to a module-level constant `Color` and keep a single reusable `targetRef` that's mutated in place each frame:

```tsx
import { useFrame, useThree } from '@react-three/fiber';
import { useRef } from 'react';
import { Color, Fog } from 'three';
import { useStore } from '../store';

const MODULATOR_HUES: Record<string, [number, number, number]> = {
  cortisol:       [0.70, 0.20, 0.20],
  dopamine:       [0.90, 0.75, 0.30],
  serotonin:      [0.55, 0.80, 0.40],
  norepinephrine: [0.40, 0.80, 0.90],
  oxytocin:       [0.90, 0.55, 0.70],
  acetylcholine:  [0.80, 0.80, 0.80],
};
const WEIGHTS: Record<string, number> = {
  cortisol: 0.35, dopamine: 0.30, serotonin: 0.15,
  norepinephrine: 0.20, oxytocin: 0.10, acetylcholine: 0.10,
};
const BG_R = 0.03, BG_G = 0.03, BG_B = 0.07;

export function ModulatorFog() {
  const { scene } = useThree();
  const mods = useStore((s) => s.ambient.modulators);
  const targetRef = useRef(new Color(BG_R, BG_G, BG_B));
  useFrame(() => {
    const target = targetRef.current;
    target.setRGB(BG_R, BG_G, BG_B);
    for (const [name, value] of Object.entries(mods)) {
      const v = typeof value === 'number' ? value : 0;
      const hue = MODULATOR_HUES[name] ?? [0, 0, 0];
      const w = (WEIGHTS[name] ?? 0) * Math.max(0, Math.min(1, v));
      target.r = Math.min(1, target.r + hue[0] * w);
      target.g = Math.min(1, target.g + hue[1] * w);
      target.b = Math.min(1, target.b + hue[2] * w);
    }
    if (!scene.fog) scene.fog = new Fog(target, 10, 40);
    else (scene.fog as Fog).color.copy(target);
    scene.background = target;
  });
  return null;
}
```

Note the `new Fog(target, 10, 40)` is called once (gated by `!scene.fog`). Passing `target` directly is safe because `Fog` constructor copies the color internally (verify: three.js source shows `this.color = new Color(color)`). The per-frame branch uses `.color.copy(target)` which writes in place.

`scene.background = target` assigns the same Color reference each frame — three.js accepts Color or Texture for `background`. Reusing the ref means no allocation.

Log as Task 14 drift entry — follows Task 12 entry 67 / Task 13 entry 68 pattern.

### 2. `Rhythm.tsx` — use non-reactive store access, not reactive subscription

Plan's `const envelopes = useStore((s) => s.envelopes);` subscribes `RhythmPulse` to the entire envelopes array. Every `pushEnvelope` call (~50–100 Hz under live traffic) triggers a re-render. `useFrame` already runs 60 Hz — the reactive subscription is redundant and causes React overhead.

**Pre-approved fix:** same pattern as Task 13's `Sparks.tsx` — use `useStore.getState()` inside `useFrame` for non-reactive access:

```tsx
import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';
import { useStore } from '../store';

// Drive a scene-wide ambient-light amplitude from hive/rhythm/{gamma, beta, theta}.

export function RhythmPulse({ lightRef }: { lightRef: React.MutableRefObject<any> }) {
  const latestRef = useRef<{ freq: number } | null>(null);

  useFrame(({ clock }) => {
    const envelopes = useStore.getState().envelopes;
    const slice = envelopes.slice(-20);
    for (let i = slice.length - 1; i >= 0; i--) {
      const t = slice[i].topic;
      if (t === 'hive/rhythm/gamma') { latestRef.current = { freq: 40 }; break; }
      if (t === 'hive/rhythm/beta')  { latestRef.current = { freq: 20 }; break; }
      if (t === 'hive/rhythm/theta') { latestRef.current = { freq: 6  }; break; }
    }
    if (!lightRef.current) return;
    const base = 0.35;
    if (latestRef.current) {
      const amp = 0.03;
      lightRef.current.intensity = base + amp * Math.sin(clock.elapsedTime * 2 * Math.PI * latestRef.current.freq * 0.02);
      // The 0.02 scalar tames 40Hz to a visible ~0.8Hz — perceptual stand-in, not literal frequency.
    } else {
      lightRef.current.intensity = base;
    }
  });
  return null;
}
```

Also dropped the plan's `_dt` parameter since it's unused (prior tasks also hit this; `noUnusedParameters`).

Log as Task 14 drift entry.

### 3. Scene.tsx — MUST preserve `useMemo` for `names`

Plan Step 3 code block AGAIN shows `const names = Object.keys(regions);` without memoization. This is the third time the plan code predates Task 11's review-fix. **Preserve the memoization** — do NOT revert.

**Pre-approved full Scene.tsx:**

```tsx
import { useMemo, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useStore } from '../store';
import { useForceGraph } from './useForceGraph';
import { Regions } from './Regions';
import { Sparks } from './Sparks';
import { ModulatorFog } from './Fog';
import { RhythmPulse } from './Rhythm';

export function Scene() {
  const regions = useStore((s) => s.regions);
  const adjacency = useStore((s) => s.adjacency);
  const names = useMemo(() => Object.keys(regions).sort(), [regions]);
  const nodes = useForceGraph(names, adjacency);
  const ambientRef = useRef<any>(null);
  return (
    <Canvas camera={{ position: [0, 0, 12], fov: 55 }}>
      <ambientLight ref={ambientRef} intensity={0.35} />
      <directionalLight position={[10, 10, 5]} intensity={0.6} />
      <ModulatorFog />
      <RhythmPulse lightRef={ambientRef} />
      <Regions nodesRef={nodes} />
      <Sparks nodesRef={nodes} />
      <OrbitControls />
    </Canvas>
  );
}
```

Note two additional plan details to preserve:
- Plan drops the `style={{ background: '#080814' }}` from `<Canvas>` because `ModulatorFog` now owns `scene.background`. Preserve that drop.
- Plan adds `useRef` import + `ambientRef` + the `ref={ambientRef}` prop on `<ambientLight>`.

### 4. `lightRef: React.MutableRefObject<any>`

Plan uses `any` for the ref type. Consistent with other three.js refs in Tasks 11–13. Don't tighten to `MutableRefObject<THREE.AmbientLight>` — the loose pattern is established.

### 5. `<ModulatorFog />` and `<RhythmPulse />` return `null`

They exist for their `useFrame` side effects only (mutating `scene.fog`, `scene.background`, `lightRef.current.intensity`). Returning `null` is correct — do not wrap in a fragment.

### 6. `useThree().scene` in `Fog.tsx`

`useThree()` is an R3F hook that provides access to the scene/camera/gl. `scene.fog` and `scene.background` are three.js `Scene` properties. Writes from `useFrame` are fine — R3F doesn't batch them.

### 7. No new tests

Task 14 is pure per-frame animation glue. No unit-testable logic. Keep the existing 21 frontend tests green; don't add component tests preemptively.

### 8. Commit discipline

One commit for Task 14. Stage only:
- `observatory/web-src/src/scene/Fog.tsx`
- `observatory/web-src/src/scene/Rhythm.tsx`
- `observatory/web-src/src/scene/Scene.tsx`
- `observatory/memory/decisions.md`
- `observatory/prompts/task-14-modulator-fog-rhythm.md`

Do NOT stage:
- `observatory/web/` (gitignored).
- Any Python files.

Use the plan's Step 4 HEREDOC verbatim:

```
observatory: modulator fog + rhythm pulse (task 14)

ModulatorFog updates scene.fog and scene.background each frame from
the weighted modulator values. RhythmPulse modulates ambient-light
intensity at a perceptually-scaled gamma/beta/theta tempo based on
the most recently observed rhythm topic.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Stage explicitly (NOT `git add -A`):

```
git add observatory/web-src/src/scene/Fog.tsx \
        observatory/web-src/src/scene/Rhythm.tsx \
        observatory/web-src/src/scene/Scene.tsx \
        observatory/memory/decisions.md \
        observatory/prompts/task-14-modulator-fog-rhythm.md
```

## Verification gate — MUST pass before commit

```bash
cd observatory/web-src
npx tsc -b                                                  # clean
npm run build                                               # vite build succeeds
npm run test                                                # 21/21 passed (no new tests)

cd /c/repos/hive
.venv/Scripts/python.exe -m pytest observatory/tests/unit/ -q   # 67 passed
.venv/Scripts/python.exe -m ruff check observatory/             # clean
```

If any fail, DO NOT commit — diagnose first.

## What you'll deliver back

1. Confirmation each plan step 1–4 was executed with the three pre-approved deviations.
2. `npx tsc -b` output (empty = success).
3. `npm run build` output (bundle size; chunk-size warning expected).
4. `npm run test` output (21/21).
5. Any plan-code drift beyond §1/§2/§3 you encountered.
6. Commit SHA.
7. Follow-up threads worth logging.

Do NOT summarize away unexpected events. Surface them.
