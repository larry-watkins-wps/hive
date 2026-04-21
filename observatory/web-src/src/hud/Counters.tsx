import { useStore } from '../store';
import { useEffect, useRef, useState } from 'react';

export function Counters() {
  const regions = useStore((s) => s.regions);
  const [rate, setRate] = useState(0);
  const samplesRef = useRef<number[]>([]); // length samples, one per second, last 6 kept

  useEffect(() => {
    const id = setInterval(() => {
      const envs = useStore.getState().envelopes;
      samplesRef.current.push(envs.length);
      if (samplesRef.current.length > 6) samplesRef.current.shift();
      const earliest = samplesRef.current[0];
      const seconds = samplesRef.current.length - 1;
      setRate(seconds > 0 ? (envs.length - earliest) / seconds : 0);
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const totalTokens = Object.values(regions).reduce(
    (a, r: any) => a + (r.stats?.tokens_lifetime ?? 0),
    0,
  );
  return (
    <div className="flex gap-6 text-xs px-3 py-2 bg-hive-panel/80 backdrop-blur rounded-md">
      <div><span className="opacity-60">Tokens total: </span><span className="tabular-nums">{totalTokens}</span></div>
      <div><span className="opacity-60">Msg/s: </span><span className="tabular-nums">{rate.toFixed(1)}</span></div>
    </div>
  );
}
