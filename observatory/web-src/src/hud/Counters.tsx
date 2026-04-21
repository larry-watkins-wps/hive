import { useStore, type RegionMeta } from '../store';
import { useEffect, useRef, useState } from 'react';

export function Counters() {
  const regions = useStore((s) => s.regions);
  const [rate, setRate] = useState(0);
  // Samples of `envelopesReceivedTotal` (monotonic), one per second, last 6 kept.
  // Sampling the monotonic counter — not `envelopes.length` — avoids the
  // plateau bug when the envelope ring caps at RING_CAP (5000): length-delta
  // would read 0.0 msg/s during the busiest periods.
  const samplesRef = useRef<number[]>([]);

  useEffect(() => {
    const id = setInterval(() => {
      const total = useStore.getState().envelopesReceivedTotal;
      samplesRef.current.push(total);
      if (samplesRef.current.length > 6) samplesRef.current.shift();
      const earliest = samplesRef.current[0];
      const seconds = samplesRef.current.length - 1;
      setRate(seconds > 0 ? (total - earliest) / seconds : 0);
    }, 1000);
    return () => clearInterval(id);
  }, []);

  const totalTokens = Object.values(regions).reduce(
    (a, r: RegionMeta) => a + (r.stats?.tokens_lifetime ?? 0),
    0,
  );
  return (
    <div className="flex gap-6 text-xs px-3 py-2 bg-hive-panel/80 backdrop-blur rounded-md">
      <div><span className="opacity-60">Tokens total: </span><span className="tabular-nums">{totalTokens}</span></div>
      <div><span className="opacity-60">Msg/s: </span><span className="tabular-nums">{rate.toFixed(1)}</span></div>
    </div>
  );
}
