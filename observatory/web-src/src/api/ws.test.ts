import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { handleServerMessage } from './ws';
import { createStore } from '../store';

describe('handleServerMessage', () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it('routes snapshot', () => {
    const s = createStore();
    const spy = vi.spyOn(s.getState(), 'applySnapshot');
    handleServerMessage(s, { type: 'snapshot', payload: {
      regions: {}, retained: {}, recent: [], server_version: '0.1.0' } });
    expect(spy).toHaveBeenCalled();
  });

  it('routes envelope', () => {
    const s = createStore();
    handleServerMessage(s, { type: 'envelope', payload: {
      observed_at: 1, topic: 'x', envelope: {}, source_region: null, destinations: [],
    }});
    // ws.ts batches envelopes through a ~100ms _scheduleFlush() (introduced
    // by commit 5b93ce5 to bound Firehose re-render rate); advance the
    // fake timer past the flush window to drain `_pending` into the store.
    vi.advanceTimersByTime(150);
    expect(s.getState().envelopes.length).toBe(1);
  });

  it('routes region_delta and adjacency', () => {
    const s = createStore();
    handleServerMessage(s, { type: 'region_delta', payload: { regions: { a: { role: '', llm_model: '', stats: { phase: 'wake' } as any } } } });
    expect(s.getState().regions.a.stats.phase).toBe('wake');
    handleServerMessage(s, { type: 'adjacency', payload: { pairs: [['a', 'b', 0.5]] } });
    expect(s.getState().adjacency).toEqual([['a', 'b', 0.5]]);
  });
});
