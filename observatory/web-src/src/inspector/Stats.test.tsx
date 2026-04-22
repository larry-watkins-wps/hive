import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, act, cleanup } from '@testing-library/react';
import { useStatsHistory } from './sections/Stats';
import { useStore, type RegionStats } from '../store';

function statsOverrides(partial: Partial<RegionStats>): RegionStats {
  return {
    phase: 'wake',
    queue_depth: 1,
    stm_bytes: 100,
    tokens_lifetime: 50,
    handler_count: 3,
    last_error_ts: null,
    msg_rate_in: 0,
    msg_rate_out: 0,
    llm_in_flight: false,
    ...partial,
  };
}

describe('useStatsHistory', () => {
  beforeEach(() => {
    useStore.getState().applyRegionDelta({
      r1: { role: 'x', llm_model: '', stats: statsOverrides({}) },
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('seeds history with the current stats on mount', () => {
    const { result } = renderHook(() => useStatsHistory('r1'));
    expect(result.current.queue_depth).toEqual([1]);
    expect(result.current.stm_bytes).toEqual([100]);
    expect(result.current.tokens_lifetime).toEqual([50]);
  });

  it('ignores envelope-only store ticks (dedup)', () => {
    // `pushEnvelope` fires at MQTT rates and does not change the region's
    // stats, so the subscribe callback must not append a duplicate sample.
    const { result } = renderHook(() => useStatsHistory('r1'));
    act(() => {
      useStore.getState().pushEnvelope({
        observed_at: 0,
        topic: 'hive/test',
        envelope: {},
        source_region: null,
        destinations: [],
      });
      useStore.getState().pushEnvelope({
        observed_at: 1,
        topic: 'hive/test',
        envelope: {},
        source_region: null,
        destinations: [],
      });
    });
    expect(result.current.queue_depth).toEqual([1]);
    expect(result.current.stm_bytes).toEqual([100]);
    expect(result.current.tokens_lifetime).toEqual([50]);
  });

  it('appends a sample when any tracked stat changes', () => {
    const { result } = renderHook(() => useStatsHistory('r1'));
    act(() => {
      useStore.getState().applyRegionDelta({
        r1: {
          role: 'x',
          llm_model: '',
          stats: statsOverrides({ queue_depth: 2, stm_bytes: 200, tokens_lifetime: 60 }),
        },
      });
    });
    expect(result.current.queue_depth).toEqual([1, 2]);
    expect(result.current.stm_bytes).toEqual([100, 200]);
    expect(result.current.tokens_lifetime).toEqual([50, 60]);
  });

  it('dedups when only a non-tracked stat (handler_count) changes', () => {
    const { result } = renderHook(() => useStatsHistory('r1'));
    act(() => {
      useStore.getState().applyRegionDelta({
        r1: {
          role: 'x',
          llm_model: '',
          stats: statsOverrides({ handler_count: 99 }),
        },
      });
    });
    // handler_count is not a sparkline; the three tracked values are
    // unchanged, so no new sample should be appended.
    expect(result.current.queue_depth).toEqual([1]);
  });
});
