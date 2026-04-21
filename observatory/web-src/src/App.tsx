import { useEffect } from 'react';
import { Scene } from './scene/Scene';
import { connect } from './api/ws';
import { useStore } from './store';

export function App() {
  useEffect(() => connect(useStore), []);
  return <div className="relative w-full h-full"><Scene /></div>;
}
