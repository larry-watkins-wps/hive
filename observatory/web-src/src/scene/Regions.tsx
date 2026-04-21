import { useMemo, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Color } from 'three';
import { useStore } from '../store';
import type { ForceNode } from './useForceGraph';

const PHASE_COLOR: Record<string, string> = {
  sleep: '#444450',
  wake: '#4a6a8a',
  processing: '#e8e8f0',
  unknown: '#2a2a36',
};

function Region({ node }: { node: ForceNode }) {
  const regions = useStore((s) => s.regions);
  const meta = regions[node.id];
  const meshRef = useRef<any>(null);
  const haloRef = useRef<any>(null);
  const tokensRef = useRef<number>(meta?.stats.tokens_lifetime ?? 0);
  const burnRef = useRef<number>(0);

  useFrame((_, dt) => {
    if (!meshRef.current) return;
    meshRef.current.position.set(node.x, node.y, node.z);
    if (haloRef.current) haloRef.current.position.set(node.x, node.y, node.z);
    if (!meta) return;
    // update burn estimate
    const tokens = meta.stats.tokens_lifetime;
    const delta = Math.max(0, tokens - tokensRef.current);
    tokensRef.current = tokens;
    burnRef.current = burnRef.current * 0.92 + (delta / Math.max(dt, 0.001)) * 0.08;
    const intensity = Math.min(1, burnRef.current / 500); // 500 tok/sec = full glow
    if (haloRef.current) haloRef.current.material.opacity = 0.15 + 0.6 * intensity;
    // base color
    const col = new Color(PHASE_COLOR[meta.stats.phase] ?? PHASE_COLOR.unknown);
    meshRef.current.material.color.lerp(col, Math.min(1, dt * 3));
    // size from queue depth
    const scale = 1 + Math.min(0.3, meta.stats.queue_depth * 0.03);
    meshRef.current.scale.setScalar(scale);
  });

  return (
    <group>
      <mesh ref={meshRef} position={[node.x, node.y, node.z]}>
        <sphereGeometry args={[0.4, 24, 24]} />
        <meshStandardMaterial color={PHASE_COLOR.unknown} />
      </mesh>
      <mesh ref={haloRef} position={[node.x, node.y, node.z]}>
        <sphereGeometry args={[0.6, 16, 16]} />
        <meshBasicMaterial color="#ffc97a" transparent opacity={0.15} depthWrite={false} />
      </mesh>
      <mesh position={[node.x, node.y, node.z]}>
        <torusGeometry args={[0.5, 0.02, 8, Math.max(4, (meta?.stats.handler_count ?? 4))]} />
        <meshBasicMaterial color="#8899aa" />
      </mesh>
    </group>
  );
}

export function Regions({ nodesRef }: { nodesRef: React.MutableRefObject<Map<string, ForceNode>> }) {
  const regions = useStore((s) => s.regions);
  const names = useMemo(() => Object.keys(regions).sort(), [regions]);
  const nodes = useMemo(() => names.map((n) => nodesRef.current.get(n)!).filter(Boolean), [names, nodesRef]);
  return (<>{nodes.map((n) => <Region key={n.id} node={n} />)}</>);
}
