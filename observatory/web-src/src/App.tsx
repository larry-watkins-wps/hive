import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  // Strict-mode safe: connect() returns a cleanup that closes the socket; the
  // double mount/unmount in dev is absorbed by the reconnect guard in ws.ts.
  useEffect(() => connect(useStore), []);
  return <div className="relative w-full h-full"><Scene /></div>;
}
