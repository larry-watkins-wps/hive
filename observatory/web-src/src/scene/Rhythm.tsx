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
