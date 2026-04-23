import { useEffect, useMemo, useRef } from 'react';
import * as THREE from 'three';
import { useFrame } from '@react-three/fiber';
import { useStore } from '../store';
import type { ForceNode } from './useForceGraph';

// -----------------------------------------------------------------------------
// Reactive adjacency threads (spec §5.3)
//
// One THREE.Line per adjacency pair. At rest each edge is faintly visible at
// opacity 0.08 so scene layout reads even with no traffic. When Sparks.tsx
// spawns a spark for an edge, it bumps the module-level EDGE_PULSE entry —
// pulse=1, color copied from the spark's topic color. Each frame Edges.tsx
// decays pulses at rate 1/0.8s and applies opacity / color formulae.
// -----------------------------------------------------------------------------

// Baseline edges are deliberately very faint — with ~14 regions each
// publishing on base-bundle topics (every region subscribes), the recent
// pair set trends toward the complete graph (~91 edges) during even
// moderate traffic. Dim baseline keeps that dense web subtle; the
// reactive pulse does the actual work of surfacing "who's talking right
// now".
const BASE_COLOR_HEX = 0x3a4a6a;
const BASE_OPACITY = 0.06;
const REACTIVE_GAIN = 0.9;
const DECAY_PER_SEC = 1 / 0.8;

export type EdgePulseEntry = {
  pulse: number;
  color: THREE.Color;
  material: THREE.LineBasicMaterial;
};

/**
 * Module-level pulse map. `Sparks.tsx` writes to this Map to bump an edge's
 * pulse on spark spawn. `Edges.tsx` useFrame reads+decays each entry and
 * applies the opacity/color formulae to the per-edge `LineBasicMaterial`.
 *
 * Key format: undirected canonical — `${min(a,b)}|${max(a,b)}`.
 * Region names are `^[A-Za-z0-9_-]+$` per backend, so `|` is a safe delimiter.
 */
// Module-level singleton: Sparks.tsx writes to this Map during envelope
// spawns; Edges.tsx reads + decays it each frame. Shared mutable state
// across components is the trade-off for decoupling Sparks from Edges'
// component lifecycle (sparks can fire bumps even if Edges is unmounted —
// the `get()?` guard in Sparks silently no-ops in that case).
//
// Caveats to be aware of:
//   - Vitest: this Map persists across test cases in the same test module.
//     Any future test that mutates it must clear the relevant keys in
//     afterEach. Pure-logic tests (`edgeKey`, formula constants) are
//     unaffected — they never touch the Map.
//   - Vite HMR: if Edges.tsx is hot-edited during dev, the new module
//     version gets a fresh Map while Sparks.tsx may still hold the old
//     reference. Full page reload clears the split.
// Promotion to a Zustand slice is a v2.1+ refactor if either caveat bites
// in practice.
export const EDGE_PULSE: Map<string, EdgePulseEntry> = new Map();

/**
 * Undirected canonical edge key. `edgeKey('a', 'b') === edgeKey('b', 'a')`.
 * Sorted alphabetically so the same pair always produces the same string
 * regardless of which region is "source" in a given spark envelope.
 */
export function edgeKey(a: string, b: string): string {
  return a < b ? `${a}|${b}` : `${b}|${a}`;
}

type EdgesProps = {
  /** Scene-wide dim factor (1.0 idle, 0.25 when a region is selected). */
  dimFactor: number;
  /** Shared force-graph positions (same ref FuzzyOrbs / Sparks consume). */
  nodesRef: React.MutableRefObject<Map<string, ForceNode>>;
};

type LineRec = { line: THREE.Line; a: string; b: string };

/**
 * Renders one `THREE.Line` per adjacency pair. Each line owns its own
 * `LineBasicMaterial` (cannot be shared — per-edge opacity/color state)
 * and a 2-vertex `BufferGeometry` whose positions are rewritten each
 * frame from `nodesRef`. Adjacency changes rebuild the line set; stale
 * `EDGE_PULSE` entries are disposed (material + geometry) to avoid
 * leaking GL resources.
 */
export function Edges({ dimFactor, nodesRef }: EdgesProps) {
  const adjacency = useStore((s) => s.adjacency);
  const baselinePairs = useStore((s) => s.baselinePairs);
  const regions = useStore((s) => s.regions);

  // Union of baseline (always-on topology) + active adjacency (recent
  // traffic) pairs, filtered to pairs where BOTH endpoints are registered
  // regions. The backend's ever-seen set legitimately includes sources
  // like `glia` (publisher of rhythms) and filesystem-present regions like
  // `test_self_mod` that aren't in `regions_registry.yaml`; passing those
  // as force-graph links makes `d3-force-3d`'s `forceLink` throw
  // "node not found" and crash the whole r3f canvas. Drop them here.
  const allPairs = useMemo<Array<[string, string]>>(() => {
    const seen = new Set<string>();
    const out: Array<[string, string]> = [];
    const push = (a: string, b: string) => {
      if (!regions[a] || !regions[b]) return;
      const k = edgeKey(a, b);
      if (seen.has(k)) return;
      seen.add(k);
      out.push([a, b]);
    };
    for (const [a, b] of baselinePairs) push(a, b);
    for (const [a, b] of adjacency) push(a, b);
    return out;
  }, [adjacency, baselinePairs, regions]);

  // Stable string identity for the edge set. Contents-based so we skip
  // the rebuild effect when the pair set is structurally unchanged.
  const adjKey = useMemo(
    () => allPairs.map(([a, b]) => edgeKey(a, b)).sort().join('~'),
    [allPairs],
  );

  // Per-edge lines keyed by canonical edge key. Ref (not state) because
  // useFrame mutates `line.geometry.attributes.position.array` in place —
  // reassigning state each frame would re-render the React tree at 60 Hz.
  const linesRef = useRef<Map<string, LineRec>>(new Map());

  // Materialize lines SYNCHRONOUSLY during render, not in useEffect.
  // Previous version ran line creation in an effect, which fires after
  // paint — on the first render after the snapshot arrived with 91
  // baseline pairs, `linesRef.current.get(k)` returned undefined for
  // every pair and the JSX emitted `null`, so no lines rendered until
  // the NEXT store-triggered re-render (up to 2s later via the adjacency
  // delta). Doing the materialization in useMemo(adjKey) is side-effectful
  // but idempotent (we guard via `linesRef.current.has(k)`) and makes
  // lines visible on the very first render that sees the pair.
  useMemo(() => {
    const present = new Set<string>();
    for (const [a, b] of allPairs) {
      const k = edgeKey(a, b);
      present.add(k);
      if (!EDGE_PULSE.has(k)) {
        const mat = new THREE.LineBasicMaterial({
          color: BASE_COLOR_HEX,
          transparent: true,
          opacity: BASE_OPACITY,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        EDGE_PULSE.set(k, {
          pulse: 0,
          color: new THREE.Color(BASE_COLOR_HEX),
          material: mat,
        });
      }
      if (!linesRef.current.has(k)) {
        const geom = new THREE.BufferGeometry();
        const positions = new Float32Array([0, 0, 0, 0, 0, 0]);
        geom.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        const entry = EDGE_PULSE.get(k)!;
        const line = new THREE.Line(geom, entry.material);
        linesRef.current.set(k, { line, a, b });
      }
    }
    // GC stale entries — dispose both GL resources (geometry + material)
    // so WebGL releases the VBOs / program-state.
    for (const k of Array.from(EDGE_PULSE.keys())) {
      if (!present.has(k)) {
        const entry = EDGE_PULSE.get(k);
        entry?.material.dispose();
        EDGE_PULSE.delete(k);
      }
    }
    for (const [k, rec] of Array.from(linesRef.current.entries())) {
      if (!present.has(k)) {
        rec.line.geometry.dispose();
        linesRef.current.delete(k);
      }
    }
  }, [adjKey]);

  // Component-unmount cleanup. Without this, the adjacency-GC loop above
  // is the only path that disposes materials + geometries — which never
  // fires if `<Edges />` itself unmounts (route change, HMR, app teardown)
  // while adjacency pairs are still "present". Dispose everything and
  // clear both maps so nothing GL-ref'd survives.
  useEffect(() => {
    return () => {
      for (const entry of EDGE_PULSE.values()) entry.material.dispose();
      EDGE_PULSE.clear();
      for (const rec of linesRef.current.values()) rec.line.geometry.dispose();
      linesRef.current.clear();
    };
  }, []);

  useFrame((_, dt) => {
    // Clamp dt — avoids an entire pulse draining in one frame after a
    // backgrounded-tab resume. Same pattern as FuzzyOrbs lerp clamp.
    const d = Math.min(dt, 0.05);

    // Update line endpoints from live force-graph positions. nodesRef is
    // mutated in place by the d3-force-3d simulation each tick; we just
    // copy x/y/z to the 6-float position buffer.
    for (const { line, a, b } of linesRef.current.values()) {
      const na = nodesRef.current.get(a);
      const nb = nodesRef.current.get(b);
      if (!na || !nb) continue;
      const positions = (line.geometry as THREE.BufferGeometry).attributes
        .position.array as Float32Array;
      positions[0] = na.x;
      positions[1] = na.y;
      positions[2] = na.z;
      positions[3] = nb.x;
      positions[4] = nb.y;
      positions[5] = nb.z;
      (line.geometry as THREE.BufferGeometry).attributes.position.needsUpdate =
        true;
    }

    // Decay + apply opacity/color formulae. `pulse > 0.01` is the
    // "reactive" branch: material takes the spark color and pulses to
    // ~0.63 opacity. Below threshold, reset to base blue-grey at 0.08
    // opacity — still multiplied by dimFactor so a selected region dims
    // its neighbor edges too (spec §5.3).
    for (const entry of EDGE_PULSE.values()) {
      entry.pulse = Math.max(0, entry.pulse - d * DECAY_PER_SEC);
      if (entry.pulse > 0.01) {
        entry.material.opacity = Math.min(
          1,
          (BASE_OPACITY + REACTIVE_GAIN * entry.pulse) * dimFactor,
        );
        entry.material.color.copy(entry.color);
      } else {
        entry.material.opacity = BASE_OPACITY * dimFactor;
        entry.material.color.setHex(BASE_COLOR_HEX);
      }
    }
  });

  // Render from the unioned `allPairs` set (reactive) rather than
  // `linesRef.current` (ref — no re-render signal). Each `<primitive>` hosts
  // a pre-built THREE.Line keyed by canonical edge key so adjacency churn
  // doesn't swap identities or leak WebGL objects.
  return (
    <group>
      {allPairs.map(([a, b]) => {
        const k = edgeKey(a, b);
        const rec = linesRef.current.get(k);
        if (!rec) return null;
        return <primitive key={k} object={rec.line} />;
      })}
    </group>
  );
}
