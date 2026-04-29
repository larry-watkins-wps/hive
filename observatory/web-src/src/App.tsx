import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { Hud } from './hud/Hud';
import { Inspector } from './inspector/Inspector';
import { Dock } from './dock/Dock';
import { useInspectorKeys } from './inspector/useInspectorKeys';
import { useDockKeys } from './dock/useDockKeys';
import { ChatOverlay } from './chat/ChatOverlay';
import { useChatKeys } from './chat/useChatKeys';
import { useChatPersistence } from './chat/useChatPersistence';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  // Strict-mode safe: connect() returns a cleanup that closes the socket; the
  // double mount/unmount in dev is absorbed by the reconnect guard in ws.ts.
  useEffect(() => connect(useStore), []);
  // Window-level keydown bindings for Esc / [ / ] / R. Installed once at the
  // App root so no per-component listeners duplicate. Spec §3.1 / §4.
  useInspectorKeys();
  // Dock-specific keys (spec §4.1): backtick toggles collapse; Space toggles
  // pause when the event target is inside #dock-root.
  useDockKeys();
  useChatKeys();
  useChatPersistence(useStore);
  return (
    <div className="relative w-full h-full">
      <Scene />
      <Hud />
      <Inspector />
      <Dock />
      <ChatOverlay />
    </div>
  );
}
