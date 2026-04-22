import { useEffect, useRef } from 'react';
import { useStore } from '../../store';
import { useRegionFetch } from '../useRegionFetch';
import { fetchPrompt } from '../../api/rest';
import { fmtBytes } from '../format';

/**
 * Prompt section — collapsed `<details>` by default. Spec §3.2 item 4.
 *
 * Renders the region's `prompt.md` as a scrollable monospaced `<pre>`. The
 * summary shows the file size (via `fmtBytes`, consistent with Handlers and
 * Stats). Auto-refetch fires whenever the selected region's `phase` or
 * `last_error_ts` changes (spec §3.3).
 *
 * Missing-prompt handling (see gotcha #6): the backend returns a 404 with a
 * `not_found` body when a region has no `prompt.md`. That surfaces through
 * `error`, so real 404s render as "Failed: ..." — acceptable for v2 per the
 * spec (§3.4 does not require semantic empty-state for 404). The
 * "No prompt.md in this region." branch only fires when the fetch succeeds
 * but returns an empty string.
 */
export function Prompt({ name }: { name: string }) {
  const { loading, error, data, reload } = useRegionFetch(name, fetchPrompt);
  const stats = useStore((s) => s.regions[name]?.stats);

  const firstRef = useRef(true);
  // Auto-refetch on phase change or last_error_ts change (spec §3.3).
  // Skip the first render — `useRegionFetch` already fetches on mount,
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

  return (
    <details className="border-b border-[#1f1f27]">
      <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
        <span className="font-semibold">
          Prompt{' '}
          <span className="text-[#8a8e99] text-[10px]">· {sizeLabel}</span>
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
        {error && <div className="text-[#ff6a6a]">Failed: {error}</div>}
        {!loading && !error && (data === null || data === '') && (
          <div className="text-[#8a8e99]">
            No <code>prompt.md</code> in this region.
          </div>
        )}
        {data && (
          <pre className="whitespace-pre-wrap break-words text-[#cfd2da] bg-[#0e0e14] p-2 rounded max-h-[360px] overflow-y-auto">
            {data}
          </pre>
        )}
      </div>
    </details>
  );
}
