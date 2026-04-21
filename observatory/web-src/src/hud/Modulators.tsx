import { useStore } from '../store';

const ORDER = ['cortisol', 'dopamine', 'serotonin', 'norepinephrine', 'oxytocin', 'acetylcholine'] as const;

function Gauge({ name, value }: { name: string; value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-28 opacity-70">{name}</span>
      <div className="flex-1 h-1.5 bg-white/10 rounded overflow-hidden">
        <div className="h-full bg-white/60" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right tabular-nums opacity-80">{value.toFixed(2)}</span>
    </div>
  );
}

export function Modulators() {
  const mods = useStore((s) => s.ambient.modulators);
  return (
    <div className="p-3 bg-hive-panel/80 backdrop-blur rounded-md w-72 space-y-1 mt-2">
      <div className="text-[10px] tracking-widest opacity-60 uppercase">Modulators</div>
      {ORDER.map((n) => <Gauge key={n} name={n} value={mods[n] ?? 0} />)}
    </div>
  );
}
