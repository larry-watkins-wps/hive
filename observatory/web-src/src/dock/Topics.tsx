import { useState } from 'react';
import { useStore } from '../store';
import type { TopicStat } from './useTopicStats';
import { selectRegionFromRow } from './selectRegionFromRow';

/**
 * `< 1 s ago` / `X.Y s ago` / `X.Y min ago` (spec §6.1 "last-seen
 * relative"). Anchor is wallclock `Date.now()`, same clock the 1 Hz
 * tick uses to write `stat.lastSeenMs`.
 */
function relativeTime(lastSeenMs: number): string {
  const s = (Date.now() - lastSeenMs) / 1000;
  if (s < 1) return '<1 s ago';
  if (s < 60) return `${s.toFixed(1)} s ago`;
  return `${(s / 60).toFixed(1)} min ago`;
}

/**
 * Inline 48 x 8 SVG sparkline (spec §6.1 row column). Normalizes to
 * the tallest bucket; `max = Math.max(1, ...)` avoids div-by-zero when
 * every bucket is 0 (empty-activity topic still in the map during
 * decay).
 */
function Sparkline({ buckets }: { buckets: number[] }) {
  const max = Math.max(1, ...buckets);
  return (
    <svg viewBox="0 0 48 8" width="48" height="8" preserveAspectRatio="none">
      {buckets.map((n, i) => {
        const h = (n / max) * 8;
        return (
          <rect
            key={i}
            x={i * 8 + 1}
            y={8 - h}
            width={6}
            height={h}
            fill="rgba(230,232,238,.65)"
          />
        );
      })}
    </svg>
  );
}

/**
 * HH:MM:SS.mmm (spec §5.1 / §6.1 — same format as Firehose rows so the
 * expand-list reads uniformly). `Date` accepts ms input.
 */
function ts(ms: number): string {
  return new Date(ms).toISOString().slice(11, 23);
}

/**
 * One topic row (spec §6.1).
 *
 * Columns (grid): topic · rate · sparkline · publishers · last-seen · chevron.
 * Spec §6.1 line 168 lists exactly 5 content columns (topic, rate,
 * sparkline, publishers, last-seen) plus a chevron (§6.1 line 172);
 * the plan's earlier code sample added a kind badge between topic and
 * rate — removed per spec. Row text is proportional (Inter 300) per
 * §4.3; the grid layout (not monospace font) provides tabular alignment.
 * Row height is pinned at 22 px per §6.1 line 169.
 *
 * Row click: selectRegionFromRow with the most recent publisher on this
 * topic (spec §6.1 "select the publisher with the most recent envelope").
 * Scene outline ring on every currently-publishing region (spec §6.1
 * second half + §8) is DEFERRED per v3 Task 6 Drift C — logged in
 * decisions.md. Chevron toggles an inline list of the last 5 envelopes
 * on this topic, pulled from the non-reactive `stat.recent5` (Drift B).
 *
 * `recent5` is newest-first (the 1 Hz tick reverse-walks the ring), so
 * `recent5[0]` is the most recent envelope — drives both the row-click
 * publisher choice and the order of the expanded list.
 */
function Row({ stat }: { stat: TopicStat }) {
  const [expanded, setExpanded] = useState(false);
  const recent5 = stat.recent5;

  const onRowClick = () => {
    const mostRecent = recent5[0];
    if (!mostRecent) return;
    selectRegionFromRow(useStore, {
      regionName: mostRecent.source_region,
      envelopeKey: `${mostRecent.observed_at}|${mostRecent.topic}`,
    });
  };

  return (
    <>
      <div
        data-testid="topics-row"
        className="grid items-center gap-2 px-2 h-[22px] cursor-pointer hover:bg-[rgba(230,232,238,.05)]"
        style={{ gridTemplateColumns: '1fr auto auto auto auto auto' }}
        onClick={onRowClick}
      >
        <span className="text-[11px] truncate min-w-0">{stat.topic}</span>
        <span className="font-mono text-[10px] text-[rgba(230,232,238,.9)]">
          {stat.ewmaRate.toFixed(1)} msg/s
        </span>
        <Sparkline buckets={stat.sparkBuckets} />
        <span className="font-mono text-[10px] opacity-70">{stat.publishers.size} pub</span>
        <span className="font-mono text-[10px] opacity-60">{relativeTime(stat.lastSeenMs)}</span>
        <button
          type="button"
          className="text-[10px] opacity-70 px-1"
          onClick={(e) => {
            e.stopPropagation();
            setExpanded(!expanded);
          }}
        >
          {expanded ? '▾' : '▸'}
        </button>
      </div>
      {expanded && (
        <div className="pl-6 pb-1">
          {recent5.map((env) => (
            <div
              key={`${env.observed_at}|${env.source_region ?? ''}`}
              className="text-[10px] font-mono cursor-pointer hover:opacity-100 opacity-75"
              onClick={() =>
                selectRegionFromRow(useStore, {
                  regionName: env.source_region,
                  envelopeKey: `${env.observed_at}|${env.topic}`,
                })
              }
            >
              {ts(env.observed_at)} · {env.source_region ?? '—'}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

/**
 * Spec §6 Topics tab. Renders rows from the `stats` map, sorted by
 * `ewmaRate` desc with `lastSeenMs` asc as tiebreaker (spec §6.1).
 *
 * Empty state per plan Step 6 wording: "No topics yet — waiting for
 * envelopes…".
 *
 * Drift A: `stats` is passed in from `Dock` (which owns the single
 * `useTopicStats()` call) rather than calling the hook here. This keeps
 * the selector's state + interval single-instance — the `Dock` reads
 * `stats.size` for the tab-strip badge count and forwards the same map
 * down so the rows always match the badge.
 */
export function Topics({ stats }: { stats: Map<string, TopicStat> }) {
  if (stats.size === 0) {
    return <div className="p-3 text-xs opacity-60">No topics yet — waiting for envelopes…</div>;
  }
  const rows = Array.from(stats.values()).sort((a, b) => {
    if (b.ewmaRate !== a.ewmaRate) return b.ewmaRate - a.ewmaRate;
    return a.lastSeenMs - b.lastSeenMs;
  });
  return (
    <div className="overflow-y-auto h-full">
      {rows.map((s) => (
        <Row key={s.topic} stat={s} />
      ))}
    </div>
  );
}
