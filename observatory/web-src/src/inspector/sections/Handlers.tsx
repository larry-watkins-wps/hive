import { fetchHandlers, type HandlerEntry } from '../../api/rest';
import { useRegionFetch } from '../useRegionFetch';
import { fmtBytes } from '../format';

/**
 * Handlers section — collapsed `<details>` by default. Spec §3.2 item 8.
 *
 * Lists handler files discovered by the sandbox reader at
 * `/api/regions/:name/handlers`. Each row is `path · size`. Click-through
 * to source content is deferred to v3; in v2 the entries are read-only.
 *
 * No auto-refetch (spec §3.3) — handler files change only on region
 * self-modification + restart. Reload button handles manual refresh.
 */
export function Handlers({ name }: { name: string }) {
  const { loading, error, data, reload } = useRegionFetch(name, fetchHandlers);
  const entries: HandlerEntry[] = data ?? [];

  return (
    <details className="px-4 py-2 border-b border-[#1f1f27]">
      <summary className="cursor-pointer flex justify-between items-center">
        <span className="font-semibold">
          Handlers{' '}
          <span className="text-[#8a8e99] text-[10px]">· {entries.length} files</span>
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
      <div className="pt-2 text-[11px]">
        {loading && <div className="text-[#8a8e99]">loading…</div>}
        {error && <div className="text-[#ff6a6a]">Failed: {error}</div>}
        {!loading && !error && entries.length === 0 && (
          <div className="text-[#8a8e99]">No handler files.</div>
        )}
        {entries.length > 0 && (
          <ul className="font-mono list-none pl-0">
            {entries.map((e) => (
              <li key={e.path} className="py-0.5 flex justify-between">
                <span>{e.path}</span>
                <span className="text-[#8a8e99]">{fmtBytes(e.size)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}
