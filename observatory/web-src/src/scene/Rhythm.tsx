import { useFrame } from '@react-three/fiber';
import { useRef } from 'react';
import { useStore } from '../store';

// Drive a scene-wide ambient-light amplitude from hive/rhythm/{gamma, beta, theta}.

type RhythmState = { freq: number; ts: number };

// After this many ms without a fresh rhythm topic, fall back to flat ambient.
// Prevents the scene from "beating" forever if the brain goes silent.
const RHYTHM_STALE_MS = 5000;

export function RhythmPulse({ lightRef }: { lightRef: React.MutableRefObject<any> }) {
  const latestRef = useRef<RhythmState | null>(null);
  const lastLenRef = useRef(0);

  useFrame(({ clock }) => {
    // Scan only NEW envelopes since last frame for rhythm topics. Avoids
    // the Task 14 plan's `envelopes.slice(-20)` window which could hide
    // rhythm broadcasts under a burst of >20 non-rhythm envelopes per frame.
    const envelopes = useStore.getState().envelopes;
    const newCount = envelopes.length - lastLenRef.current;
    if (newCount > 0) {
      const start = envelopes.length - newCount;
      for (let i = start; i < envelopes.length; i++) {
        const t = envelopes[i].topic;
        if (t === 'hive/rhythm/gamma') { latestRef.current = { freq: 40, ts: performance.now() }; }
        else if (t === 'hive/rhythm/beta')  { latestRef.current = { freq: 20, ts: performance.now() }; }
        else if (t === 'hive/rhythm/theta') { latestRef.current = { freq: 6,  ts: performance.now() }; }
      }
    }
    lastLenRef.current = envelopes.length;

    if (!lightRef.current) return;
    const base = 0.35;
    const latest = latestRef.current;
    if (latest && performance.now() - latest.ts < RHYTHM_STALE_MS) {
      const amp = 0.03;
      lightRef.current.intensity = base + amp * Math.sin(clock.elapsedTime * 2 * Math.PI * latest.freq * 0.02);
      // The 0.02 scalar tames 40Hz to a visible ~0.8Hz — perceptual stand-in, not literal frequency.
    } else {
      lightRef.current.intensity = base;
    }
  });
  return null;
}
