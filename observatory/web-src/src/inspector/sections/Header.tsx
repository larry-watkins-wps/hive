import { useStore } from '../../store';
import { useRegionFetch } from '../useRegionFetch';
import { fetchConfig } from '../../api/rest';

/**
 * Inspector header — region name, phase badge, handler count, llm_model,
 * close button. Spec §3.2 item 1.
 *
 * `llm_model` resolution order (spec §3.3):
 *   1. Fetched `/api/regions/:name/config` (redacted) `llm_model` key.
 *   2. Fall back to `RegionMeta.llm_model` from the store.
 *   3. Fall back to `—` when neither has a non-empty string.
 *
 * No auto-refetch of config — it rarely changes. `useRegionFetch` fires
 * once on mount (and when `name` changes via cycle), which is enough.
 */
export function Header({ name }: { name: string }) {
  const meta = useStore((s) => s.regions[name]);
  const select = useStore((s) => s.select);
  // Call useRegionFetch unconditionally at the top level — never put it
  // behind an early return, because React's Rules of Hooks require a
  // stable call order across renders.
  const cfg = useRegionFetch(name, fetchConfig);

  const cfgModel =
    typeof cfg.data?.llm_model === 'string' && cfg.data.llm_model
      ? cfg.data.llm_model
      : null;
  const metaModel = meta?.llm_model && meta.llm_model.length > 0 ? meta.llm_model : null;
  const llmModel = cfgModel ?? metaModel ?? '—';

  const phase = meta?.stats?.phase ?? 'unknown';
  const handlerCount = meta?.stats?.handler_count ?? 0;

  return (
    <div className="px-4 py-3 border-b border-[#2a2a33]">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[15px] font-semibold">{name}</span>
          <PhaseBadge phase={phase} />
        </div>
        <button
          type="button"
          className="bg-transparent border-0 text-[#8a8e99] text-base cursor-pointer"
          onClick={() => select(null)}
          aria-label="close inspector"
        >
          ✕
        </button>
      </div>
      <div className="flex gap-3 mt-1 text-[#8a8e99] text-[11px]">
        <span>handlers {handlerCount}</span>
        <span>model {llmModel}</span>
      </div>
    </div>
  );
}

/**
 * Phase badge pill. Colors per spec §3.2:
 *   wake       → blue  (default)
 *   sleep      → grey
 *   bootstrap  → green
 *   other      → same classes as wake (fallback)
 */
function PhaseBadge({ phase }: { phase: string }) {
  const cls =
    phase === 'sleep'
      ? 'bg-[#2a2f3a] text-[#8a8e99]'
      : phase === 'bootstrap'
        ? 'bg-[#1e3a2a] text-[#8fd6a0]'
        : 'bg-[#1e3a5f] text-[#8ec5ff]';
  return (
    <span className={`text-[10px] px-2 py-0.5 rounded-full tracking-wider ${cls}`}>
      {phase.toUpperCase()}
    </span>
  );
}
