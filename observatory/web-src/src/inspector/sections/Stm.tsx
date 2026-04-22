import { useEffect, useRef } from 'react';
import { useStore } from '../../store';
import { useRegionFetch } from '../useRegionFetch';
import { fetchStm } from '../../api/rest';
import { JsonTree, type JsonValue } from './JsonTree';

/**
 * STM section — collapsed `<details>` by default. Spec §3.2 item 6.
 *
 * Renders the region's short-term memory as a recursive JSON tree via
 * `JsonTree`. Summary shows the top-level key count. Auto-refetch fires on
 * `phase` / `last_error_ts` change (spec §3.3).
 *
 * Empty STM (`{}`) → "STM is empty." per §3.4. `fetchStm` returns
 * `Record<string, unknown>` which we cast to `JsonValue` at the call site
 * (gotcha #5 option (a)) — keeps `JsonTree` strict and avoids widening its
 * surface to `unknown`.
 */
export function Stm({ name }: { name: string }) {
  const { loading, error, data, reload } = useRegionFetch(name, fetchStm);
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

  const keyCount = data ? Object.keys(data).length : 0;

  return (
    <details className="border-b border-[#1f1f27]">
      <summary className="px-4 py-2 cursor-pointer flex items-center justify-between">
        <span className="font-semibold">
          STM{' '}
          <span className="text-[#8a8e99] text-[10px]">· {keyCount} keys</span>
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
        {!loading && !error && data && Object.keys(data).length === 0 && (
          <div className="text-[#8a8e99]">STM is empty.</div>
        )}
        {data && Object.keys(data).length > 0 && (
          <JsonTree value={data as JsonValue} />
        )}
      </div>
    </details>
  );
}
