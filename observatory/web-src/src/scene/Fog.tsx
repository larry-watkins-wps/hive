import { useEffect } from 'react';
import { useThree } from '@react-three/fiber';
import { Color, Fog } from 'three';

// Scene background + fog are hardcoded near-black. Previous versions tinted
// both from modulator values, but that dominated the visual field — the
// modulator bath is already surfaced in the HUD (Self / Modulators panel),
// so keeping the 3D field black lets orb phase colors, sparks, and edge
// pulses read cleanly regardless of modulator state.
const BG_HEX = 0x000000;

export function ModulatorFog() {
  const { scene } = useThree();
  useEffect(() => {
    const bg = new Color(BG_HEX);
    scene.background = bg;
    scene.fog = new Fog(bg, 14, 60);
    return () => {
      // Leave scene.background/fog as-is on unmount; Three handles teardown
      // when the Canvas itself disposes. Nulling them here would briefly
      // flash white during HMR.
    };
  }, [scene]);
  return null;
}
