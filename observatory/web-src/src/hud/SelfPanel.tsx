import { useStore } from '../store';

export function SelfPanel() {
  const self = useStore((s) => s.ambient.self);
  return (
    <div className="p-3 bg-hive-panel/80 backdrop-blur rounded-md max-w-xs">
      <div className="text-[10px] tracking-widest opacity-60 uppercase">Self</div>
      <div className="text-sm leading-snug line-clamp-2">{self.identity ?? '—'}</div>
      <div className="flex gap-2 mt-1 text-xs">
        <span className="px-1.5 py-0.5 bg-white/10 rounded">{self.felt_state ?? '—'}</span>
      </div>
    </div>
  );
}
