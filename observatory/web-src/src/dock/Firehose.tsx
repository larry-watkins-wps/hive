import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore, type Envelope } from '../store';
import { FirehoseRow } from './FirehoseRow';

const MAX_ROWS = 1000;

/**
 * Compile the active filter string into a `(haystack: string) => boolean`
 * matcher plus a `valid` flag the UI uses to paint a red border on the
 * input when the user typed an un-compilable regex.
 *
 * Rules (spec §5.2):
 *   - empty → match-all, valid
 *   - `/pattern/` or `/pattern/i` → compile, valid on success; on failure
 *     return match-all + `valid: false` so the UI can signal the error
 *     without hiding every row
 *   - anything else → case-insensitive substring match
 */
function matcher(filter: string): { fn: (s: string) => boolean; valid: boolean } {
  if (filter.trim() === '') return { fn: () => true, valid: true };
  const m = filter.match(/^\/(.+)\/(i)?$/);
  if (m) {
    try {
      const rx = new RegExp(m[1], m[2] ?? '');
      return { fn: (s) => rx.test(s), valid: true };
    } catch {
      return { fn: () => true, valid: false };
    }
  }
  const lc = filter.toLowerCase();
  return { fn: (s) => s.toLowerCase().includes(lc), valid: true };
}

/**
 * Spec §5 Firehose tab. Renders the envelope ring with spec-§5.1 row
 * schema, spec-§5.2 filter bar, spec-§5.3 kind-tag badges, pause snapshot,
 * auto-scroll to bottom, and a 1000-row hard cap (spec §15 perf budget).
 *
 * Pause snapshot is captured INLINE during render (Task 5 Drift D): on
 * the frame where `paused` flips true we set `snapshotRef.current =
 * liveEnvs` before reading `envs`, so the first paused frame already
 * shows the snapshotted list instead of one frame of live data. Setting
 * a ref during render is safe because renders are supposed to be pure
 * wrt. observed state — and a ref write is explicitly called out in the
 * React docs as NOT triggering a re-render.
 */
export function Firehose() {
  const filter = useStore((s) => s.firehoseFilter);
  const setFilter = useStore((s) => s.setFirehoseFilter);
  const paused = useStore((s) => s.dockPaused);

  const [input, setInput] = useState(filter);
  useEffect(() => {
    const t = setTimeout(() => setFilter(input), 150);
    return () => clearTimeout(t);
  }, [input, setFilter]);

  const match = useMemo(() => matcher(filter), [filter]);

  const liveEnvs = useStore((s) => s.envelopes);
  const snapshotRef = useRef<Envelope[] | null>(null);
  // Drift D — inline (not useEffect) so the first paused frame already
  // renders off the snapshot. useEffect fires AFTER commit, which would
  // mean one frame of live data leaks through between `paused` flipping
  // true and the effect setting the snapshot.
  if (paused && snapshotRef.current == null) {
    snapshotRef.current = liveEnvs;
  }
  if (!paused && snapshotRef.current != null) {
    snapshotRef.current = null;
  }
  const envs = paused ? (snapshotRef.current ?? liveEnvs) : liveEnvs;

  const rows = useMemo(() => {
    const sliced = envs.slice(-MAX_ROWS);
    return sliced.filter((e) => {
      const src = e.source_region ?? '';
      const haystack = `${src} ${e.topic} ${JSON.stringify(e.envelope)}`;
      return match.fn(haystack);
    });
  }, [envs, match]);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [rows]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-2 py-1 border-b border-[rgba(80,84,96,.35)]">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="filter source · topic · payload  (regex /.../)"
          className={[
            'w-full bg-transparent text-[11px] font-mono outline-none px-1 py-0.5',
            match.valid
              ? 'text-[rgba(230,232,238,.9)]'
              : 'text-[#ff8a88] border border-[#ff8a88]',
          ].join(' ')}
        />
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {rows.map((e) => {
          const rowKey = `${e.observed_at}|${e.topic}|${e.source_region ?? ''}`;
          return <FirehoseRow key={rowKey} rowKey={rowKey} env={e} />;
        })}
      </div>
    </div>
  );
}
