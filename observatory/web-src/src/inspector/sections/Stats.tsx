import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { useStore } from '../../store';

/**
 * Stats strip — five inline tiles summarising the selected region's runtime
 * counters. Spec §3.2 item 2.
 *
 *   QUEUE     — queue_depth + 24-point sparkline
 *   STM       — stm_bytes formatted (B / kB / MB) with threshold coloring
 *               (<16 kB default, 16–64 kB amber, >64 kB red)
 *   TOKENS    — tokens_lifetime formatted (k / M) + sparkline
 *   HANDLERS  — handler_count integer
 *   LAST ERR  — relative time since last_error_ts with red dot when <60 s
 *
 * Sparklines span a 2-minute window at the 5-second heartbeat cadence,
 * which is 24 samples. History is tracked client-side via a
 * `useStore.subscribe` installed on mount.
 */

const HISTORY_POINTS = 24; // 2 minutes at 5s heartbeat cadence.

type SparkHistory = {
  queue_depth: number[];
  stm_bytes: number[];
  tokens_lifetime: number[];
};

/**
 * Subscribe once to the zustand store and append each region's fresh stats
 * to a bounded history. Kept tight (24 points) so React renders stay cheap.
 *
 * We read via `useStore.subscribe` rather than `useStore(selector)` because
 * we want to sample on every store update (every heartbeat delta the
 * backend sends), not only when the selector's output changes by identity.
 * `subscribe` returns an unsubscribe function we clean up in the effect.
 */
function useStatsHistory(name: string): SparkHistory {
  const [history, setHistory] = useState<SparkHistory>({
    queue_depth: [],
    stm_bytes: [],
    tokens_lifetime: [],
  });

  useEffect(() => {
    // Seed with the current value so the first render has at least one
    // point (still below the sparkline's 2-point minimum — that renders a
    // blank placeholder until the next heartbeat).
    const seed = useStore.getState().regions[name]?.stats;
    if (seed) {
      setHistory({
        queue_depth: [seed.queue_depth],
        stm_bytes: [seed.stm_bytes],
        tokens_lifetime: [seed.tokens_lifetime],
      });
    } else {
      setHistory({ queue_depth: [], stm_bytes: [], tokens_lifetime: [] });
    }
    const unsub = useStore.subscribe((s) => {
      const stats = s.regions[name]?.stats;
      if (!stats) return;
      setHistory((h) => ({
        queue_depth: [...h.queue_depth.slice(-(HISTORY_POINTS - 1)), stats.queue_depth],
        stm_bytes: [...h.stm_bytes.slice(-(HISTORY_POINTS - 1)), stats.stm_bytes],
        tokens_lifetime: [
          ...h.tokens_lifetime.slice(-(HISTORY_POINTS - 1)),
          stats.tokens_lifetime,
        ],
      }));
    });
    return unsub;
  }, [name]);

  return history;
}

function Sparkline({ points, stroke }: { points: number[]; stroke: string }) {
  // A single-point (or empty) history can't be drawn as a line — emit a
  // zero-height placeholder so the tile height stays stable.
  if (points.length < 2) return <div className="h-[10px]" />;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const coords = points
    .map((p, i) => {
      const x = (i / (HISTORY_POINTS - 1)) * 48;
      const y = 14 - ((p - min) / span) * 12;
      return `${x},${y}`;
    })
    .join(' ');
  return (
    <svg viewBox="0 0 48 14" width="100%" height={10} aria-hidden="true">
      <polyline points={coords} fill="none" stroke={stroke} strokeWidth={1} />
    </svg>
  );
}

function relativeTime(ts: string | null): { text: string; fresh: boolean } {
  if (!ts) return { text: '—', fresh: false };
  const then = new Date(ts).getTime();
  if (Number.isNaN(then)) return { text: '—', fresh: false };
  const delta = (Date.now() - then) / 1000;
  if (delta < 60) return { text: `${Math.floor(delta)}s`, fresh: true };
  if (delta < 3600) return { text: `${Math.floor(delta / 60)}m`, fresh: false };
  return { text: `${Math.floor(delta / 3600)}h`, fresh: false };
}

function fmtBytes(n: number): string {
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}MB`;
  if (n >= 1024) return `${Math.round(n / 1024)}kB`;
  return `${n}B`;
}

function fmtTokens(n: number): string {
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}k`;
  return String(n);
}

export function Stats({ name }: { name: string }) {
  const stats = useStore((s) => s.regions[name]?.stats);
  // Hook order matters — call useStatsHistory unconditionally before any
  // early return. The hook internally guards on missing stats.
  const history = useStatsHistory(name);
  if (!stats) return null;

  const stmColor =
    stats.stm_bytes > 64 * 1024
      ? 'text-[#ff6a6a]'
      : stats.stm_bytes > 16 * 1024
        ? 'text-[#ffb36a]'
        : 'text-[#cfd2da]';
  const err = relativeTime(stats.last_error_ts);

  return (
    <div className="px-3 py-2 border-b border-[#2a2a33] grid grid-cols-5 gap-1">
      <Tile label="QUEUE" value={String(stats.queue_depth)}>
        <Sparkline points={history.queue_depth} stroke="#6aa8ff" />
      </Tile>
      <Tile
        label="STM"
        value={<span className={stmColor}>{fmtBytes(stats.stm_bytes)}</span>}
      >
        <Sparkline points={history.stm_bytes} stroke="#ffb36a" />
      </Tile>
      <Tile label="TOKENS" value={fmtTokens(stats.tokens_lifetime)}>
        <Sparkline points={history.tokens_lifetime} stroke="#8fd6a0" />
      </Tile>
      <Tile label="HANDLERS" value={String(stats.handler_count)} />
      <Tile
        label="LAST ERR"
        value={
          <span className="inline-flex items-center gap-1">
            {err.fresh && (
              <span
                className="inline-block w-1.5 h-1.5 rounded-full bg-[#ff6a6a]"
                aria-hidden="true"
              />
            )}
            {err.text}
          </span>
        }
      />
    </div>
  );
}

function Tile({
  label,
  value,
  children,
}: {
  label: string;
  value: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="bg-[#16161c] p-1.5 rounded text-center">
      <div className="text-[9px] text-[#8a8e99] tracking-wider">{label}</div>
      <div className="text-[13px] font-semibold my-0.5">{value}</div>
      {children ?? <div className="h-[10px]" />}
    </div>
  );
}
