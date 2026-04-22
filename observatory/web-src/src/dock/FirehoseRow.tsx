import { useStore, type Envelope } from '../store';
import { kindTag } from '../scene/topicColors';
import { JsonTree, type JsonValue } from '../inspector/sections/JsonTree';
import { selectRegionFromRow } from './selectRegionFromRow';

/**
 * Spec §5.1 preview logic. `env` here is the INNER envelope payload
 * (`Envelope.envelope: Record<string, unknown>`), not the outer wrapper
 * type from the store. For content-type application/json, stringify the
 * `data` sub-field; otherwise coerce to a string. Truncate to 120 chars
 * with a trailing ellipsis; collapse newlines to `↵` so one row == one
 * visual line.
 *
 * `data` may be `undefined` on malformed producers. `JSON.stringify(undefined)`
 * returns `undefined`, which would then crash `.replace(...)` with a
 * TypeError. The `?? null` inside the stringify coerces undefined → "null";
 * the outer `?? ''` protects against any future edge case where stringify
 * returns undefined.
 */
function previewOf(env: Record<string, unknown>): string {
  const payload = (env as { payload?: { content_type?: string; data?: unknown } }).payload;
  if (!payload) return '';
  let raw = '';
  if (payload.content_type === 'application/json') {
    try {
      raw = JSON.stringify(payload.data ?? null) ?? '';
    } catch {
      raw = String(payload.data);
    }
  } else {
    raw = String(payload.data ?? '');
  }
  raw = raw.replace(/\n/g, '↵');
  return raw.length > 120 ? raw.slice(0, 120) + '…' : raw;
}

/**
 * Format millisecond timestamp as `HH:MM:SS.mmm` (spec §5.1). `Date`
 * accepts ms input, so `toISOString()` yields the ISO string and we slice
 * out the time portion.
 */
function ts(ms: number): string {
  return new Date(ms).toISOString().slice(11, 23);
}

/**
 * One firehose row. Spec §5.1 schema: timestamp · source · `→ topic` ·
 * kind badge · preview · expand chevron, fitting on ONE visual line at
 * 22 px tall. Click anywhere on the row (except the chevron) triggers the
 * shared `selectRegionFromRow` select-flow (spec §8). Chevron toggles an
 * inline JsonTree view of the full envelope, rendered BELOW the row so
 * the row itself stays 22 px tall.
 *
 * Grid columns: `auto auto 1fr auto 1fr auto` — the two `1fr` tracks
 * (topic, preview) compete for available width; both carry `min-w-0`
 * + `truncate` so neither can overflow. Spec §4.3 "Row text: 11 px
 * Inter 300" governs source + topic (proportional). Timestamp and
 * preview are 10 px ui-monospace per spec §4.3 "Timestamps" / "payload
 * text" rules. Source ellipsis at `18ch` per spec §5.1 ("ellipsis if
 * `> 18` chars").
 *
 * `rowKey` is `${observed_at}|${topic}|${source_region}` and is the
 * identity under which expand state is stored in the store's
 * `expandedRowIds` set (spec §5.5).
 */
export function FirehoseRow({ env, rowKey }: { env: Envelope; rowKey: string }) {
  const expanded = useStore((s) => s.expandedRowIds.has(rowKey));
  const toggleRowExpand = useStore((s) => s.toggleRowExpand);
  const selected = useStore((s) => s.selectedRegion === env.source_region);
  const preview = previewOf(env.envelope);
  const tag = kindTag(env.topic);

  return (
    <>
      <div
        data-testid="firehose-row"
        className={[
          'grid items-center gap-2 px-2 h-[22px] cursor-pointer',
          'hover:bg-[rgba(230,232,238,.05)]',
          selected
            ? 'border-l-2 border-[rgba(230,232,238,.9)]'
            : 'border-l-2 border-transparent',
        ].join(' ')}
        style={{ gridTemplateColumns: 'auto auto 1fr auto 1fr auto' }}
        onClick={() =>
          selectRegionFromRow(useStore, {
            regionName: env.source_region,
            envelopeKey: `${env.observed_at}|${env.topic}`,
          })
        }
      >
        <span className="font-mono text-[10px] text-[rgba(136,140,152,.70)]">{ts(env.observed_at)}</span>
        <span className="text-[11px] truncate max-w-[18ch]">{env.source_region ?? '—'}</span>
        <span className="text-[11px] truncate min-w-0 opacity-80">→ {env.topic}</span>
        <span className="font-mono text-[10px] px-1 rounded bg-[rgba(255,255,255,.05)]">{tag}</span>
        <span className="font-mono text-[10px] opacity-70 truncate min-w-0">{preview}</span>
        <button
          type="button"
          className="text-[10px] opacity-70 px-1"
          onClick={(e) => {
            e.stopPropagation();
            toggleRowExpand(rowKey);
          }}
        >
          {expanded ? '▾' : '▸'}
        </button>
      </div>
      {expanded && (
        <div className="px-6 py-1 text-[10px] border-l-2 border-[rgba(80,84,96,.35)]">
          {/* Envelope is Record<string, unknown>; JsonTree takes JsonValue.
              Cast is safe at this boundary because observatory only receives
              JSON-decoded payloads from the backend — same pattern as Stm.tsx. */}
          <JsonTree value={env.envelope as unknown as JsonValue} />
        </div>
      )}
    </>
  );
}
