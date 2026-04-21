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
