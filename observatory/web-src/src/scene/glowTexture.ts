import * as THREE from 'three';

/**
 * Module-level singleton: a radial-gradient soft-glow canvas texture used
 * by every FuzzyOrb sprite layer (outer halo, mid halo, speckle). Generated
 * lazily on first access so modules that merely import `FuzzyOrbs` for
 * pure-logic testing under jsdom (no canvas backend) do not crash at
 * import time. Once built it is reused across all 14 regions so we never
 * pay the canvas draw cost more than once.
 *
 * Spec §5.1: 256x256 radial gradient, stops [0, 0.18, 0.4, 0.7, 1.0] at
 * alpha [1.0, 0.65, 0.22, 0.06, 0.0], white, sRGB color space.
 */
function _buildGlowTexture(): THREE.Texture {
  const c = document.createElement('canvas');
  c.width = c.height = 256;
  const g = c.getContext('2d')!;
  const rg = g.createRadialGradient(128, 128, 0, 128, 128, 128);
  rg.addColorStop(0.00, 'rgba(255,255,255,1.00)');
  rg.addColorStop(0.18, 'rgba(255,255,255,0.65)');
  rg.addColorStop(0.40, 'rgba(255,255,255,0.22)');
  rg.addColorStop(0.70, 'rgba(255,255,255,0.06)');
  rg.addColorStop(1.00, 'rgba(255,255,255,0.00)');
  g.fillStyle = rg;
  g.fillRect(0, 0, 256, 256);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.needsUpdate = true;
  return tex;
}

let _cached: THREE.Texture | null = null;

/**
 * Lazy singleton accessor. First caller in a real browser pays the canvas
 * build; subsequent calls return the cached texture. In a jsdom test that
 * never actually mounts FuzzyOrbs, this never runs and imports stay safe.
 */
export function getGlowTexture(): THREE.Texture {
  if (_cached == null) _cached = _buildGlowTexture();
  return _cached;
}
