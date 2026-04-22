import { useState } from 'react';
import { useStore } from '../store';

// Four tabs map to the four `hive/self/*` retained topics (plus the
// interoception felt_state is NOT surfaced here — it stays on the
// SelfPanel's replacement only for the payload projection). Tab → store key:
//   identity    → ambient.self.identity           (string)
//   values      → ambient.self.values             (list | dict | scalar)
//   personality → ambient.self.personality        (list | dict | scalar)
//   autobio     → ambient.self.autobiographical_index (list of {ts, headline})
type Tab = 'identity' | 'values' | 'personality' | 'autobio';

const TABS: Array<{ id: Tab; label: string }> = [
  { id: 'identity', label: 'Identity' },
  { id: 'values', label: 'Values' },
  { id: 'personality', label: 'Personality' },
  { id: 'autobio', label: 'Index' },
];

// `empty state` is per-tab and uses the exact copy from spec §10.2. The
// guard treats `undefined | null | empty-string` as missing so an
// `identity: ''` on a fresh region looks the same as an unset retained
// topic.
function renderBody(tab: Tab, self: ReturnType<typeof useStore.getState>['ambient']['self']) {
  let v: unknown;
  if (tab === 'identity') v = self.identity;
  if (tab === 'values') v = self.values;
  if (tab === 'personality') v = self.personality;
  if (tab === 'autobio') v = self.autobiographical_index;
  if (v === undefined || v === '' || v === null) {
    return <div className="text-xs opacity-60">No data yet — mPFC hasn&apos;t published.</div>;
  }
  if (typeof v === 'string') return <div className="text-sm leading-snug">{v}</div>;
  if (Array.isArray(v)) {
    if (tab === 'autobio') {
      // Autobio entries are `{ts, headline}` rendered newest-first per spec
      // §10.2:327 — sort by `ts` descending (ISO 8601 timestamps sort
      // lexicographically as they do chronologically, so a string compare
      // works) then slice at 20 with an "N more…" footer. Missing `ts`
      // sorts to the end via `''` fallback. Fall back to a truncated JSON
      // blob per row so a malformed entry still renders something useful.
      const entries = (v as Array<{ ts?: string; headline?: string }>)
        .slice()
        .sort((a, b) => {
          const ta = a.ts ?? '';
          const tb = b.ts ?? '';
          return tb.localeCompare(ta);
        })
        .slice(0, 20);
      return (
        <ul className="text-xs leading-snug list-none space-y-0.5">
          {entries.map((e, i) => (
            <li key={i} className="font-mono">
              <span className="opacity-60">{e.ts ?? '—'}</span> · {e.headline ?? JSON.stringify(e).slice(0, 80)}
            </li>
          ))}
          {v.length > 20 && <li className="opacity-60 text-[10px]">{v.length - 20} more…</li>}
        </ul>
      );
    }
    return (
      <ul className="text-xs leading-snug list-disc list-inside">
        {(v as unknown[]).map((x, i) => <li key={i}>{typeof x === 'string' ? x : JSON.stringify(x)}</li>)}
      </ul>
    );
  }
  if (typeof v === 'object') {
    return (
      <ul className="text-xs leading-snug list-none space-y-0.5 font-mono">
        {Object.entries(v as Record<string, unknown>).map(([k, val]) => (
          <li key={k}>
            <span className="opacity-60">{k}</span> · {typeof val === 'object' ? JSON.stringify(val) : String(val)}
          </li>
        ))}
      </ul>
    );
  }
  return <div className="text-sm">{String(v)}</div>;
}

export function SelfState() {
  const self = useStore((s) => s.ambient.self);
  const [tab, setTab] = useState<Tab>('identity');

  return (
    <div className="p-3 bg-hive-panel/80 backdrop-blur rounded-md max-w-xs">
      <div className="text-[10px] tracking-widest opacity-60 uppercase mb-1">Self</div>
      <div className="flex gap-2 mb-2 text-[11px]">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={[
              'pb-0.5',
              tab === t.id ? 'border-b border-[rgba(230,232,238,.9)] text-[rgba(230,232,238,.95)]' : 'opacity-55',
            ].join(' ')}
          >
            {t.label}
          </button>
        ))}
      </div>
      {renderBody(tab, self)}
    </div>
  );
}
