import { useFrame, useThree } from '@react-three/fiber';
import { useRef } from 'react';
import { Color, Fog } from 'three';
import { useStore } from '../store';

// Pre-built modulator → (hue, weight) tuples, iterated per frame without
// per-frame allocation. Order is stable; weights sum to 1.20 (non-normalised
// because we want modulators to compound visually under stress).
const MOD_ENTRIES: ReadonlyArray<readonly [string, readonly [number, number, number], number]> = [
  ['cortisol',       [0.70, 0.20, 0.20], 0.35],
  ['dopamine',       [0.90, 0.75, 0.30], 0.30],
  ['serotonin',      [0.55, 0.80, 0.40], 0.15],
  ['norepinephrine', [0.40, 0.80, 0.90], 0.20],
  ['oxytocin',       [0.90, 0.55, 0.70], 0.10],
  ['acetylcholine',  [0.80, 0.80, 0.80], 0.10],
];
const BG_R = 0.03, BG_G = 0.03, BG_B = 0.07;

export function ModulatorFog() {
  const { scene } = useThree();
  const mods = useStore((s) => s.ambient.modulators);
  const targetRef = useRef(new Color(BG_R, BG_G, BG_B));
  useFrame(() => {
    const target = targetRef.current;
    target.setRGB(BG_R, BG_G, BG_B);
    for (const [name, hue, weight] of MOD_ENTRIES) {
      const raw = mods[name as keyof typeof mods];
      const v = typeof raw === 'number' ? raw : 0;
      const w = weight * Math.max(0, Math.min(1, v));
      target.r = Math.min(1, target.r + hue[0] * w);
      target.g = Math.min(1, target.g + hue[1] * w);
      target.b = Math.min(1, target.b + hue[2] * w);
    }
    // three.js Fog constructor copies the color internally (Fog.js:11), so
    // first-frame construction snapshots `target`; subsequent frames need
    // an explicit `.color.copy(target)` to keep the fog in sync.
    // `scene.background = target` aliases by reference, so it only needs
    // to be set once — WebGLBackground reads `.r/.g/.b` live every frame.
    if (!scene.fog) {
      scene.fog = new Fog(target, 10, 40);
      scene.background = target;
    } else {
      (scene.fog as Fog).color.copy(target);
    }
  });
  return null;
}
