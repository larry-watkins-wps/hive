import { useEffect, useMemo, useRef } from 'react';
import { forceSimulation, forceManyBody, forceLink, forceX, forceY, forceZ } from 'd3-force-3d';

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

  const nodes = useMemo<ForceNode[]>(() => {
    const map = nodesRef.current;
    for (const name of names) {
      if (!map.has(name)) {
        const [x, y, z] = PERIMETER_BIAS[name] ?? [
          (Math.random() - 0.5) * 4, (Math.random() - 0.5) * 4, (Math.random() - 0.5) * 4,
        ];
        const node: ForceNode = { id: name, x, y, z };
        if (name === 'medial_prefrontal_cortex') { node.fx = 0; node.fy = 0; node.fz = 0; }
        map.set(name, node);
      }
    }
    return Array.from(map.values());
  }, [names]);

  const simRef = useRef<ReturnType<typeof forceSimulation<ForceNode>> | null>(null);

  useEffect(() => {
    const sim = forceSimulation<ForceNode>(nodes, 3)
      .force('charge', forceManyBody().strength(-80))
      .force('xBias', forceX<ForceNode>((d) => PERIMETER_BIAS[d.id]?.[0] ?? 0).strength(0.02))
      .force('yBias', forceY<ForceNode>((d) => PERIMETER_BIAS[d.id]?.[1] ?? 0).strength(0.02))
      .force('zBias', forceZ<ForceNode>((d) => PERIMETER_BIAS[d.id]?.[2] ?? 0).strength(0.02))
      .alphaDecay(0.02)
      .velocityDecay(0.6);
    simRef.current = sim;
    return () => { sim.stop(); };
  }, [nodes]);

  useEffect(() => {
    if (!simRef.current) return;
    const links: ForceLink[] = adjacency.map(([s, t, w]) => ({ source: s, target: t, weight: w }));
    simRef.current
      .force('link', forceLink<ForceNode, ForceLink>(links).id((d) => d.id).distance(2.5).strength(0.1))
      .alpha(0.3)
      .restart();
  }, [adjacency]);

  return nodesRef;
}
