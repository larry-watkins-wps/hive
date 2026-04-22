import { useEffect, useMemo, useRef } from 'react';
import { useStore, type Envelope } from '../store';
import { selectRegionFromRow } from './selectRegionFromRow';

/**
 * Spec §7.1 title extraction. For errors, the payload typically carries
 * `{ kind, detail }` — surface that as `"<kind>: <detail>"`. Otherwise
 * fall back to a 120-char JSON summary of the payload data.
 *
 * Drift C: `JSON.stringify(undefined)` returns `undefined` (not a string),
 * so `.slice(...)` would throw TypeError on malformed producers. The
 * `?? null` inside stringify coerces undefined → "null"; the outer `?? ''`
 * defends against any edge case where stringify still returns undefined
 * (same pattern as `Firehose.previewOf`).
 */
function titleOf(env: Envelope): string {
  const payload = (env.envelope as { payload?: { data?: unknown } }).payload;
  const data = payload?.data as { kind?: string; detail?: string } | undefined;
  if (data?.kind && data?.detail) return `${data.kind}: ${data.detail}`.slice(0, 120);
  try {
    return (JSON.stringify(data ?? null) ?? '').slice(0, 120);
  } catch {
    return String(data ?? '');
  }
}

/**
 * Spec §7.1 left-border accent color by event-kind sub-tree. Fallback
 * grey covers any metacognition subtree we haven't enumerated yet
 * (future-proofing against new sub-topics without crashing).
 */
function colorOf(topic: string): string {
  if (topic.includes('/error/')) return '#ff8a88';
  if (topic.includes('/conflict/')) return '#ffc07a';
  if (topic.includes('/reflection/')) return 'rgba(210,212,220,.55)';
  return 'rgba(230,232,238,.45)';
}

/**
 * Spec §7.1 — event-kind column is the last two topic segments joined
 * with '.' (e.g. `hive/metacognition/error/detected` → `error.detected`).
 * `Array.prototype.at(-N)` is ES2022 / TS 5 standard.
 */
function kindOf(topic: string): string {
  const parts = topic.split('/');
  return `${parts.at(-2) ?? ''}.${parts.at(-1) ?? ''}`;
}

/**
 * HH:MM:SS.mmm (same format as Firehose and Topics — spec §5.1 / §7.1).
 */
function ts(ms: number): string {
  return new Date(ms).toISOString().slice(11, 23);
}

/**
 * Spec §7 Metacognition tab. Filters the envelope ring to
 * `hive/metacognition/#` and renders one row per matching envelope with
 * severity-coloured left-border accent (error red, conflict amber,
 * reflection grey).
 *
 * Drift B: row height pinned at `h-[22px]` and source ellipsis at
 * `max-w-[18ch]` matching Firehose (Task 5 review-fix precedent). Spec
 * §7 doesn't pin a row height; §5.1's 22 px is the dock-row standard
 * and consistency beats inventing a separate height for one tab.
 *
 * Row key is `${observed_at}|${topic}` — matches the shape spec §7.2
 * / §8 uses for `pendingEnvelopeKey` so Task 10's Messages view can
 * scroll/expand the clicked envelope. (Drift from Firehose's three-part
 * key is intentional: the metacog tab is typically sparse, so collisions
 * across identical ts+topic from different sources are rare AND the
 * Messages scroll contract is topic-scoped anyway.)
 *
 * Auto-scroll near-bottom (40 px window) matches Firehose's pattern —
 * scroll with the stream unless the user has deliberately scrolled up.
 */
export function Metacog() {
  const envs = useStore((s) => s.envelopes);
  const rows = useMemo(
    () => envs.filter((e) => e.topic.startsWith('hive/metacognition/')),
    [envs],
  );

  const scrollRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [rows.length]);

  if (rows.length === 0) {
    return <div className="p-3 text-xs opacity-60">No metacognition events yet.</div>;
  }

  return (
    <div ref={scrollRef} className="overflow-y-auto h-full">
      {rows.map((e) => (
        <div
          key={`${e.observed_at}|${e.topic}`}
          data-testid="metacog-row"
          className="grid grid-cols-[auto_auto_auto_1fr] items-center gap-2 px-2 h-[22px] cursor-pointer hover:bg-[rgba(230,232,238,.05)]"
          style={{ borderLeft: `2px solid ${colorOf(e.topic)}` }}
          onClick={() =>
            selectRegionFromRow(useStore, {
              regionName: e.source_region,
              envelopeKey: `${e.observed_at}|${e.topic}`,
            })
          }
        >
          <span className="font-mono text-[10px] text-[rgba(136,140,152,.70)]">{ts(e.observed_at)}</span>
          <span className="text-[11px] truncate max-w-[18ch]">{e.source_region ?? '—'}</span>
          <span className="font-mono text-[10px] opacity-80">{kindOf(e.topic)}</span>
          <span className="font-mono text-[10px] truncate opacity-80">{titleOf(e)}</span>
        </div>
      ))}
    </div>
  );
}
