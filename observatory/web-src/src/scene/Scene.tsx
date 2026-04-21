import { useMemo } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useStore } from '../store';
import { useForceGraph } from './useForceGraph';

export function Scene() {
  const regions = useStore((s) => s.regions);
  const adjacency = useStore((s) => s.adjacency);
  const names = useMemo(() => Object.keys(regions).sort(), [regions]);
  const nodes = useForceGraph(names, adjacency);

  // Stub: render a tiny cube at each position so we can verify physics before Task 12.
  // (Remove this block when Task 12 lands.)
  return (
    <Canvas camera={{ position: [0, 0, 12], fov: 55 }} style={{ background: '#080814' }}>
      <ambientLight intensity={0.35} />
      <directionalLight position={[10, 10, 5]} intensity={0.6} />
      {Array.from(nodes.current.values()).map((n) => (
        <mesh key={n.id} position={[n.x, n.y, n.z]}>
          <boxGeometry args={[0.3, 0.3, 0.3]} />
          <meshStandardMaterial color="#6af" />
        </mesh>
      ))}
      <OrbitControls />
    </Canvas>
  );
}
