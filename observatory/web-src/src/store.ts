import { create, StoreApi, UseBoundStore } from 'zustand';

export type RegionStats = {
  phase: string;
  queue_depth: number;
  stm_bytes: number;
  tokens_lifetime: number;
  handler_count: number;
  last_error_ts: string | null;
  msg_rate_in: number;
  msg_rate_out: number;
  llm_in_flight: boolean;
};

export type RegionMeta = {
  role: string;
  llm_model: string;
  stats: RegionStats;
};

export type Envelope = {
  observed_at: number;
  topic: string;
  envelope: Record<string, unknown>;
  source_region: string | null;
  destinations: string[];
};

export type Ambient = {
  modulators: Partial<Record<'cortisol' | 'dopamine' | 'serotonin' | 'norepinephrine' | 'oxytocin' | 'acetylcholine', number>>;
  self: { identity?: string; developmental_stage?: string; age?: number; felt_state?: string };
};

type Snapshot = {
  regions: Record<string, RegionMeta>;
  retained: Record<string, { payload?: Record<string, unknown> }>;
  recent: Envelope[];
  server_version: string;
};

type State = {
  regions: Record<string, RegionMeta>;
  envelopes: Envelope[];
  adjacency: Array<[string, string, number]>;
  ambient: Ambient;
  applySnapshot: (s: Snapshot) => void;
  applyRegionDelta: (regions: Record<string, RegionMeta>) => void;
  applyAdjacency: (pairs: Array<[string, string, number]>) => void;
  applyRetained: (topic: string, payload: Record<string, unknown>) => void;
  pushEnvelope: (env: Envelope) => void;
};

const RING_CAP = 5000;

const MODULATOR_NAMES = ['cortisol', 'dopamine', 'serotonin', 'norepinephrine', 'oxytocin', 'acetylcholine'] as const;
type ModulatorName = (typeof MODULATOR_NAMES)[number];

function isModulatorName(name: string): name is ModulatorName {
  return (MODULATOR_NAMES as readonly string[]).includes(name);
}

function extractAmbient(retained: Snapshot['retained']): Ambient {
  const ambient: Ambient = { modulators: {}, self: {} };
  for (const [topic, env] of Object.entries(retained)) {
    const payload = env.payload ?? {};
    if (topic.startsWith('hive/modulator/')) {
      const name = topic.slice('hive/modulator/'.length);
      if (!isModulatorName(name)) continue;
      const v = Number(payload.value ?? NaN);
      if (!Number.isNaN(v)) ambient.modulators[name] = v;
    } else if (topic === 'hive/self/identity') ambient.self.identity = String(payload.value ?? '');
    else if (topic === 'hive/self/developmental_stage') ambient.self.developmental_stage = String(payload.value ?? '');
    else if (topic === 'hive/self/age') ambient.self.age = Number(payload.value ?? NaN);
    else if (topic === 'hive/interoception/felt_state') ambient.self.felt_state = String(payload.value ?? '');
  }
  return ambient;
}

export function createStore(): UseBoundStore<StoreApi<State>> {
  return create<State>((set, get) => ({
    regions: {},
    envelopes: [],
    adjacency: [],
    ambient: { modulators: {}, self: {} },
    applySnapshot: (s) => set({
      regions: s.regions,
      envelopes: s.recent,
      ambient: extractAmbient(s.retained),
    }),
    applyRegionDelta: (regions) => set({ regions }),
    applyAdjacency: (pairs) => set({ adjacency: pairs }),
    applyRetained: (topic, payload) => {
      const ambient = { ...get().ambient, modulators: { ...get().ambient.modulators }, self: { ...get().ambient.self } };
      if (topic.startsWith('hive/modulator/')) {
        const name = topic.slice('hive/modulator/'.length);
        if (!isModulatorName(name)) return;
        ambient.modulators[name] = Number(payload.value ?? 0);
      }
      set({ ambient });
    },
    pushEnvelope: (env) => {
      const next = get().envelopes.concat(env);
      if (next.length > RING_CAP) next.splice(0, next.length - RING_CAP);
      set({ envelopes: next });
    },
  }));
}

export const useStore = createStore();
