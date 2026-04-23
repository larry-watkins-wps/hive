import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import { Color, InstancedMesh, Matrix4, Vector3 } from 'three';
import { useStore } from '../store';
import { topicColorObject } from './topicColors';
import type { ForceNode } from './useForceGraph';
import { EDGE_PULSE, edgeKey } from './Edges';

const MAX_SPARKS = 2000;
const LIFETIME = 1.2; // seconds — long enough to track, short enough to stay light
const SPARK_RADIUS = 0.035; // tiny pinprick dot — additive blending still pops against black

type Spark = {
  src: Vector3;
  dst: Vector3;
  t0: number;
  color: Color;
};

export function Sparks({ nodesRef }: { nodesRef: React.MutableRefObject<Map<string, ForceNode>> }) {
  const meshRef = useRef<InstancedMesh>(null);
  const sparks = useRef<Spark[]>([]);
  const lastLenRef = useRef(0);

  // Force count to 0 on first mount so the default MAX_SPARKS instances
  // don't flash at the origin (identity matrices) before useFrame runs.
  // Has to be a layout effect so it lands before the first paint.
  useEffect(() => {
    if (meshRef.current) meshRef.current.count = 0;
  }, []);

  // Subscribe to envelope appends by polling the envelopes array length each frame.
  useFrame((state) => {
    const store = useStore.getState();
    const envs = store.envelopes;
    const newCount = envs.length - lastLenRef.current;
    if (newCount > 0) {
      // Prefer freshness: if a burst >100 arrived in one frame, take the last 100.
      const slice = envs.slice(envs.length - Math.min(newCount, 100));
      for (const e of slice) {
        if (!e.source_region || e.destinations.length === 0) continue;
        const src = nodesRef.current.get(e.source_region);
        if (!src) continue;
        // Drift fix (decisions entry 68): reuse pre-built Color from topicColors
        // cache instead of allocating per envelope. At 50-100 env/sec with 1-3
        // destinations, this avoids 50-300 Color allocations/sec.
        const color = topicColorObject(e.topic);
        for (const dname of e.destinations) {
          const dst = nodesRef.current.get(dname);
          if (!dst) continue;
          if (sparks.current.length >= MAX_SPARKS) sparks.current.shift();
          // Snapshot positions at spawn. Sparks may miss moving targets during
          // force-graph settle (first seconds after mount or topology change).
          // Acceptable v1 tradeoff; v2 could look up live positions each frame.
          sparks.current.push({
            src: new Vector3(src.x, src.y, src.z),
            dst: new Vector3(dst.x, dst.y, dst.z),
            t0: state.clock.elapsedTime,
            color,
          });
          // Task 11 / spec §5.3: bump the reactive thread between src+dst.
          // Bump happens only for edges that Edges.tsx has materialized (i.e.
          // pairs present in the server-side adjacency Map); sparks that
          // travel along undeclared edges (e.g. direct-send envelopes) still
          // render their traveling dot but don't pulse a thread.
          const ek = edgeKey(e.source_region, dname);
          const entry = EDGE_PULSE.get(ek);
          if (entry) {
            entry.pulse = 1.0;
            entry.color.copy(color);
          }
        }
      }
    }
    lastLenRef.current = envs.length;

    if (!meshRef.current) return;
    const m = new Matrix4();
    const pos = new Vector3();
    const scale = new Vector3();
    const quat = new THREE.Quaternion();
    let i = 0;
    for (const s of sparks.current) {
      const age = state.clock.elapsedTime - s.t0;
      if (age > LIFETIME) continue;
      const t = age / LIFETIME;
      pos.lerpVectors(s.src, s.dst, t);
      // Subtle size envelope — grow briefly at spawn, fade in the last
      // third. Multiplier stays in [0.6, 1.0] so sparks never balloon.
      const sizeMul = t < 0.15 ? t / 0.15 : t > 0.75 ? (1 - t) / 0.25 : 1.0;
      const s3 = 0.6 + 0.4 * sizeMul;
      scale.set(s3, s3, s3);
      m.compose(pos, quat, scale);
      meshRef.current.setMatrixAt(i, m);
      meshRef.current.setColorAt(i, s.color);
      i++;
    }
    meshRef.current.count = i;
    meshRef.current.instanceMatrix.needsUpdate = true;
    if (meshRef.current.instanceColor) meshRef.current.instanceColor.needsUpdate = true;
    // prune expired
    sparks.current = sparks.current.filter((s) => state.clock.elapsedTime - s.t0 <= LIFETIME);
  });

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined as any, undefined as any, MAX_SPARKS]}
      frustumCulled={false}
    >
      {/* Baseline radius × per-instance scale pulse (useFrame above) lets
          sparks read as traveling lights, not rigid dots. Additive blending
          over black background pops the topic color; depthWrite off so
          overlapping sparks sum correctly; toneMapped off so the topic
          color lands on-screen at full intensity instead of being crushed. */}
      <sphereGeometry args={[SPARK_RADIUS, 16, 12]} />
      <meshBasicMaterial
        transparent
        opacity={1.0}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
        toneMapped={false}
      />
    </instancedMesh>
  );
}
