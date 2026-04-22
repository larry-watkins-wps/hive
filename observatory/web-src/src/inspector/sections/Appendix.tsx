import { useEffect, useRef } from 'react';
import { useStore } from '../../store';
import { useRegionAppendix } from '../useRegionAppendix';
import { parseAppendix } from './parseAppendix';
import { fmtBytes } from '../format';

/**
 * Appendix section — expanded `<details open>` by default. Spec §9.1.
 *
 * Renders the region's rolling `appendix.md` as parsed entries (timestamp +
 * trigger tag + monospace body), newest-first. The summary shows the file
 * size via `fmtBytes`, matching Prompt / Stats / Handlers conventions.
 *
 * Empty-state semantics (see `useRegionAppendix`): the backend returns 404
 * when a region has never slept, which the hook maps to `data === ''` (not
 * an error). `data === null` means "fetch still in flight" and is covered
 * by the `loading` branch. Non-404 failures surface through `error` as the
 * standard red "Failed: ..." row (spec §9.1).
 *
 * Auto-refetch fires on `phase` or `last_error_ts` change (spec §9.1,
 * matching Prompt's pattern). The `firstRef` guard skips the initial
 * effect-run so we don't double-fetch on mount (the hook already fetches
 * on mount).
 */
export function Appendix({ name }: { name: string }) {
  const { loading, error, data, reload } = useRegionAppendix(name);
  const stats = useStore((s) => s.regions[name]?.stats);

  const firstRef = useRef(true);
  // Auto-refetch on phase change or last_error_ts change (spec §9.1).
  // Skip the first render — `useRegionAppendix` already fetches on mount,
  // so firing reload() here would double-fetch every selection.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (firstRef.current) {
      firstRef.current = false;
      return;
    }
    if (stats) reload();
  }, [stats?.phase, stats?.last_error_ts]);

  const sizeLabel = data != null ? fmtBytes(data.length) : '—';
  // parseAppendix preserves file order (chronological). Reverse so newest
  // renders first. `.reverse()` is fine here — it mutates the fresh array
  // returned by the parser, not stored state.
  const entries = data ? parseAppendix(data).reverse() : [];

  return (
    <details open className="border-b border-[#1f1f27]">
      <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
        <span className="font-semibold">
          Appendix{' '}
          <span className="text-[#8a8e99] text-[10px]">
            (rolling) · {sizeLabel}
            {data ? ` · ${entries.length} entries` : ''}
          </span>
        </span>
        <button
          type="button"
          onClick={(e) => {
            e.preventDefault();
            e.stopPropagation();
            reload();
          }}
          className="text-[10px] text-[#8a8e99] border border-[#2a2a33] px-2 rounded"
        >
          reload
        </button>
      </summary>
      <div className="px-4 pb-3 text-[11px]">
        {loading && <div className="text-[#8a8e99]">loading…</div>}
        {error && (
          <div className="text-[#ff6a6a]">Failed: {error.message}</div>
        )}
        {!loading && !error && data === '' && (
          <div className="text-[#8a8e99]">
            No appendix yet — region hasn't slept.
          </div>
        )}
        {!loading && !error && entries.length > 0 && (
          <div className="max-h-[360px] overflow-y-auto">
            {entries.map((e, i) => (
              <div key={i} className="mb-2">
                <div className="flex gap-2 items-baseline">
                  <span className="font-mono text-[10px] text-[#8a8e99]">
                    {e.ts || '—'}
                  </span>
                  {e.trigger && (
                    <span className="text-[11px] px-1 rounded bg-[#1e1e26]">
                      {e.trigger}
                    </span>
                  )}
                </div>
                <pre className="font-mono text-[10px] whitespace-pre-wrap text-[#cfd2da] opacity-85 mt-1 bg-[#0e0e14] p-2 rounded">
                  {e.body}
                </pre>
              </div>
            ))}
          </div>
        )}
      </div>
    </details>
  );
}
