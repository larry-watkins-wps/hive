import { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { useStore, type RegionMeta } from '../store';
import type { ForceNode } from './useForceGraph';
import { getGlowTexture } from './glowTexture';

/**
 * Phase → color hex. `unknown` — emitted by the backend for any region we
 * have seeded from the registry but haven't yet received a heartbeat for —
 * reads as a faint slate-grey so offline/not-yet-booted regions are visibly
 * distinct from live `wake`-blue orbs.
 */
const PHASE_COLOR: Record<string, number> = {
  wake: 0x6aa8ff,
  sleep: 0x3a4458,
  bootstrap: 0x5a8a78,
  shutdown: 0x805a5a,
  processing: 0xffd56a,
  unknown: 0x2e3442,
};

/**
 * Per-region base orb size. Executive (mPFC) gets 1.8× to visually pin
 * the center of the force graph; everything else is unit. Exported so
 * Labels (Task 10) can position its CSS2DObject above the actual orb
 * height instead of a hardcoded offset.
 */
export function regionSize(meta: RegionMeta | undefined): number {
  return meta?.role === 'executive' ? 1.8 : 1.0;
}

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
// Pre-built PhaseBase singletons for the three shapes. useFrame runs at
// ~60 Hz × 14 regions = 840 calls/sec; returning a cached object per phase
// avoids per-frame allocation churn without masking the phase-change signal
// (color equality still identifies a real transition).
const _SLEEP_BASE: PhaseBase = {
  color: PHASE_COLOR.sleep,
  emissive: 0.15,
  coreOpacity: 0.85,
  outerOpacity: 0.10,
  midOpacity: 0.28,
  speckleOpacity: 0.20,
  outerScale: 3.8,
};
const _BOOT_BASE: PhaseBase = {
  color: PHASE_COLOR.bootstrap,
  emissive: 0.35,
  coreOpacity: 0.85,
  outerOpacity: 0.18,
  midOpacity: 0.45,
  speckleOpacity: 0.40,
  outerScale: 4.5,
};
// Offline shape: a region the registry has seeded but we haven't heard from
// yet. Dim core, near-zero glow, narrow outer halo — visibly present so
// layout reads, but clearly not-alive until the first heartbeat arrives.
const _OFFLINE_BASE: PhaseBase = {
  color: PHASE_COLOR.unknown,
  emissive: 0.05,
  coreOpacity: 0.55,
  outerOpacity: 0.04,
  midOpacity: 0.12,
  speckleOpacity: 0.0,
  outerScale: 3.0,
};
// Known-but-non-default phases (`shutdown`, `processing`, and any forward-
// compatible string the backend may emit) land here. Cached per-phase to
// avoid per-frame PhaseBase allocations at 60 Hz × 14 regions.
const _DEFAULT_BASE_CACHE: Record<string, PhaseBase> = {};

export function phaseBase(phase: string): PhaseBase {
  if (phase === 'sleep') return _SLEEP_BASE;
  if (phase === 'bootstrap') return _BOOT_BASE;
  if (phase === 'unknown') return _OFFLINE_BASE;
  const cached = _DEFAULT_BASE_CACHE[phase];
  if (cached) return cached;
  const built: PhaseBase = {
    color: PHASE_COLOR[phase] ?? PHASE_COLOR.unknown,
    emissive: 0.55,
    coreOpacity: 0.85,
    outerOpacity: 0.28,
    midOpacity: 0.65,
    speckleOpacity: 0.60,
    outerScale: 5.2,
  };
  _DEFAULT_BASE_CACHE[phase] = built;
  return built;
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
  // Stable string identity of the region set — useEffect dep arrays compare
  // reference-equal, and `names` is a fresh array each store delta even when
  // contents are unchanged. Keying the publish effect on the joined string
  // stops it from re-firing every heartbeat (same pattern as useForceGraph).
  const namesKey = names.join('|');

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
  // Re-runs only when the region set actually changes (namesKey — not names).
  useEffect(() => {
    refMap.current.clear();
    for (const name of names) {
      const g = groupRefs.current.get(name);
      if (g) refMap.current.set(name, g);
    }
    // namesKey is joined from names; depending on it (not `names`) stops
    // the effect from churning on every store delta.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [namesKey, refMap]);

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
        const size = regionSize(meta);
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
                from the visually soft halos. userData.name lets Labels (Task 10)
                find the region name via ray.hit. stopPropagation is
                defensive for the future case where Labels attach a sibling
                hover-picker; r3f already suppresses onPointerMissed on a
                successful hit, so this is a no-op today. */}
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
