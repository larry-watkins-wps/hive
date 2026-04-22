import { useStore } from '../store';

// Schemas mirror `glia/metrics.py::build_compute_payload`,
// `build_tokens_payload`, `build_region_health_payload` at the time of
// writing. Observatory is a read-only sidecar, so every field is optional:
// if Hive drifts, we render "—" rather than crash.
type Compute = { total_cpu_pct?: number; total_mem_mb?: number };
type Tokens = { total_input_tokens?: number; total_output_tokens?: number };
type HealthEntry = {
  status?: string;
  consecutive_misses?: number;
  uptime_s?: number;
};
type Health = {
  summary?: string;
  regions_up?: number;
  regions_degraded?: number;
  regions_down?: number;
  per_region?: Record<string, HealthEntry>;
};

type Liveness = 'alive' | 'stale' | 'dead' | 'unknown';

// `per_region[name]` is an object (not a bare status string). `status`
// carries the raw `LifecyclePhase` value (`"wake"`, `"sleep"`, …) plus
// `"dead"` when the region's LWT fired. The UI vocabulary in spec §10.1
// (`alive | stale | dead | unknown`) is derived here:
//   status === "dead"          → dead
//   consecutive_misses > 0     → stale (heartbeat missed)
//   otherwise                  → alive
// `unknown` is reserved for the "no entry for this region at all" case,
// which the current render loop can't hit (we iterate keys of `per_region`),
// but keep it in the map so future empty-slot rendering doesn't need a
// schema change.
function livenessOf(entry: HealthEntry | undefined): Liveness {
  if (!entry) return 'unknown';
  if (entry.status === 'dead') return 'dead';
  if ((entry.consecutive_misses ?? 0) > 0) return 'stale';
  return 'alive';
}

const HEALTH_COLOR: Record<Liveness, string> = {
  alive: '#85d19a',
  stale: '#d6b85a',
  dead: '#d66a6a',
  unknown: 'rgba(136,140,152,.35)',
};

export function SystemMetrics() {
  const compute = useStore((s) => s.retained['hive/system/metrics/compute'] as Compute | undefined);
  const tokens = useStore((s) => s.retained['hive/system/metrics/tokens'] as Tokens | undefined);
  const health = useStore((s) => s.retained['hive/system/metrics/region_health'] as Health | undefined);

  const regions = Object.entries(health?.per_region ?? {});

  return (
    <div className="p-3 bg-hive-panel/80 backdrop-blur rounded-md max-w-xs text-[11px]">
      <div className="text-[10px] tracking-widest opacity-60 uppercase mb-1">Metrics</div>
      <div className="flex gap-4 font-mono text-[11px]">
        <span>CPU {compute?.total_cpu_pct != null ? `${compute.total_cpu_pct.toFixed(1)}%` : '—'}</span>
        <span>Mem {compute?.total_mem_mb != null ? `${Math.round(compute.total_mem_mb)} MB` : '—'}</span>
      </div>
      <div className="flex gap-4 font-mono text-[11px] mt-1">
        <span>In {tokens?.total_input_tokens ?? '—'}</span>
        <span>Out {tokens?.total_output_tokens ?? '—'}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-[2px]">
        {regions.map(([name, entry]) => {
          const live = livenessOf(entry);
          return (
            <div
              key={name}
              data-testid="health-cell"
              title={`${name} · ${entry?.status ?? 'unknown'} · ${live}`}
              style={{
                width: 10,
                height: 10,
                background: HEALTH_COLOR[live],
              }}
            />
          );
        })}
      </div>
    </div>
  );
}
