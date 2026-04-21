import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { Hud } from './hud/Hud';
import { Inspector } from './inspector/Inspector';
import { useInspectorKeys } from './inspector/useInspectorKeys';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  // Strict-mode safe: connect() returns a cleanup that closes the socket; the
  // double mount/unmount in dev is absorbed by the reconnect guard in ws.ts.
  useEffect(() => connect(useStore), []);
  // Window-level keydown bindings for Esc / [ / ] / R. Installed once at the
  // App root so no per-component listeners duplicate. Spec §3.1 / §4.
  useInspectorKeys();
  return (
    <div className="relative w-full h-full">
      <Scene />
      <Hud />
      <Inspector />
    </div>
  );
}
