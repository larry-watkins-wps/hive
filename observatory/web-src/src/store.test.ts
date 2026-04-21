import { describe, it, expect } from 'vitest';
import { createStore } from './store';

describe('store', () => {
  it('applies a snapshot', () => {
    const s = createStore();
    s.getState().applySnapshot({
      regions: { thalamus: { role: 'cognitive', llm_model: 'x', stats: { phase: 'wake' } as any } },
      retained: { 'hive/modulator/cortisol': { payload: { value: 0.4 } } },
      recent: [],
      server_version: '0.1.0',
    });
    expect(s.getState().regions.thalamus.stats.phase).toBe('wake');
    expect(s.getState().ambient.modulators.cortisol).toBe(0.4);
  });

  it('appends an envelope into the ring', () => {
    const s = createStore();
    s.getState().pushEnvelope({
      observed_at: 1,
      topic: 'hive/cognitive/prefrontal/plan',
      envelope: {},
      source_region: 'thalamus',
      destinations: ['prefrontal_cortex'],
    });
    expect(s.getState().envelopes.length).toBe(1);
  });

  it('caps envelopes at 5000', () => {
    const s = createStore();
    for (let i = 0; i < 5100; i++) {
      s.getState().pushEnvelope({
        observed_at: i, topic: 't', envelope: {}, source_region: null, destinations: [],
      });
    }
    expect(s.getState().envelopes.length).toBe(5000);
  });

  it('drops unknown modulator names from retained snapshots', () => {
    const s = createStore();
    s.getState().applySnapshot({
      regions: {},
      retained: {
        'hive/modulator/cortisol': { payload: { value: 0.4 } },
        'hive/modulator/BADNAME': { payload: { value: 9.9 } },
      },
      recent: [],
      server_version: '0.1.0',
    });
    expect(s.getState().ambient.modulators.cortisol).toBe(0.4);
    expect(Object.keys(s.getState().ambient.modulators)).not.toContain('BADNAME');
  });

  it('drops unknown modulator names from live applyRetained', () => {
    const s = createStore();
    s.getState().applyRetained('hive/modulator/BADNAME', { value: 9.9 });
    expect(Object.keys(s.getState().ambient.modulators)).not.toContain('BADNAME');
  });

  it('envelopesReceivedTotal increments monotonically past RING_CAP', () => {
    const s = createStore();
    for (let i = 0; i < 5100; i++) {
      s.getState().pushEnvelope({
        observed_at: i, topic: 't', envelope: {}, source_region: null, destinations: [],
      });
    }
    expect(s.getState().envelopes.length).toBe(5000);
    expect(s.getState().envelopesReceivedTotal).toBe(5100);
  });
});

function withRegions(store: ReturnType<typeof createStore>, ...names: string[]) {
    const regions = Object.fromEntries(
        names.map((n) => [n, { role: 'x', llm_model: '', stats: {
            phase: 'wake', queue_depth: 0, stm_bytes: 0, tokens_lifetime: 0,
            handler_count: 0, last_error_ts: null, msg_rate_in: 0, msg_rate_out: 0,
            llm_in_flight: false,
        } }]),
    );
    store.getState().applyRegionDelta(regions);
}

describe('selection', () => {
  it('select(name) sets selectedRegion', () => {
    const store = createStore();
    store.getState().select('mpfc');
    expect(store.getState().selectedRegion).toBe('mpfc');
  });
  it('select(null) clears selectedRegion', () => {
    const store = createStore();
    store.getState().select('mpfc');
    store.getState().select(null);
    expect(store.getState().selectedRegion).toBeNull();
  });
  it('cycle is a no-op when selectedRegion is null', () => {
    const store = createStore();
    withRegions(store, 'a', 'b', 'c');
    store.getState().cycle(1);
    expect(store.getState().selectedRegion).toBeNull();
  });
  it('cycle(+1) steps forward alphabetically', () => {
    const store = createStore();
    withRegions(store, 'charlie', 'alpha', 'bravo');
    store.getState().select('alpha');
    store.getState().cycle(1);
    expect(store.getState().selectedRegion).toBe('bravo');
  });
  it('cycle(+1) wraps from last to first', () => {
    const store = createStore();
    withRegions(store, 'alpha', 'bravo', 'charlie');
    store.getState().select('charlie');
    store.getState().cycle(1);
    expect(store.getState().selectedRegion).toBe('alpha');
  });
  it('cycle(-1) wraps from first to last', () => {
    const store = createStore();
    withRegions(store, 'alpha', 'bravo', 'charlie');
    store.getState().select('alpha');
    store.getState().cycle(-1);
    expect(store.getState().selectedRegion).toBe('charlie');
  });
});
