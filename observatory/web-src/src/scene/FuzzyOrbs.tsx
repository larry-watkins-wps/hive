import { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { useStore, type RegionMeta } from '../store';
import type { ForceNode } from './useForceGraph';
import { getGlowTexture } from './glowTexture';

/**
 * Phase → color hex. Wake/unknown share the same blue so unrecognized phase
 * strings fall back to a sensible baseline instead of going black.
 */
const PHASE_COLOR: Record<string, number> = {
  wake: 0x6aa8ff,
  sleep: 0x3a4458,
  bootstrap: 0x5a8a78,
  shutdown: 0x805a5a,
  processing: 0xffd56a,
  unknown: 0x6aa8ff,
};

export type PhaseBase = {
  color: number;
  emissive: number;
  coreOpacity: number;
  outerOpacity: number;
  midOpacity: number;
  speckleOpacity: number;
  outerScale: number;
};

/**
 * Phase-dependent base values for the five-layer orb. Sleep dims everything;
 * bootstrap is a middle state; wake (and anything else) uses the high-energy
 * defaults. Exported so tests can pin the numbers and the rest of the scene
 * can reuse the color map if needed.
 *
 * Spec §5.1 tables the exact scale/opacity/emissive numbers per layer.
 */
export function phaseBase(phase: string): PhaseBase {
  if (phase === 'sleep') {
    return {
      color: PHASE_COLOR.sleep,
      emissive: 0.15,
      coreOpacity: 0.85,
      outerOpacity: 0.10,
      midOpacity: 0.28,
      speckleOpacity: 0.20,
      outerScale: 3.8,
    };
  }
  if (phase === 'bootstrap') {
    return {
      color: PHASE_COLOR.bootstrap,
      emissive: 0.35,
      coreOpacity: 0.85,
      outerOpacity: 0.18,
      midOpacity: 0.45,
      speckleOpacity: 0.40,
      outerScale: 4.5,
    };
  }
  return {
    color: PHASE_COLOR[phase] ?? PHASE_COLOR.unknown,
    emissive: 0.55,
    coreOpacity: 0.85,
    outerOpacity: 0.28,
    midOpacity: 0.65,
    speckleOpacity: 0.60,
    outerScale: 5.2,
  };
}

type FuzzyOrbsProps = {
  /** Dim non-selected regions. 1.0 when nothing is selected, 0.25 otherwise. */
  dimFactor: number;
  /** Click handler fired by the invisible picker mesh. */
  onRegionClick: (name: string) => void;
  /** Parent-owned Map; FuzzyOrbs publishes each region's group here for the
   *  camera-focus hook in Scene.tsx (Task 8) and Labels (Task 10). */
  refMap: React.MutableRefObject<Map<string, THREE.Object3D>>;
  /** Live force-graph node positions. Mutated in place by the simulation; we
   *  just read x/y/z each frame and copy to the group's transform. */
  nodesRef: React.MutableRefObject<Map<string, ForceNode>>;
};

/**
 * Per-region five-mesh group: outer halo sprite, mid halo sprite, shaded
 * core sphere, white speckle sprite, invisible picker mesh. All sprites
 * use additive blending against `GLOW_TEX` for a soft-glow look. Core is
 * `MeshStandardMaterial` so directional lighting reads parallax.
 *
 * Phase changes lerp opacity and `emissiveIntensity` toward `phaseBase(phase)`
 * at rate `dt / 0.8` — ~800 ms to reach 63% of the new value. Dim factor
 * multiplies all four visible layers' opacity for non-selected regions; the
 * selected region (if any) always renders at full intensity.
 */
export function FuzzyOrbs({ dimFactor, onRegionClick, refMap, nodesRef }: FuzzyOrbsProps) {
  const regions = useStore((s) => s.regions);
  const selectedRegion = useStore((s) => s.selectedRegion);
  const names = useMemo(() => Object.keys(regions).sort(), [regions]);

  // Per-region material / group refs, keyed by region name. Callback refs
  // populate these on mount; useFrame reads them to drive the phase lerp.
  const groupRefs = useRef<Map<string, THREE.Group>>(new Map());
  const coreMatRefs = useRef<Map<string, THREE.MeshStandardMaterial>>(new Map());
  const outerMatRefs = useRef<Map<string, THREE.SpriteMaterial>>(new Map());
  const midMatRefs = useRef<Map<string, THREE.SpriteMaterial>>(new Map());
  const speckleMatRefs = useRef<Map<string, THREE.SpriteMaterial>>(new Map());

  // Per-region phase target. When stats.phase changes, the target is
  // swapped and useFrame smoothly lerps all four layers to the new values.
  const phaseTargets = useRef<Map<string, PhaseBase>>(new Map());

  // Publish group refs to the parent's Map so Scene.tsx's camera focus hook
  // (Task 8) and Labels (Task 10) can raycast / fitToBox the selected region.
  // Re-runs when `names` changes (regions appear / disappear from the store).
  useEffect(() => {
    refMap.current.clear();
    for (const name of names) {
      const g = groupRefs.current.get(name);
      if (g) refMap.current.set(name, g);
    }
  }, [names, refMap]);

  useFrame((_, dt) => {
    // Clamp dt — avoids huge lerps after a tab backgrounds for minutes.
    const d = Math.min(dt, 0.05);
    const lerpRate = d / 0.8; // 800 ms to ~63% of target (spec §5.1)

    for (const name of names) {
      const group = groupRefs.current.get(name);
      const node = nodesRef.current.get(name);
      if (!group || !node) continue;

      // Position follows the force-graph simulation.
      group.position.set(node.x, node.y, node.z);

      // Resolve the phase target — recompute only when the color changes
      // (phase transition); otherwise the cached target is still correct.
      const meta: RegionMeta | undefined = regions[name];
      const phase = meta?.stats?.phase ?? 'unknown';
      const currentTarget = phaseTargets.current.get(name);
      const nextTarget = phaseBase(phase);
      if (!currentTarget || currentTarget.color !== nextTarget.color) {
        phaseTargets.current.set(name, nextTarget);
      }
      const target = phaseTargets.current.get(name)!;

      // Selected region stays at full opacity; everything else is dimmed
      // when some region is selected. When nothing is selected, dimFactor
      // should be 1.0 and effectiveDim is 1.0 for every region.
      const effectiveDim = selectedRegion != null && selectedRegion !== name ? dimFactor : 1.0;

      const coreMat = coreMatRefs.current.get(name);
      if (coreMat) {
        coreMat.emissiveIntensity += (target.emissive - coreMat.emissiveIntensity) * lerpRate;
        coreMat.opacity += (target.coreOpacity * effectiveDim - coreMat.opacity) * lerpRate;
        coreMat.color.setHex(target.color);
        coreMat.emissive.setHex(target.color);
      }
      const outer = outerMatRefs.current.get(name);
      if (outer) {
        outer.opacity += (target.outerOpacity * effectiveDim - outer.opacity) * lerpRate;
        outer.color.setHex(target.color);
      }
      const mid = midMatRefs.current.get(name);
      if (mid) {
        mid.opacity += (target.midOpacity * effectiveDim - mid.opacity) * lerpRate;
        mid.color.setHex(target.color);
      }
      const speck = speckleMatRefs.current.get(name);
      if (speck) {
        // Speckle color is always white (hot-core feel); only opacity lerps.
        speck.opacity += (target.speckleOpacity * effectiveDim - speck.opacity) * lerpRate;
      }
    }
  });

  // Resolve the singleton lazily on first render. In a live scene this
  // runs once; under jsdom-based tests FuzzyOrbs is never mounted so the
  // canvas-dependent build never fires at import time.
  const glowTex = getGlowTexture();

  return (
    <group>
      {names.map((name) => {
        const meta = regions[name];
        // Placeholder size heuristic — v1 did not differentiate region size.
        // Executive (mPFC) renders larger so the center-pin stands out.
        const size = meta?.role === 'executive' ? 1.8 : 1.0;
        const initial = phaseBase(meta?.stats?.phase ?? 'unknown');
        const outerScale = size * initial.outerScale;
        const midScale = size * 2.6;
        const speckleScale = size * 0.9;

        return (
          <group
            key={name}
            ref={(el) => {
              if (el) groupRefs.current.set(name, el);
            }}
          >
            {/* Outer halo — widest sprite, softest alpha, additive. */}
            <sprite scale={[outerScale, outerScale, 1]}>
              <spriteMaterial
                attach="material"
                ref={(m: any) => {
                  if (m) outerMatRefs.current.set(name, m);
                }}
                map={glowTex}
                color={initial.color}
                transparent
                opacity={initial.outerOpacity}
                depthWrite={false}
                blending={THREE.AdditiveBlending}
              />
            </sprite>
            {/* Mid halo — tighter glow, higher opacity. */}
            <sprite scale={[midScale, midScale, 1]}>
              <spriteMaterial
                attach="material"
                ref={(m: any) => {
                  if (m) midMatRefs.current.set(name, m);
                }}
                map={glowTex}
                color={initial.color}
                transparent
                opacity={initial.midOpacity}
                depthWrite={false}
                blending={THREE.AdditiveBlending}
              />
            </sprite>
            {/* Core — shaded sphere for 3D parallax under directional light. */}
            <mesh>
              <sphereGeometry args={[size * 0.55, 32, 24]} />
              <meshStandardMaterial
                ref={(m: any) => {
                  if (m) coreMatRefs.current.set(name, m);
                }}
                color={initial.color}
                emissive={initial.color}
                emissiveIntensity={initial.emissive}
                roughness={0.9}
                metalness={0}
                transparent
                opacity={initial.coreOpacity}
              />
            </mesh>
            {/* Speckle — tiny bright white dot for a hot-core highlight. */}
            <sprite scale={[speckleScale, speckleScale, 1]}>
              <spriteMaterial
                attach="material"
                ref={(m: any) => {
                  if (m) speckleMatRefs.current.set(name, m);
                }}
                map={glowTex}
                color={0xffffff}
                transparent
                opacity={initial.speckleOpacity}
                depthWrite={false}
                blending={THREE.AdditiveBlending}
              />
            </sprite>
            {/* Invisible picker — sole raycast target; decouples click/hover
                from the visually soft halos. userData.name lets Labels find
                the region name via ray.hit. stopPropagation prevents the
                Canvas onPointerMissed from firing right after a pick. */}
            <mesh
              onClick={(e) => {
                e.stopPropagation();
                onRegionClick(name);
              }}
              userData={{ name }}
            >
              <sphereGeometry args={[size * 1.2, 16, 12]} />
              <meshBasicMaterial visible={false} />
            </mesh>
          </group>
        );
      })}
    </group>
  );
}
