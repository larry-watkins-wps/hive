import { useEffect, useMemo, useRef } from 'react';
import { Canvas } from '@react-three/fiber';
import { CameraControls } from '@react-three/drei';
import * as THREE from 'three';
import { useStore } from '../store';
import { useForceGraph } from './useForceGraph';
import { Regions } from './Regions';
import { Sparks } from './Sparks';
import { ModulatorFog } from './Fog';
import { RhythmPulse } from './Rhythm';

export function Scene() {
  const regions = useStore((s) => s.regions);
  const adjacency = useStore((s) => s.adjacency);
  const selectedRegion = useStore((s) => s.selectedRegion);
  const names = useMemo(() => Object.keys(regions).sort(), [regions]);
  const nodes = useForceGraph(names, adjacency);
  const ambientRef = useRef<any>(null);
  const cameraControlsRef = useRef<CameraControls>(null);
  // Populated by Task 9's FuzzyOrbs via callback refs; read by the focus hook
  // below and by Task 10's Labels. Mutating a ref Map does not trigger React
  // re-renders, which is the desired behavior here — scene updates happen in
  // the r3f render loop, not via React state.
  const regionMeshRefs = useRef<Map<string, THREE.Object3D>>(new Map());

  // Focus hook: fit the camera to the selected region's mesh, or reset when
  // nothing is selected. Tasks 9/10 populate regionMeshRefs; until then the
  // `fitToBox` path is a no-op because the map is empty.
  useEffect(() => {
    const ctrl = cameraControlsRef.current;
    if (!ctrl) return;
    if (selectedRegion == null) {
      ctrl.reset(true);
      return;
    }
    const target = regionMeshRefs.current.get(selectedRegion);
    if (!target) return;
    const box = new THREE.Box3().setFromObject(target);
    ctrl.fitToBox(box, true, {
      paddingTop: 0.5,
      paddingLeft: 0.5,
      paddingRight: 0.5,
      paddingBottom: 0.5,
    });
  }, [selectedRegion]);

  // Global camera-reset event, dispatched by Task 12's `R` key handler.
  // Installing the listener here (rather than exposing the ref) keeps the
  // keys hook decoupled from the CameraControls instance.
  useEffect(() => {
    const onReset = () => cameraControlsRef.current?.reset(true);
    window.addEventListener('observatory:camera-reset', onReset);
    return () => window.removeEventListener('observatory:camera-reset', onReset);
  }, []);

  // 1.0 normal, 0.25 when any region is selected. Threaded into Tasks 9/10/11
  // child components once they mount.
  const _dimFactor = selectedRegion == null ? 1.0 : 0.25;
  void _dimFactor; // consumed by FuzzyOrbs/Edges/Labels (Tasks 9-11)

  return (
    <Canvas
      camera={{ position: [0, 0, 12], fov: 55 }}
      onPointerMissed={() => useStore.getState().select(null)}
    >
      <ambientLight ref={ambientRef} intensity={0.35} />
      <directionalLight position={[10, 10, 5]} intensity={0.6} />
      <ModulatorFog />
      <RhythmPulse lightRef={ambientRef} />
      <Regions nodesRef={nodes} />
      <Sparks nodesRef={nodes} />
      <CameraControls
        ref={cameraControlsRef}
        minDistance={10}
        maxDistance={140}
        dampingFactor={0.08}
      />
    </Canvas>
  );
}
