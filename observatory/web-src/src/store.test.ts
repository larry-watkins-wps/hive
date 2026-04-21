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
