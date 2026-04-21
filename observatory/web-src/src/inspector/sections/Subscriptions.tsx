import { fetchSubscriptions } from '../../api/rest';
import { useRegionFetch } from '../useRegionFetch';

/**
 * Subscriptions section — collapsed `<details>` by default. Spec §3.2 item 7.
 *
 * Data shape: `fetchSubscriptions(name)` returns the parsed JSON body from
 * `/api/regions/:name/subscriptions`, which per §6 is
 * `{"topics": string[]}`. We read `data?.topics` defensively in case the
 * backend grows more keys later; unknown keys are ignored here.
 *
 * No auto-refetch (spec §3.3) — subscriptions change only when the region
 * restarts. Reload button calls `reload()` for manual refresh.
 */
export function Subscriptions({ name }: { name: string }) {
  const { loading, error, data, reload } = useRegionFetch(name, fetchSubscriptions);
  const topics = (data?.topics as string[] | undefined) ?? [];

  return (
    <details className="px-4 py-2 border-b border-[#1f1f27]">
      <summary className="cursor-pointer flex justify-between items-center">
        <span className="font-semibold">
          Subscriptions{' '}
          <span className="text-[#8a8e99] text-[10px]">· {topics.length} topics</span>
        </span>
        <button
          type="button"
          onClick={(e) => {
            // Stop the click from toggling <details>' own open state.
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
        {!loading && !error && topics.length === 0 && (
          <div className="text-[#8a8e99]">No subscriptions declared.</div>
        )}
        {topics.length > 0 && (
          <ul className="font-mono list-none pl-0">
            {topics.map((t) => (
              <li key={t} className="py-0.5">
                {t}
              </li>
            ))}
          </ul>
        )}
      </div>
    </details>
  );
}
