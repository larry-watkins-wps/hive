import { useEffect, useRef, useState } from 'react';
import { useStore, type Envelope } from '../../store';
import { JsonTree, type JsonValue } from './JsonTree';

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
  // Expand state is LOCAL to Messages, NOT shared with the store's
  // `expandedRowIds` set. Spec §12 scopes `expandedRowIds` to the dock
  // (`setDockTab` clears it on tab switch); sharing it here would let
  // dock tab changes collapse Messages rows and let same-id Firehose +
  // Messages rows expand together. Only `pendingEnvelopeKey` crosses
  // the boundary, and only read-once-then-clear.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const containerRef = useRef<HTMLDivElement | null>(null);
  const followTailRef = useRef(true);
  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const pendingKey = useStore((s) => s.pendingEnvelopeKey);
  const setPendingKey = useStore((s) => s.setPendingEnvelopeKey);

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
    // Reset local expand state on region change so expand identity (which is
    // `observed_at|topic`) doesn't leak across regions — two regions that
    // happen to share an id would otherwise render pre-expanded.
    setExpanded(new Set());
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

  // Consume `pendingEnvelopeKey` (spec §7.2): scroll the matching row into
  // view, auto-expand it, flip followTail off (so the next inbound envelope
  // doesn't yank the viewport back to the tail), then clear the key. jsdom
  // 29 does not implement `scrollIntoView`, so we guard the call — tests
  // assert the expand + clear side effects, which is sufficient.
  //
  // `filtered` is in the dep array so the effect re-runs after the initial
  // filtered seed commits. The dock click-through path (Firehose/Metacog row
  // → `selectRegionFromRow`) sets `pendingEnvelopeKey` in the SAME tick that
  // flips `selectedRegion`, which remounts Messages with pendingKey already
  // set and `rowRefs` still empty. Without `filtered` in the deps, the first
  // run of this effect would miss the row, clear the key, and leave the user
  // with no scroll + no expand. The `if (!pendingKey) return;` early-exit
  // keeps the per-envelope re-run cost at one ref read.
  useEffect(() => {
    if (!pendingKey) return;
    const node = rowRefs.current.get(pendingKey);
    if (node) {
      if (typeof node.scrollIntoView === 'function') {
        node.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
      setExpanded((s) => {
        if (s.has(pendingKey)) return s;
        const n = new Set(s);
        n.add(pendingKey);
        return n;
      });
      followTailRef.current = false;
    }
    // Always clear — spec §7.2 "consumes + clears" covers the miss path too.
    setPendingKey(null);
  }, [pendingKey, setPendingKey, filtered]);

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
            <div
              key={id}
              ref={(n) => {
                if (n) rowRefs.current.set(id, n);
                else rowRefs.current.delete(id);
              }}
              className="py-1 border-b border-dotted border-[#23232b]"
            >
              <div
                data-testid="message-row-grid"
                className="grid grid-cols-[60px_14px_1fr_16px] gap-2 cursor-pointer items-start"
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
                <span className="text-[#8a8e99] text-[10px]">{isExpanded ? '▾' : '▸'}</span>
              </div>
              {isExpanded && (
                <div className="text-[10px] pl-[76px] pt-1">
                  <JsonTree value={e.envelope as unknown as JsonValue} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </details>
  );
}
