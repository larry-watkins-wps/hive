import { useMemo } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls } from '@react-three/drei';
import { useStore } from '../store';
import { useForceGraph } from './useForceGraph';
import { Regions } from './Regions';
import { Sparks } from './Sparks';

export function Scene() {
  const regions = useStore((s) => s.regions);
  const adjacency = useStore((s) => s.adjacency);
  const names = useMemo(() => Object.keys(regions).sort(), [regions]);
  const nodes = useForceGraph(names, adjacency);
  return (
    <Canvas camera={{ position: [0, 0, 12], fov: 55 }} style={{ background: '#080814' }}>
      <ambientLight intensity={0.35} />
      <directionalLight position={[10, 10, 5]} intensity={0.6} />
      <Regions nodesRef={nodes} />
      <Sparks nodesRef={nodes} />
      <OrbitControls />
    </Canvas>
  );
}
