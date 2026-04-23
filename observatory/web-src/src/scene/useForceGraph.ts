import { useEffect, useMemo, useRef } from 'react';
import {
  forceSimulation,
  forceManyBody,
  forceLink,
  forceX,
  forceY,
  forceZ,
} from 'd3-force-3d';

export type ForceNode = { id: string; x: number; y: number; z: number; fx?: number; fy?: number; fz?: number };
export type ForceLink = { source: string; target: string; weight: number };

const PERIMETER_BIAS: Record<string, [number, number, number]> = {
  visual_cortex: [-6, -2, 0],
  auditory_cortex: [-6, 2, 0],
  broca_area: [6, -2, 0],
  motor_cortex: [6, 2, 0],
};

export function useForceGraph(names: string[], adjacency: Array<[string, string, number]>) {
  const nodesRef = useRef<Map<string, ForceNode>>(new Map());
  const simRef = useRef<ReturnType<typeof forceSimulation<ForceNode>> | null>(null);

  const namesKey = [...names].sort().join('|');

  // Structural-only adjacency key: pairs present, direction-agnostic. Link
  // weight flickers every 2 s with traffic but doesn't change which regions
  // are bonded — keying on weights would restart the sim indefinitely
  // (spec §5.1 calls for a "smooth transition rather than snapping").
  const adjKey = useMemo(
    () => adjacency.map(([s, t]) => (s < t ? `${s}|${t}` : `${t}|${s}`)).sort().join('~'),
    [adjacency],
  );

  useEffect(() => {
    // Force tuning rationale (spec §5.1: "calm motion, slow jellyfish"):
    //
    // Original tuning (charge -80, bias 0.02, velocityDecay 0.6) let many-body
    // repulsion dominate: with 14 regions and no `forceLink` bonding (backend
    // adjacency starts empty and only fills when routable cross-region
    // traffic is detected), regions flew past the camera frustum within a
    // few seconds. The scene rendered empty even though orbs + edges were
    // mounting correctly — they were just out of view at world positions
    // like (±50, ±50, …).
    //
    // - `charge` -2 — repulsion is just a gentle nudge so two regions can't
    //   overlap into the same pixel, but it can't drive the layout. Spec
    //   §5.1 ("calm motion") means charges are for anti-stacking, not
    //   force-directed layout energy.
    // - `x/y/zBias` strength 1.0 (up from 0.02) — for perimeter regions
    //   (visual/auditory/broca/motor cortex at [±6, ±2, 0]) this pulls them
    //   hard to their quadrant target; for every other region the target is
    //   (0, 0, 0), keeping the cluster tightly centered around the pinned
    //   mPFC at origin. A strong bias is what replaces the missing
    //   `forceLink` gravity when adjacency is empty. Strength 1.0 is high
    //   enough that equilibrium converges to within ~1 world unit of each
    //   region's target, so the [±6, ±2, 0] perimeter regions sit inside
    //   the camera's horizontal field at z=12 FOV 55 aspect 16:10
    //   (half-width ≈ 10 world units).
    // - `velocityDecay` 0.85 (up from 0.6) — strong damping prevents any
    //   transient velocity spike (from a late region joining the cluster
    //   near the pinned mPFC) from flinging the new region off-screen
    //   before the bias catches it.
    const sim = forceSimulation<ForceNode>([], 3)
      .force('charge', forceManyBody().strength(-2))
      .force('xBias', forceX<ForceNode>((d) => PERIMETER_BIAS[d.id]?.[0] ?? 0).strength(1.0))
      .force('yBias', forceY<ForceNode>((d) => PERIMETER_BIAS[d.id]?.[1] ?? 0).strength(1.0))
      .force('zBias', forceZ<ForceNode>((d) => PERIMETER_BIAS[d.id]?.[2] ?? 0).strength(1.0))
      .alphaDecay(0.02)
      // `alphaTarget` 0.05 is the floor alpha decays toward (default 0).
      // With a nonzero target the sim ticks forever at a low energy,
      // which keeps the (strong) bias force pulling drifted regions back
      // toward their targets. Without this, `alpha` decays past
      // `alphaMin` (0.001) and d3 halts the sim; any accumulated charge
      // drift past a region's bias target then becomes permanent.
      //
      // Note: `alphaMin(...)` would be the WRONG knob — that's the
      // threshold at which the sim stops, not the floor it decays to.
      .alphaTarget(0.05)
      .velocityDecay(0.85);
    simRef.current = sim;
    return () => { sim.stop(); simRef.current = null; };
  }, []);

  useEffect(() => {
    const map = nodesRef.current;
    for (const name of names) {
      if (!map.has(name)) {
        // Initialize away from the pinned mPFC at origin. The previous
        // `(Math.random() - 0.5) * 4` sometimes placed late arrivals within
        // epsilon of origin, and with charge strength on close-range pairs,
        // that launched them off-screen in the first few frames. Spread
        // jitter is ±4 around a fixed ±2 radial offset so the smallest
        // possible distance from origin is ~2.
        const [x, y, z] = PERIMETER_BIAS[name] ?? [
          (Math.random() > 0.5 ? 2 : -2) + (Math.random() - 0.5) * 4,
          (Math.random() > 0.5 ? 2 : -2) + (Math.random() - 0.5) * 4,
          (Math.random() > 0.5 ? 2 : -2) + (Math.random() - 0.5) * 4,
        ];
        const node: ForceNode = { id: name, x, y, z };
        if (name === 'medial_prefrontal_cortex') { node.fx = 0; node.fy = 0; node.fz = 0; }
        map.set(name, node);
      }
    }
    if (!simRef.current) return;
    simRef.current.nodes(Array.from(map.values())).alpha(0.3).restart();
  }, [namesKey]);

  useEffect(() => {
    if (!simRef.current) return;
    const links: ForceLink[] = adjacency.map(([s, t, w]) => ({ source: s, target: t, weight: w }));
    simRef.current
      .force('link', forceLink<ForceNode, ForceLink>(links).id((d) => d.id).distance(2.5).strength(0.1))
      // Small warm-up per spec §5.1 ("smooth transition rather than snapping").
      // Full 0.3 kick every 2 s prevented the sim from ever decaying and let
      // many-body repulsion blow the graph apart.
      .alpha(0.1)
      .restart();
    // Key is structural hash, not `adjacency` reference — backend emits a
    // fresh array every 2 s even when pairs are unchanged, and keying on
    // the reference restarted the simulation indefinitely.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [adjKey]);

  return nodesRef;
}
