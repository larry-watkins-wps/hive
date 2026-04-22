import { create } from 'zustand';
import { subscribeWithSelector } from 'zustand/middleware';

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
  self: {
    identity?: string;
    values?: unknown;
    personality?: unknown;
    autobiographical_index?: unknown;
    felt_state?: string;
  };
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
  envelopesReceivedTotal: number;
  adjacency: Array<[string, string, number]>;
  ambient: Ambient;
  selectedRegion: string | null;
  dockTab: 'firehose' | 'topics' | 'metacog';
  dockCollapsed: boolean;
  dockHeight: number;              // clamped [120, 520]
  dockPaused: boolean;
  firehoseFilter: string;
  expandedRowIds: Set<string>;
  pendingEnvelopeKey: string | null;
  applySnapshot: (s: Snapshot) => void;
  applyRegionDelta: (regions: Record<string, RegionMeta>) => void;
  applyAdjacency: (pairs: Array<[string, string, number]>) => void;
  applyRetained: (topic: string, payload: Record<string, unknown>) => void;
  pushEnvelope: (env: Envelope) => void;
  select: (name: string | null) => void;
  cycle: (direction: 1 | -1) => void;
  setDockTab: (tab: 'firehose' | 'topics' | 'metacog') => void;
  setDockCollapsed: (b: boolean) => void;
  setDockHeight: (n: number) => void;
  setDockPaused: (b: boolean) => void;
  setFirehoseFilter: (s: string) => void;
  toggleRowExpand: (id: string) => void;
  setPendingEnvelopeKey: (key: string | null) => void;
};

const RING_CAP = 5000;

export const MODULATOR_NAMES = ['cortisol', 'dopamine', 'serotonin', 'norepinephrine', 'oxytocin', 'acetylcholine'] as const;
export type ModulatorName = (typeof MODULATOR_NAMES)[number];

function isModulatorName(name: string): name is ModulatorName {
  return (MODULATOR_NAMES as readonly string[]).includes(name);
}

function extractAmbient(retained: Snapshot['retained']): Ambient {
  const ambient: Ambient = { modulators: {}, self: {} };
  for (const [topic, env] of Object.entries(retained)) {
    const payload = env.payload ?? {};
    const value = (payload as { value?: unknown }).value;
    if (topic.startsWith('hive/modulator/')) {
      const name = topic.slice('hive/modulator/'.length);
      if (!isModulatorName(name)) continue;
      const v = Number(value ?? NaN);
      if (!Number.isNaN(v)) ambient.modulators[name] = v;
    } else if (topic === 'hive/self/identity') ambient.self.identity = String(value ?? '');
    else if (topic === 'hive/self/values') ambient.self.values = value;
    else if (topic === 'hive/self/personality') ambient.self.personality = value;
    else if (topic === 'hive/self/autobiographical_index') ambient.self.autobiographical_index = value;
    else if (topic === 'hive/interoception/felt_state') ambient.self.felt_state = String(value ?? '');
  }
  return ambient;
}

// `subscribeWithSelector` middleware adds an overloaded
// `subscribe(selector, listener, opts?)` signature to the store API so
// subscribers can scope to a slice of state (see
// `dock/useDockPersistence.ts` for the canonical usage). Existing
// `useStore((s) => ...)` React hook calls and `store.getState()` are
// unaffected — the middleware is purely additive.
export function createStore() {
  return create<State>()(
    subscribeWithSelector((set, get) => ({
    regions: {},
    envelopes: [],
    envelopesReceivedTotal: 0,
    adjacency: [],
    ambient: { modulators: {}, self: {} },
    selectedRegion: null,
    dockTab: 'firehose',
    dockCollapsed: false,
    dockHeight: 220,
    dockPaused: false,
    firehoseFilter: '',
    expandedRowIds: new Set<string>(),
    pendingEnvelopeKey: null,
    applySnapshot: (s) => set({
      regions: s.regions,
      envelopes: s.recent,
      envelopesReceivedTotal: s.recent.length,
      ambient: extractAmbient(s.retained),
    }),
    applyRegionDelta: (regions) => set({ regions }),
    applyAdjacency: (pairs) => set({ adjacency: pairs }),
    applyRetained: (topic, payload) => {
      const ambient = { ...get().ambient, modulators: { ...get().ambient.modulators }, self: { ...get().ambient.self } };
      const value = (payload as { value?: unknown }).value;
      if (topic.startsWith('hive/modulator/')) {
        const name = topic.slice('hive/modulator/'.length);
        if (!isModulatorName(name)) return;
        ambient.modulators[name] = Number(value ?? 0);
      } else if (topic === 'hive/self/identity') {
        ambient.self.identity = String(value ?? '');
      } else if (topic === 'hive/self/values') {
        ambient.self.values = value;
      } else if (topic === 'hive/self/personality') {
        ambient.self.personality = value;
      } else if (topic === 'hive/self/autobiographical_index') {
        ambient.self.autobiographical_index = value;
      } else if (topic === 'hive/interoception/felt_state') {
        ambient.self.felt_state = String(value ?? '');
      }
      set({ ambient });
    },
    pushEnvelope: (env) => {
      const next = get().envelopes.concat(env);
      if (next.length > RING_CAP) next.splice(0, next.length - RING_CAP);
      // `envelopesReceivedTotal` is monotonic (unlike `envelopes.length` which
      // plateaus at RING_CAP); Counters HUD samples it to compute msg/s.
      set({ envelopes: next, envelopesReceivedTotal: get().envelopesReceivedTotal + 1 });
    },
    select: (name) => set({ selectedRegion: name }),
    cycle: (direction) => {
      const s = get();
      if (s.selectedRegion == null) return;
      const names = Object.keys(s.regions).sort();
      if (names.length === 0) return;
      const idx = names.indexOf(s.selectedRegion);
      if (idx < 0) return;
      const next = (idx + direction + names.length) % names.length;
      set({ selectedRegion: names[next] });
    },
    setDockTab: (tab) => set({ dockTab: tab, expandedRowIds: new Set() }),
    setDockCollapsed: (b) => set({ dockCollapsed: b }),
    setDockHeight: (n) => set({ dockHeight: Math.max(120, Math.min(520, n)) }),
    setDockPaused: (b) => set({ dockPaused: b }),
    setFirehoseFilter: (s) => set({ firehoseFilter: s }),
    toggleRowExpand: (id) => {
      const next = new Set(get().expandedRowIds);
      if (next.has(id)) next.delete(id); else next.add(id);
      set({ expandedRowIds: next });
    },
    setPendingEnvelopeKey: (key) => set({ pendingEnvelopeKey: key }),
    })),
  );
}

export const useStore = createStore();
