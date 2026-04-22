import { useEffect, useRef, useState } from 'react';
import { useStore, type Envelope } from '../../store';

const MAX_ROWS = 100;
const AUTOSCROLL_PX = 40;

function relevantToRegion(env: Envelope, name: string): boolean {
  return env.source_region === name || env.destinations.includes(name);
}

function renderTime(observedAt: number): string {
  const d = new Date(observedAt * 1000);
  const h = String(d.getHours()).padStart(2, '0');
  const m = String(d.getMinutes()).padStart(2, '0');
  const s = String(d.getSeconds()).padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function previewPayload(env: Envelope): string {
  try {
    const s = JSON.stringify(env.envelope);
    return s.length > 80 ? s.slice(0, 80) + '…' : s;
  } catch {
    return '';
  }
}

export function Messages({ name }: { name: string }) {
  const [filtered, setFiltered] = useState<Envelope[]>([]);
  const lastTotalRef = useRef(0);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const containerRef = useRef<HTMLDivElement | null>(null);
  const followTailRef = useRef(true);

  // Incremental scan of the envelope ring buffer.
  //
  // Keyed on `envelopesReceivedTotal` (monotonic) not `envelopes.length`
  // (plateaus at RING_CAP). Same precedent as the Counters HUD's store
  // field: once the ring saturates, length stays at RING_CAP while the
  // total keeps climbing — so a length-based delta would miss every
  // arrival after saturation. The new envelopes always sit at the tail
  // of the ring, so a `take = min(delta, ring.length)` tail read picks
  // them up correctly.
  useEffect(() => {
    const unsub = useStore.subscribe((s) => {
      const total = s.envelopesReceivedTotal;
      const delta = total - lastTotalRef.current;
      if (delta <= 0) return;
      const env = s.envelopes;
      const take = Math.min(delta, env.length);
      const newOnes: Envelope[] = [];
      for (let i = env.length - take; i < env.length; i++) {
        const e = env[i];
        if (relevantToRegion(e, name)) newOnes.push(e);
      }
      lastTotalRef.current = total;
      if (newOnes.length > 0) {
        setFiltered((f) => {
          const next = f.concat(newOnes);
          return next.length > MAX_ROWS ? next.slice(-MAX_ROWS) : next;
        });
      }
    });
    // Seed from current ring contents (useful when panel just opened).
    const state = useStore.getState();
    const ring = state.envelopes;
    const initial: Envelope[] = [];
    for (const e of ring) if (relevantToRegion(e, name)) initial.push(e);
    setFiltered(initial.slice(-MAX_ROWS));
    lastTotalRef.current = state.envelopesReceivedTotal;
    return unsub;
  }, [name]);

  // Track follow-tail state on user scroll.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= AUTOSCROLL_PX;
      followTailRef.current = atBottom;
    };
    el.addEventListener('scroll', onScroll);
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  // Auto-scroll when new row lands AND user was at bottom.
  useEffect(() => {
    if (!followTailRef.current) return;
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [filtered]);

  return (
    <details open className="border-b border-[#1f1f27]">
      <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
        <span className="font-semibold">Messages <span className="text-[#8a8e99] text-[10px]">· filtered to {name} · {filtered.length} recent</span></span>
      </summary>
      <div ref={containerRef} className="px-4 pb-2 text-[10.5px] font-mono text-[#cfd2da] max-h-[220px] overflow-y-auto">
        {filtered.length === 0 && <div className="text-[#8a8e99]">No messages yet.</div>}
        {filtered.map((e) => {
          const id = `${e.observed_at}|${e.topic}`;
          const isExpanded = expanded.has(id);
          const direction = e.source_region === name ? '↑' : '↓';
          return (
            <div key={id} className="py-1 border-b border-dotted border-[#23232b]">
              <div
                className="grid grid-cols-[60px_14px_1fr] gap-2 cursor-pointer"
                onClick={() => setExpanded((s) => {
                  const n = new Set(s);
                  if (n.has(id)) n.delete(id); else n.add(id);
                  return n;
                })}
              >
                <span className="text-[#8a8e99]">{renderTime(e.observed_at)}</span>
                <span className={direction === '↑' ? 'text-[#ffb36a]' : 'text-[#8fd6a0]'}>{direction}</span>
                <span>
                  {e.topic}
                  {!isExpanded && <span className="text-[#8a8e99]"> &nbsp;{previewPayload(e)}</span>}
                </span>
              </div>
              {isExpanded && (
                <pre className="text-[10px] text-[#8a8e99] whitespace-pre-wrap pl-[76px] pt-1">
                  {JSON.stringify(e.envelope, null, 2)}
                </pre>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}
